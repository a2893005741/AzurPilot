"""作战委托的维护公告与每周计划，迁自上游执行器。"""

import re
from datetime import datetime, timedelta, timezone

import requests

from module.config.time_source import now as current_time
from module.config.utils import SERVER_TO_TIMEZONE
from module.logger import logger

HANDOVER_WEEKDAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
HANDOVER_WEEKDAY_NAMES = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
HANDOVER_MAINTAIN_API = 'https://api-blhx-maintain.nanoda.work/api/maintenance'
HANDOVER_MAINTAIN_TIMEZONE = re.compile(r'^UTC([+-])(\d{1,2})(?::?(\d{2}))?$')
HANDOVER_MAINTAIN_LEAD_MINUTES = 10


class HandoverSchedule:
    """只决定计划，不点击游戏界面。"""

    _handover_consume_all = False
    _handover_maintenance = False

    def _select_handover_plan(self):
        self._handover_consume_all = False
        self._handover_maintenance = False
        maintain, _ = self.handover_maintain_state()
        if maintain is not None:
            target = maintain - timedelta(minutes=HANDOVER_MAINTAIN_LEAD_MINUTES)
            if current_time() < target:
                self.config.task_delay(target=target)
                return False
            self._handover_maintenance = True
            return True
        self._handover_consume_all, _ = self.handover_consume_all_book_state()
        if self._handover_consume_all or self.config.OperationHandover_BattleCount > 0:
            return True
        targets = []
        if self.config.OperationHandover_ConsumeAllBook:
            target = self.handover_consume_all_book_next_time()
            if target is not None:
                targets.append(target)
        if self.config.OperationHandover_MaintainOverride:
            targets.append((current_time() + timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0))
        if targets:
            self.config.task_delay(target=min(targets))
        elif self.config.OperationHandover_ConsumeAllBook:
            self.config.task_delay(minute=30)
        else:
            self.config.cross_set(keys='OperationHandover.Scheduler.Enable', value=False)
        return False

    @staticmethod
    def handover_week_key(time):
        """把时间换算成「年+周数」字符串，用来判断本周是否已经触发过。

        刻意不带连字符，避免被配置系统当成日期解析。

        Args:
            time (datetime.datetime): 时间。

        Returns:
            str: 如 `2026W37`。
        """
        year, week, _ = time.isocalendar()
        return f'{year}W{week:02d}'

    def handover_maintain_query(self):
        """查询停服维护接口，取出当前游戏服务器的那一份公告。

        接口顶层是国服新闻聚合出来的结果，各服务器自己的公告在 `servers` 里，
        并且带各自的时区。只有拿不到 `servers`（旧版接口）时才退回顶层数据。

        Returns:
            tuple[dict | None, datetime.timedelta, str]:
                (维护公告, 公告时间所用的兜底时区, 失败原因)。取不到公告时公告为 None。
        """
        server = self.config.SERVER
        try:
            response = requests.get(HANDOVER_MAINTAIN_API, timeout=10).json()
        except Exception as e:
            logger.warning(f'[作战委托] 查询维护时间失败，按不维护处理: {e}')
            return None, timedelta(), '查询维护时间失败'

        data = response.get('data') if isinstance(response, dict) else None
        if not isinstance(data, dict):
            return None, timedelta(), '维护接口格式无效'
        if not data:
            detail = response.get('message') or response.get('status')
            logger.warning(f'[作战委托] 维护接口没有返回数据，按不维护处理: {detail}')
            return None, timedelta(), '维护接口没有返回数据'

        servers = data.get('servers')
        if not isinstance(servers, dict) or not servers:
            # 顶层公告来自国服新闻，退回它时只能按国服时区解释
            logger.warning('[作战委托] 维护接口没有按服务器返回数据，退回顶层公告（国服）')
            return data, SERVER_TO_TIMEZONE['cn'], ''

        payload = servers.get(server)
        if not isinstance(payload, dict) or not payload:
            errors = data.get('server_errors')
            reason = errors.get(server) if isinstance(errors, dict) else None
            reason = reason or '接口未返回该服务器'
            logger.warning(f'[作战委托] {server} 的维护公告查询失败，按不维护处理: {reason}')
            return None, timedelta(), f'{server} 维护公告查询失败'

        return payload, SERVER_TO_TIMEZONE.get(server, SERVER_TO_TIMEZONE['cn']), ''

    def handover_maintain_timezone(self, payload, default):
        """解析维护公告所用的服务器时区。

        接口在每条服务器公告里给了 timezone（如 `UTC+8`），以它为准；缺失或者
        格式不认识时用兜底时区。

        Args:
            payload (dict): 一条服务器维护公告。
            default (datetime.timedelta): 兜底时区偏移。

        Returns:
            datetime.timedelta: 相对 UTC 的时区偏移。
        """
        text = str(payload.get('timezone', '')).strip().upper()
        match = HANDOVER_MAINTAIN_TIMEZONE.match(text)
        if not match:
            logger.warning(f'[作战委托] 无法识别的服务器时区 {text!r}，按 {default} 处理')
            return default

        hours, minutes = int(match.group(2)), int(match.group(3) or 0)
        if hours >= 24 or minutes >= 60:
            return default
        offset = timedelta(hours=hours, minutes=minutes)
        return offset if match.group(1) == '+' else -offset

    def handover_maintain_state(self):
        """今天有没有停服维护，有的话返回维护开始时间。

        数据来自 api-blhx-maintain，按当前游戏服务器取对应公告。公告里的时间是
        服务器本地时间，先换算成本机时间再和当前时间比较；时间不是今天的、或者
        已经过去的都当作没有维护。

        Returns:
            tuple[datetime.datetime | None, str]: (维护开始时间, 原因)。
        """
        if not self.config.OperationHandover_MaintainOverride:
            return None, '开关未开启'

        payload, default, error = self.handover_maintain_query()
        if payload is None:
            return None, error

        try:
            start = datetime.strptime(
                f"{payload.get('maintenance_date', '')} {payload.get('start_time', '')}",
                '%Y-%m-%d %H:%M')
        except ValueError:
            logger.warning(f'[作战委托] 维护公告时间无法识别，按不维护处理: '
                           f"{payload.get('maintenance_date')} {payload.get('start_time')}")
            return None, '维护公告时间无法识别'

        # 服务器本地时间 → 本机时间，后续调度用的都是本机时间
        offset = self.handover_maintain_timezone(payload, default)
        start = start.replace(tzinfo=timezone(offset)).astimezone().replace(tzinfo=None)

        now = current_time()
        if start <= now:
            return None, f'{start} 已经过去'
        if start.date() != now.date():
            return None, f'下次维护 {start}，不是今天'

        name = payload.get('name') or self.config.SERVER
        return start, (f'今天 {start} 停服维护（{name}），'
                       f'维护前 {HANDOVER_MAINTAIN_LEAD_MINUTES} 分钟运行')

    def handover_consume_all_book_trigger(self):
        """解析一键消耗委托书的触发配置。

        Returns:
            tuple[int, int, int] | None: (周几, 时, 分)，配置不合法返回 None。
        """
        weekday = self.config.OperationHandover_ConsumeAllBookWeekday
        if weekday not in HANDOVER_WEEKDAYS:
            logger.warning(f'[作战委托] 无法识别的星期: {weekday}')
            return None

        trigger = str(self.config.OperationHandover_ConsumeAllBookTime)
        try:
            hour, minute = [int(part) for part in trigger.split(':')[:2]]
            if not 0 <= hour < 24 or not 0 <= minute < 60:
                raise ValueError
        except ValueError:
            logger.warning(f'[作战委托] 无法识别的触发时间: {trigger}')
            return None

        return HANDOVER_WEEKDAYS.index(weekday), hour, minute

    def handover_consume_all_book_state(self):
        """当前该不该执行一键消耗委托书，以及不执行的原因。

        周几和几点几分由用户配置，本周成功触发过一次就不再触发。委托没开起来
        （比如触发时正好有委托在进行）不算触发过，下一次运行会接着试。

        Returns:
            tuple[bool, str]: (是否执行, 不执行的原因)。
        """
        if not self.config.OperationHandover_ConsumeAllBook:
            return False, '开关未开启'

        now = current_time()
        if self.config.OperationHandover_ConsumeAllBookRecord == self.handover_week_key(now):
            return False, '本周已触发过'

        trigger = self.handover_consume_all_book_trigger()
        if trigger is None:
            return False, '触发日或触发时间配置不合法'
        weekday, hour, minute = trigger

        if now.weekday() != weekday:
            name = HANDOVER_WEEKDAY_NAMES[weekday]
            if now.weekday() < weekday:
                return False, f'还没到{name}'
            else:
                return False, f'{name}已经过了，等下周'

        if (now.hour, now.minute) < (hour, minute):
            return False, f'还没到触发时间 {hour:02d}:{minute:02d}'

        return True, ''

    def handover_consume_all_book_waiting(self):
        """一键消耗委托书今天还有机会触发吗。

        今天就是触发日、本周又还没触发过时，本次没开成委托也不能把任务推迟到
        次日——次日已经过了触发日，这一周的一键消耗就整个没了。

        Returns:
            bool: 应该稍后重试而不是等次日返回 True。
        """
        if not self.config.OperationHandover_ConsumeAllBook:
            return False

        now = current_time()
        if self.config.OperationHandover_ConsumeAllBookRecord == self.handover_week_key(now):
            return False

        trigger = self.handover_consume_all_book_trigger()
        if trigger is None:
            return False
        return now.weekday() == trigger[0]

    def handover_consume_all_book_next_time(self):
        """下一次一键消耗委托书的触发时刻。

        委托次数为 0 时用这个时间当下一次运行时间，中间不用进游戏。今天就是
        触发日但时间已经过了（或者本周已经触发过）时顺延到下周。

        Returns:
            datetime.datetime | None: 下一次触发时刻，触发配置不合法返回 None。
        """
        trigger = self.handover_consume_all_book_trigger()
        if trigger is None:
            return None

        weekday, hour, minute = trigger
        now = current_time()
        target = (now + timedelta(days=(weekday - now.weekday()) % 7)).replace(
            hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=7)
        return target

    def handover_consume_all_book_record(self):
        """记下本周已经触发过一键消耗委托书。"""
        week = self.handover_week_key(current_time())
        self.config.OperationHandover_ConsumeAllBookRecord = week
        logger.info(f'[作战委托] 本周已触发一键消耗委托书，记录 {week}')
