"""心情恢复的共享规则和纯计算函数。"""

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

DIC_LIMIT = {
    'keep_exp_bonus': 120,
    'prevent_green_face': 40,
    'prevent_yellow_face': 30,
    'prevent_red_face': 2,
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


def emotion_recovery_speed(recover, oath=False, onsen=False):
    """返回每个 6 分钟周期恢复的心情点数。"""
    speed = DIC_RECOVER[recover]
    if oath:
        speed += OATH_RECOVER
    if onsen:
        speed += ONSEN_RECOVER
    return speed // 10


def calculate_emotion_recovery(value, recover, elapsed, oath=False, onsen=False):
    """根据经过秒数返回当前心情值和未满一点的恢复余数。"""
    speed = emotion_recovery_speed(recover, oath=oath, onsen=onsen)
    recovery = speed * max(elapsed, 0) / SECONDS_PER_TICK
    recovered_points = int(recovery)
    current = min(max(int(value), 0) + recovered_points, DIC_RECOVER_MAX[recover])
    return current, recovery - recovered_points
