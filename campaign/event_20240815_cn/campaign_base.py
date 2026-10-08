from module.base.timer import Timer
from module.base.utils import area_in_area, area_pad
from module.campaign.campaign_base import CampaignBase as CampaignBase_
from module.campaign.campaign_ui import MODE_SWITCH_1, MODE_SWITCH_2, MODE_SWITCH_20241219
from module.combat.assets import GET_ITEMS_1
from module.exception import CampaignNameError
from module.logger import logger
from module.ui.page import page_event


class CampaignBase(CampaignBase_):
    entrance_timer = Timer(2)

    def get_story_entrance(self):
        """
        Returns:
            Button: Or None if nothing matched.
        """
        # 复刻使用左下角作战／剧情选择器，剧情关卡移入剧情模式；
        # 该布局下不再扫描黑色剧情入口，避免把左下角深色控件当作入口点击。
        if MODE_SWITCH_20241219.appear(main=self):
            return None
        # 5 story stage after clearing A2
        # You can't go anywhere unless you clicked it
        button = self.image_color_button(
            area=(66, 200, 1200, 690), color=(0, 0, 0),
            threshold=15, encourage=10, name='STORY_ENTRANCE')
        if button is None:
            return None
        # Blacklisted area
        if area_in_area(button.button, area_pad((424, 522, 444, 542), pad=-20)):
            return None
        return button

    def handle_story_entrance(self):
        if not self.entrance_timer.reached():
            return False

        entrance = self.get_story_entrance()
        if entrance is None:
            return False

        self.device.click(entrance)
        self.entrance_timer.reset()
        return True

    def ensure_no_stage_entrance(self, skip_first_screenshot=True):
        logger.info('ensure_no_stage_entrance')
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.is_in_stage_page():
                # End
                try:
                    self._get_stage_name(self.device.image)
                    return True
                except (IndexError, CampaignNameError):
                    pass
                # Click
                if self.handle_story_entrance():
                    continue
            if self.handle_story_skip():
                self.interval_clear(GET_ITEMS_1)
                self.entrance_timer.clear()
                continue
            if self.appear_then_click(GET_ITEMS_1, offset=(20, 20), interval=3):
                self.entrance_timer.clear()
                continue

    def handle_in_stage(self):
        # Click after stage ended
        if self.is_in_stage_page():
            if self.handle_story_entrance():
                return False
        return super().handle_in_stage()

    def handle_get_chapter_additional(self):
        # Exit when having story entrance
        if self.get_story_entrance():
            raise CampaignNameError
        return super().handle_get_chapter_additional()

    def handle_campaign_ui_additional(self):
        if self.get_story_entrance():
            self.ensure_no_stage_entrance()
            return True
        return super().handle_campaign_ui_additional()

    def campaign_set_chapter_20241219(self, chapter, stage, mode='combat'):
        """按当前选关页选择首发或复刻的导航布局。

        首发使用普通／困难开关；2026-10-08 自选复刻改用侧边栏和左下角作战／剧情选择器，
        与 event_20240912_cn 的处理一致，不能由服务器决定布局。

        Args:
            chapter (str): 章节标识，如 'a'、'c'、'ex_sp'。
            stage (str): 关卡编号。
            mode (str): 战役模式。

        Returns:
            bool: 新布局导航已处理时返回 True；旧布局交给后续活动分支。

        Raises:
            CampaignNameError: 布局尚未识别，交给选关循环获取新截图重试。

        Pages:
            in: 任意页面
            out: page_event
        """
        self.ui_goto_event()
        if MODE_SWITCH_20241219.appear(main=self):
            has_aside = True
        elif MODE_SWITCH_1.appear(main=self) or MODE_SWITCH_2.appear(main=self):
            has_aside = False
        else:
            # 页面动画中不猜测布局，避免把新版作战模式当作旧困难开关反复点击。
            raise CampaignNameError

        logger.attr('活动选关布局', '侧边栏' if has_aside else '旧版模式开关')
        self.config.override(
            MAP_CHAPTER_SWITCH_20241219=has_aside,
            MAP_HAS_MODE_SWITCH=has_aside and chapter in ['a', 'b', 'c', 'd'],
        )
        return super().campaign_set_chapter_20241219(chapter, stage, mode)

    def handle_exp_info(self):
        # Random background hits EXP_INFO_B
        if self.ui_page_appear(page_event):
            return False
        return super().handle_exp_info()
