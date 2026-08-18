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
