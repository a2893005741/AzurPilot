"""调度阶段的心情余量估算。

心情的值、记录时间和恢复相位由运行器作为三件套原子写回。这里只在副本上推进，
不在读取配置时回写：回写会让加载基线与保存前重读的值不一致，触发配置事务的
心情防覆盖保护，丢弃运行器写入的扣减。
"""

from module.base.emotion import DIC_LIMIT, fleet_battle_counts
from module.combat.emotion_state import EmotionRecoveryState
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
        value = estimate_emotion_lower(group, prefix, now)
        if value is None:
            return None
        margins.append(value - DIC_LIMIT[group.get(f'{prefix}Control', 'prevent_green_face')])
    return min(margins) if margins else None


def estimate_emotion_lower(group, prefix, now):
    """返回舰队在 ``now`` 时刻的心情下限，与出击控制使用同一口径。

    恢复存档有效时按相位推进取下限；存档缺失或不一致时，运行器会以当前值重建起点，
    这里同样不计入记录之后的恢复，避免排序高估尚未校准的舰队。

    Args:
        group (dict): Emotion 或 PublicEmotion 分组。
        prefix (str): 'Fleet1'、'Fleet2' 或 'Fleet'。
        now (datetime): 估算时刻。

    Returns:
        int | None: 心情下限；值不是数字时返回 None。
    """
    value = group.get(f'{prefix}Value')
    if not isinstance(value, (int, float)):
        return None
    try:
        state = EmotionRecoveryState.restore(
            group.get(f'{prefix}RecoveryState'), value, group.get(f'{prefix}Record'),
            group.get(f'{prefix}Recover'), group.get(f'{prefix}Oath', False),
            group.get(f'{prefix}Onsen', False))
        if now >= state.record:
            state.advance(now)
    except (ValueError, TypeError, AttributeError):
        return value
    return state.lower
