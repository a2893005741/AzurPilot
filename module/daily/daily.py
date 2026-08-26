"""每日任务处理器。

自动完成碧蓝航线的每日任务，包括：
- 每日出击（商船护送、海域突进、斩首行动等）
- 每日任务的完成和奖励领取
- 剩余次数检测和任务切换

每日任务类型通过 DAILY_MISSION_LIST 定义，
每日有固定的出击次数限制，通过 OCR 读取剩余次数。

继承自 Combat，可直接调用战斗流程。
"""

import cv2
import numpy as np

import module.config.server as server
from module.base.timer import Timer
from module.base.utils import get_color
from module.combat.assets import BATTLE_PREPARATION
from module.combat.combat import Combat
from module.daily.assets import *
from module.exception import GameStuckError
from module.handler.assets import GUILD_POPUP_CANCEL, GUILD_POPUP_CONFIRM
from module.logger import logger
from module.ocr.ocr import Digit
from module.ui.assets import BACK_ARROW, DAILY_CHECK
from module.ui.page import page_campaign_menu, page_daily

# 每日任务列表
DAILY_MISSION_LIST = [DAILY_MISSION_1, DAILY_MISSION_2, DAILY_MISSION_3]
if server.server != 'jp':
    OCR_REMAIN = Digit(OCR_REMAIN, threshold=128, alphabet='01234')
else:
    OCR_REMAIN = Digit(OCR_REMAIN, letter=(222, 223, 222), threshold=128, alphabet='01234')
OCR_DAILY_FLEET_INDEX = Digit(OCR_DAILY_FLEET_INDEX, letter=(90, 154, 255), threshold=128, alphabet='123456')


class Daily(Combat):
    """每日任务执行器。

    管理每日任务的选择、执行和完成检测。
    每个每日任务有独立的活跃状态和剩余次数。

    Attributes:
        daily_current (int): 当前正在处理的每日任务索引。
        daily_checked (list): 已检查过的每日任务列表。
        emergency_module_development (bool): 是否为紧急模块开发任务。
    """
    daily_current: int
    daily_checked: list
    emergency_module_development = False

    def is_active(self):
        color = get_color(image=self.device.image, area=DAILY_ACTIVE.area)
        color = np.array(color).astype(float)
        color = (np.max(color) + np.min(color)) / 2
        active = color > 30
        if active:
            logger.attr(f'每日任务_{self.daily_current}', '活跃')
        else:
            logger.attr(f'每日任务_{self.daily_current}', '未活跃')
        return active

    def _start_daily_switch(self, button):
        self._daily_switch = {
            'previous_card': self.image_crop(DAILY_ENTER, copy=True),
            'target_card': self.image_crop(button, copy=True),
            'target_seen': False,
            'target_similarity': 0.,
            'target_timer': Timer(1, count=3).start(),
            'timeout': Timer(5, count=10).start(),
        }
        self.device.click(button)

    @staticmethod
    def _daily_card_difference(current_frame, previous_frame):
        current_frame = cv2.GaussianBlur(current_frame, (0, 0), 5)
        previous_frame = cv2.GaussianBlur(previous_frame, (0, 0), 5)
        return np.mean(np.abs(current_frame.astype(np.int16) - previous_frame.astype(np.int16)))

    @staticmethod
    def _daily_card_similarity(current_frame, target_frame):
        target_frame = cv2.resize(
            target_frame,
            current_frame.shape[1::-1],
            interpolation=cv2.INTER_LINEAR,
        )
        current_frame = cv2.cvtColor(cv2.GaussianBlur(current_frame, (0, 0), 3), cv2.COLOR_RGB2GRAY)
        target_frame = cv2.cvtColor(cv2.GaussianBlur(target_frame, (0, 0), 3), cv2.COLOR_RGB2GRAY)
        similarity = cv2.matchTemplate(current_frame, target_frame, cv2.TM_CCOEFF_NORMED)[0, 0]
        return float(similarity) if np.isfinite(similarity) else 0.

    def _daily_switch_complete(self):
        """推进一次卡片切换检测，完成后返回 True。"""
        switch = self._daily_switch
        if switch is None:
            return True

        if not self.handle_daily_additional():
            current_frame = self.image_crop(DAILY_ENTER, copy=False)
            difference = self._daily_card_difference(current_frame, switch['previous_card'])
            similarity = self._daily_card_similarity(current_frame, switch['target_card'])
            switch['target_similarity'] = max(switch['target_similarity'], similarity)
            target_matched = difference > 3 and similarity > 0.6

            if not switch['target_seen']:
                if target_matched:
                    switch['target_seen'] = True
                    switch['target_timer'].reset()
            else:
                # 确认期持续验证目标卡片身份，但不要求逐帧静止，避免目标卡片的
                # 光效和粒子动画重置计时器。
                if not target_matched:
                    switch['target_seen'] = False
                    switch['target_timer'].reset()
                elif switch['target_timer'].reached():
                    self._daily_switch = None
                    return True

        if switch['timeout'].reached():
            raise GameStuckError(
                f'[每日任务] 卡片切换等待超时，目标相似度={switch["target_similarity"]:.3f}'
            )
        return False

    def next(self):
        self.daily_current += 1
        logger.info(f'[每日任务] 切换到 {self.daily_current}')
        if self.daily_current > 7:
            return
        self._start_daily_switch(DAILY_NEXT)

    def prev(self):
        self.daily_current -= 1
        logger.info(f'[每日任务] 切换到 {self.daily_current}')
        self._start_daily_switch(DAILY_PREV)

    def handle_daily_additional(self):
        if self.handle_guild_popup_cancel():
            return True
        return self.appear(GUILD_POPUP_CONFIRM, offset=self._popup_offset) \
            and self.appear(GUILD_POPUP_CANCEL, offset=self._popup_offset)

    def get_daily_stage_and_fleet(self):
        """
        获取每日任务的关卡和舰队配置。

        Returns:
            int: 关卡索引，0 到 3。
            int: 舰队索引，1 到 6。
        """
        if self.emergency_module_development:
            # daily_current 含义
            # 1 限时兵装训练 Emergency Module Development
            # 2 商船护送 Escort Mission
            # 3 海域突进 Advance Mission
            # 4 斩首行动 Fierce Assault
            # 5 战术研修 Tactical Training
            # 6 破交作战 Supply Line Disruption
            # 7 兵装训练 Module Development
            fleets = [
                0,
                self.config.Daily_EmergencyModuleDevelopmentFleet,
                self.config.Daily_EscortMissionFleet,
                self.config.Daily_AdvanceMissionFleet,
                self.config.Daily_FierceAssaultFleet,
                self.config.Daily_TacticalTrainingFleet,
                0,  # 破交作战，需要手动完成或通过每日跳过
                self.config.Daily_ModuleDevelopmentFleet,
                0
            ]
            stages = [
                0,
                self.config.Daily_EmergencyModuleDevelopment,
                self.config.Daily_EscortMission,
                self.config.Daily_AdvanceMission,
                self.config.Daily_FierceAssault,
                self.config.Daily_TacticalTraining,
                self.config.Daily_SupplyLineDisruption,
                self.config.Daily_ModuleDevelopment,
                0
            ]
        else:
            # daily_current 含义
            # 1 战术研修 Tactical Training
            # 2 破交作战 Supply Line Disruption
            # 3 兵装训练 Module Development
            # 4 (未开放)
            # 5 商船护送 Escort Mission
            # 6 海域突进 Advance Mission
            # 7 斩首行动 Fierce Assault
            fleets = [
                0,
                self.config.Daily_TacticalTrainingFleet,
                0,  # 破交作战，需要手动完成或通过每日跳过
                self.config.Daily_ModuleDevelopmentFleet,
                0,  # 空
                self.config.Daily_EscortMissionFleet,
                self.config.Daily_AdvanceMissionFleet,
                self.config.Daily_FierceAssaultFleet,
                0
            ]
            stages = [
                0,
                self.config.Daily_TacticalTraining,
                self.config.Daily_SupplyLineDisruption,
                self.config.Daily_ModuleDevelopment,
                0,  # 空
                self.config.Daily_EscortMission,
                self.config.Daily_AdvanceMission,
                self.config.Daily_FierceAssault,
                0
            ]
        dic = {
            'skip': 0,
            'first': 1,
            'second': 2,
            'third': 3,
        }
        fleet = fleets[self.daily_current]
        stage = stages[self.daily_current]

        if stage not in dic:
            logger.warning(f'未知的每日关卡 `{stage}` from daily_current={self.daily_current}')
        stage = dic.get(stage, 0)
        return int(stage), int(fleet)

    @property
    def supply_line_disruption_index(self):
        if self.emergency_module_development:
            return 2
        else:
            return 2

    @property
    def empty_index(self):
        if self.emergency_module_development:
            return 4
        else:
            return 4

    def daily_execute(self, remain=3, stage=1, fleet=1):
        """
        执行每日任务。

        Args:
            remain (int): 剩余每日挑战次数。
            stage (int): 从上到下的关卡索引，1 到 3。
            fleet (int): 使用的舰队索引。

        Returns:
            bool: 成功返回 True，每日任务锁定返回 False。

        Pages:
            in: page_daily
            out: page_daily
        """
        logger.hr(f'每日任务 {self.daily_current}', level=2)
        logger.info(f'remain={remain}, stage={stage}, fleet={fleet}')

        def daily_enter_check():
            return self.appear(DAILY_ENTER_CHECK, threshold=30)

        def daily_end():
            if self.appear(BATTLE_PREPARATION, offset=(20, 20), interval=2):
                self.device.click(BACK_ARROW)
            return self.appear(DAILY_ENTER_CHECK, threshold=30) or self.appear(BACK_ARROW, offset=(30, 30))

        self.ui_click(click_button=DAILY_ENTER, check_button=daily_enter_check, appear_button=DAILY_CHECK,
                      skip_first_screenshot=True)
        if self.appear(DAILY_LOCKED, offset=(30, 30)):
            logger.info('每日锁定')
            self.ui_click(click_button=BACK_ARROW, check_button=DAILY_CHECK)
            self.device.sleep((1, 1.2))
            return False

        button = DAILY_MISSION_LIST[stage - 1]
        for n in range(remain):
            logger.hr(f'计数 {n + 1}')
            result = self.daily_enter(button)
            if not result:
                break
            if self.daily_current == self.supply_line_disruption_index:
                logger.info('潜艇每日跳过未解锁，跳过')
                self.ui_click(click_button=BACK_ARROW, check_button=daily_enter_check, skip_first_screenshot=True)
                break
            # 执行经典每日任务
            self.ui_ensure_index(fleet, letter=OCR_DAILY_FLEET_INDEX, prev_button=DAILY_FLEET_PREV,
                                 next_button=DAILY_FLEET_NEXT, fast=False, skip_first_screenshot=True)
            self.combat(emotion_reduce=False, save_get_items=False, expected_end=daily_end, balance_hp=False)

        self.ui_click(click_button=BACK_ARROW, check_button=DAILY_CHECK, additional=self.handle_daily_additional,
                      skip_first_screenshot=True)
        self.device.sleep((1, 1.2))
        return True

    def daily_enter(self, button, skip_first_screenshot=True):
        """
        进入每日任务。

        Args:
            button (Button): 每日任务入口按钮。
            skip_first_screenshot (bool): 是否跳过首次截图。

        Returns:
            bool: 战斗画面出现返回 True，每日跳过已解锁/已跳过/已领取奖励返回 False。

        Pages:
            in: DAILY_ENTER_CHECK
            out: DAILY_ENTER_CHECK 或 combat_appear
        """
        reward_received = False
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(DAILY_ENTER_CHECK, threshold=30, interval=5):
                self.device.click(button)
                continue
            if self.handle_get_items():
                reward_received = True
                continue
            if self.config.Daily_UseDailySkip:
                if self.appear_then_click(DAILY_SKIP, offset=(20, 20), interval=5):
                    continue
            else:
                if self.appear_then_click(DAILY_NORMAL_RUN, offset=(20, 20), interval=5):
                    continue
            if self.handle_combat_automation_confirm():
                continue
            if self.handle_daily_additional():
                continue
            if self.handle_popup_confirm('DAILY_SKIP'):
                continue

            # 结束
            if self.appear(DAILY_SKIP, offset=(20, 20)):
                if reward_received:
                    return False
                if self.info_bar_count():
                    return False
            if self.appear(DAILY_ENTER_CHECK, threshold=30):
                if self.info_bar_count():
                    return False
            if self.combat_appear():
                return True

    def daily_check(self, n=None):
        if not n:
            n = self.daily_current
        self.daily_checked.append(n)
        logger.info(f'已检查每日 {n}')
        logger.info(f'已检查列表: {self.daily_checked}')

    def daily_run_one(self):
        logger.hr('每日运行一次', level=1)
        self.ui_ensure(page_daily)
        self.device.sleep(0.2)
        self.device.screenshot()
        self.daily_current = 1
        self._daily_switch = None
        self.emergency_module_development = self.appear(ENTRANCE_EMERGENCY_MODULE_DEVELOPMENT, offset=(25, 50))
        logger.attr('emergency_module_development', self.emergency_module_development)

        logger.info(f'已检查列表: {self.daily_checked}')

        while 1:
            if self._daily_switch is not None:
                self.device.screenshot()
                if not self._daily_switch_complete():
                    continue
            if self.daily_current > 7:
                break
            if self.daily_current in self.daily_checked:
                self.next()
                continue
            if self.daily_current == self.empty_index:
                logger.info('此每日当前未开放')
                self.daily_check()
                self.next()
                continue
            if self.appear(DAILY_LOCKED, offset=(30, 30)):
                logger.info(f'每日 {self.daily_current} 今日未开放，跳过')
                self.daily_check()
                self.next()
                continue
            stage, fleet = self.get_daily_stage_and_fleet()
            if self.daily_current == self.supply_line_disruption_index and not self.config.Daily_UseDailySkip:
                logger.info('如UseDailySkip禁用则跳过补给线破坏')
                self.daily_check()
                self.next()
                continue
            if not stage:
                logger.info(f'daily_current未设置关卡，跳过: {self.daily_current}, skip')
                self.daily_check()
                self.next()
                continue
            if self.daily_current != self.supply_line_disruption_index and not fleet:
                logger.info(f'daily_current未设置舰队，跳过: {self.daily_current}, skip')
                self.daily_check()
                self.next()
                continue
            if not self.is_active():
                self.daily_check()
                self.next()
                continue
            remain = OCR_REMAIN.ocr(self.device.image)
            if remain == 0:
                self.daily_check()
                self.next()
                continue
            else:
                self.daily_execute(remain=remain, stage=stage, fleet=fleet)
                self.daily_check()
                # 打完一次之后每日任务的顺序会乱掉, 退出再进入来重置顺序.
                self.ui_goto(page_campaign_menu)
                break

    def daily_run(self):
        self.daily_checked = [0]

        while 1:
            self.daily_run_one()

            if self.emergency_module_development and self.config.Daily_EmergencyModuleDevelopment != 'skip':
                self.daily_checked = [0]

            if all(index in self.daily_checked for index in range(1, 8)):
                logger.info('每日清除完成')
                break

    def run(self):
        """
        运行每日任务。

        Pages:
            in: 任意页面
            out: page_daily
        """
        self.daily_run()

        # 不能停留在 page_daily，因为顺序会乱掉。
        self.config.task_delay(server_update=True)
