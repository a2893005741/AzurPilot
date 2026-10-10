"""心情调度的共享规则和纯计算函数；恢复模型见 ``module.combat.emotion_state``。"""

# 仅重复刷图任务参与心情轮转，限次 SP 与活动开图保留各自的完成判定。
EMOTION_ROTATION_TASKS = ('Event', 'Event2', 'Event3')

# 情绪控制阈值：当情绪低于此值时触发等待/延迟
DIC_LIMIT = {
    'keep_exp_bonus': 120,     # 保持经验加成（心情开心）
    'prevent_green_face': 40,  # 防止绿脸
    'prevent_yellow_face': 30, # 防止黄脸
    'prevent_red_face': 2,     # 防止红脸
}


def fleet_battle_counts(battle, order, fleet2):
    """按出战顺序分配战斗次数，未启用的第二舰队不参与。"""
    if not fleet2:
        return battle, 0
    if order == 'fleet1_mob_fleet2_boss':
        return max(battle - 1, 0), min(battle, 1)
    if order == 'fleet1_boss_fleet2_mob':
        return min(battle, 1), max(battle - 1, 0)
    if order == 'fleet1_all_fleet2_standby':
        return battle, 0
    if order == 'fleet1_standby_fleet2_all':
        return 0, battle
    raise ValueError(f'Unknown fleet order: {order}')
