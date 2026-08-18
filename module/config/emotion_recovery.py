"""配置加载阶段的心情恢复计算。"""

from datetime import datetime, timedelta

SECONDS_PER_TICK = 6 * 60

DIC_RECOVER = {
    'not_in_dormitory': 20,
    'dormitory_floor_1': 40,
    'dormitory_floor_2': 50,
}
DIC_RECOVER_MAX = {
    'not_in_dormitory': 119,
    'dormitory_floor_1': 150,
    'dormitory_floor_2': 150,
}
OATH_RECOVER = 10
ONSEN_RECOVER = 10


def emotion_recovery_speed(recover, oath=False, onsen=False):
    """返回每 6 分钟恢复的心情点数。"""
    speed = DIC_RECOVER[recover]
    if oath:
        speed += OATH_RECOVER
    if onsen:
        speed += ONSEN_RECOVER
    return speed // 10


def _recover_fleet(group, prefix, now):
    value_key = f'{prefix}Value'
    record_key = f'{prefix}Record'
    recover_key = f'{prefix}Recover'
    if value_key not in group or record_key not in group or recover_key not in group:
        return

    value = group[value_key]
    record = group[record_key]
    recover = group[recover_key]
    if not isinstance(value, (int, float)) or not isinstance(record, datetime):
        return
    if recover not in DIC_RECOVER:
        return

    elapsed = (now - record).total_seconds()
    if elapsed <= 0:
        return

    speed = emotion_recovery_speed(
        recover,
        oath=bool(group.get(f'{prefix}Oath', False)),
        onsen=bool(group.get(f'{prefix}Onsen', False)),
    )
    maximum = DIC_RECOVER_MAX[recover]
    recovery = speed * elapsed / SECONDS_PER_TICK
    recovered_points = int(recovery)
    new_value = min(max(int(value), 0) + recovered_points, maximum)

    group[value_key] = new_value
    if new_value >= maximum:
        group[record_key] = now.replace(microsecond=0)
        return

    fractional = recovery - recovered_points
    record_time = now.replace(microsecond=0)
    if fractional > 0:
        record_time -= timedelta(seconds=fractional * SECONDS_PER_TICK / speed)
    group[record_key] = record_time


def recover_emotion_config(data, now):
    """把任务配置中的持久化心情更新到 ``now`` 对应的当前值。"""
    for task in data.values():
        if not isinstance(task, dict):
            continue

        emotion = task.get('Emotion')
        if isinstance(emotion, dict):
            _recover_fleet(emotion, 'Fleet1', now)
            _recover_fleet(emotion, 'Fleet2', now)

        public_emotion = task.get('PublicEmotion')
        if isinstance(public_emotion, dict):
            _recover_fleet(public_emotion, 'Fleet', now)

    return data
