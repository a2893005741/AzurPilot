"""重复活动图的逐局轮换：优先消化即将溢出的恢复量，保留真实冷却。"""

from datetime import datetime
from statistics import median

from module.base.emotion import DIC_LIMIT, EMOTION_ROTATION_TASKS, fleet_battle_counts
from module.combat.emotion_state import DIC_RECOVER, DIC_RECOVER_MAX
from module.config.deep import deep_get
from module.config.emotion_recovery import estimate_emotion_lower


def rotation_settings(data, task):
    """关卡、编队或双倍书改变后，不再复用旧图的耗时与成本。"""
    paths = ('Campaign.Event', 'Campaign.Name', 'Campaign.Mode', 'Campaign.Use2xBook',
             'StopCondition.MapAchievement', 'Fleet.Fleet1', 'Fleet.Fleet2', 'Fleet.FleetOrder')
    return [deep_get(data, f'{task}.{path}') for path in paths]


def rotation_stats(data, task):
    """只有设置仍对应当前地图的已完成记录才参与预测。"""
    stats = deep_get(data, f'{task}.EventRotation.Stats')
    if stats and stats['settings'] == rotation_settings(data, task):
        return stats
    return None


def record_event_rotation(config, costs, seconds, now, settings):
    """完整出击后原子保存实际成本、平滑耗时及轮换顺序所需的完成时间。"""
    task = config.task.command
    # 用户在图内更换关卡或编队时，本局样本不能记到新设置名下。
    if settings != rotation_settings(config.data, task):
        return
    previous = rotation_stats(config.data, task)
    duration = seconds if previous is None else previous['duration'] * .75 + seconds * .25
    config.cross_set(f'{task}.EventRotation.Stats', {
        'settings': settings,
        'costs': list(costs), 'duration': duration, 'last_run': now.isoformat(),
    })


def rotation_score(data, task, now, horizon):
    """比较能否完整出击、距恢复上限的时间和上次出击时间。

    心情上限不同不能直接比较数值；以各队补满所需时间衡量恢复压力。
    下一局结束前都会满的队伍按最久未出击排序，减少无意义的小幅抢占。
    新队列尚无地图成本时只用配置推断参战队，准确成本仍由原有出击预检确认。
    """
    emotion = deep_get(data, f'{task}.Emotion', default={})
    if 'calculate' not in emotion.get('Mode', 'calculate'):
        return None
    stats = rotation_stats(data, task)
    fleet = deep_get(data, f'{task}.Fleet', default={})
    if stats:
        costs = stats['costs']
    else:
        counts = fleet_battle_counts(2, fleet.get('FleetOrder', 'fleet1_mob_fleet2_boss'), fleet.get('Fleet2', 0))
        per_battle = 4 if deep_get(data, f'{task}.Campaign.Use2xBook', default=False) else 2
        costs = tuple(count * per_battle for count in counts)
    public = deep_get(data, 'General.PublicEmotion', default={})
    public_tasks = [name.strip() for name in (public.get('Tasks') or '').split(',')]
    if public.get('Enable') and task in public_tasks:
        groups = [(public, 'Fleet', sum(costs))]
    else:
        groups = [(emotion, f'Fleet{i}', cost) for i, cost in enumerate(costs, 1) if cost]
    ready = True
    fill_seconds = []
    for group, prefix, cost in groups:
        value = estimate_emotion_lower(group, prefix, now)
        if value is None:
            return None
        recover = group.get(f'{prefix}Recover', 'not_in_dormitory')
        speed = DIC_RECOVER[recover] + int(group.get(f'{prefix}Oath', False)) + int(
            group.get(f'{prefix}Onsen', False))
        cap = 150 if group.get(f'{prefix}Onsen') else DIC_RECOVER_MAX[recover]
        control = group.get(f'{prefix}Control', 'prevent_green_face')
        target = DIC_LIMIT[control] + (min(cost, 29) if control == 'keep_exp_bonus' else cost)
        waiting = emotion.get('RecoveryWait') or []
        key = 'Public' if prefix == 'Fleet' else prefix.removeprefix('Fleet')
        if key in waiting:
            target = max(target, min(emotion.get('MinReserve', 0), cap))
        ready &= value >= target
        fill_seconds.append(max(cap - value, 0) * 360 / speed)
    # 双队出战看恢复较慢的实际参战队，不让满心情的待命队或低耗 Boss 队掩盖短板。
    pressure = max(fill_seconds, default=0)
    last_run = datetime.fromisoformat(stats['last_run']) if stats else datetime.min
    age = (now - last_run).total_seconds()
    return ready, -max(pressure - horizon, 0), age, -pressure


def order_event_tasks(data, tasks, now):
    """只交换到期活动任务的原有槽位，不唤醒冷却任务或越过其他任务。"""
    durations = [stats['duration'] for task in tasks
                 if task.command in EMOTION_ROTATION_TASKS
                 and (stats := rotation_stats(data, task.command))]
    # 未完成首局之前不猜测耗时，直接按距满心情的时间排序。
    horizon = median(durations) if durations else 0
    scores = {task.command: rotation_score(data, task.command, now, horizon)
              for task in tasks if task.command in EMOTION_ROTATION_TASKS}
    candidates = [task for task in tasks if scores.get(task.command) is not None]
    candidates.sort(key=lambda task: scores[task.command], reverse=True)
    ordered = iter(candidates)
    return [next(ordered) if scores.get(task.command) is not None else task for task in tasks]
