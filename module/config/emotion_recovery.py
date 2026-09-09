"""配置加载阶段的心情恢复计算。"""

from datetime import datetime, timedelta

from module.base.emotion import (
    DIC_LIMIT,
    DIC_RECOVER,
    DIC_RECOVER_MAX,
    SECONDS_PER_TICK,
    calculate_emotion_recovery,
    emotion_recovery_speed,
    fleet_battle_counts,
)
from module.config.deep import deep_get


def campaign_emotion_score(data, task, now):
    """以实际出战队的最低心情余量排序，不改写持久化记录。"""
    emotion = deep_get(data, f'{task}.Emotion', default={})
    if 'calculate' not in emotion.get('Mode', 'calculate'):
        return None
    public = deep_get(data, 'General.PublicEmotion', default={})
    public_tasks = [name.strip() for name in (public.get('Tasks') or '').split(',')]
    if public.get('Enable') and task in public_tasks:
        groups = [(public, 'Fleet')]
    else:
        fleet = deep_get(data, f'{task}.Fleet', default={})
        counts = fleet_battle_counts(2, fleet.get('FleetOrder', 'fleet1_mob_fleet2_boss'),
                                    fleet.get('Fleet2', 0))
        groups = [(emotion, f'Fleet{i}') for i, count in enumerate(counts, 1) if count]
    margins = []
    for group, prefix in groups:
        group = group.copy()
        _recover_fleet(group, prefix, now)
        value = group.get(f'{prefix}Value')
        if not isinstance(value, (int, float)):
            return None
        margins.append(value - DIC_LIMIT[group.get(f'{prefix}Control', 'prevent_green_face')])
    return min(margins) if margins else None


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

    elapsed = now.timestamp() - record.timestamp()
    if elapsed <= 0:
        return

    oath = bool(group.get(f'{prefix}Oath', False))
    onsen = bool(group.get(f'{prefix}Onsen', False))
    speed = emotion_recovery_speed(recover, oath=oath, onsen=onsen)
    maximum = DIC_RECOVER_MAX[recover]
    new_value, fractional = calculate_emotion_recovery(
        value,
        recover,
        elapsed,
        oath=oath,
        onsen=onsen,
    )

    group[value_key] = new_value
    if new_value >= maximum:
        group[record_key] = now.replace(microsecond=0)
        return

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
