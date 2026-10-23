"""按港区舰队编号同步活动图的心情存档，复用已有配置事务与字段。"""

import copy

from module.base.emotion import EMOTION_ROTATION_TASKS
from module.config.deep import deep_get, deep_set


SHARED_SUFFIXES = ('Value', 'Record', 'RecoveryState', 'Recover', 'Oath', 'Onsen')
SHARED_SLOTS = {'none': (), 'fleet1': (1,), 'fleet2': (2,), 'both': (1, 2)}


def shared_fleet_id(data, task, slot):
    """未选择共享的槽位返回 None；身份使用港区编号而非任务内一、二队。"""
    if task not in EMOTION_ROTATION_TASKS:
        return None
    option = deep_get(data, f'{task}.EventRotation.SharedFleet', default='none')
    if slot not in SHARED_SLOTS[option]:
        return None
    return deep_get(data, f'{task}.Fleet.Fleet{slot}')


def shared_groups(data, validate=False):
    """收集主动选择共享的活动槽位；保存入口验证不能成立的共享配置。"""
    groups = {}
    public = deep_get(data, 'General.PublicEmotion', default={})
    public_tasks = {name.strip() for name in (public.get('Tasks') or '').split(',')}
    for task in EMOTION_ROTATION_TASKS:
        option = deep_get(data, f'{task}.EventRotation.SharedFleet', default='none')
        if option == 'none':
            continue
        if validate:
            if public.get('Enable') and task in public_tasks:
                raise ValueError(f'{task} 不能同时使用公共心情与按舰队共享，请先关闭其中一种')
            if ('calculate' not in deep_get(data, f'{task}.Emotion.Mode', default='calculate') or
                    deep_get(data, f'{task}.Campaign.Mode', default='normal') != 'normal'):
                raise ValueError(f'{task} 按舰队共享需要普通模式和心情计算模式')
        selected = set()
        for slot in SHARED_SLOTS[option]:
            number = shared_fleet_id(data, task, slot)
            if validate and (type(number) is not int or not 1 <= number <= 6 or number in selected):
                raise ValueError(f'{task} 共享的舰队必须启用、编号为 1–6，且不能在两个槽位重复选择')
            selected.add(number)
            groups.setdefault(number, []).append(f'{task}.Emotion.Fleet{slot}')
    return groups


def inherit_shared_emotion(data, before, changed):
    """新加入时先继承现有共享记录，再应用本次明确编辑，供随后校准使用。"""
    previous = shared_groups(before)
    inherited = set()
    for number, members in shared_groups(data, validate=True).items():
        established = [prefix for prefix in members if prefix in previous.get(number, [])]
        source = (established or members)[0]
        values = {suffix: copy.deepcopy(deep_get(data, source + suffix)) for suffix in SHARED_SUFFIXES}
        for prefix in members:
            if prefix in established:
                continue
            task, _, fleet = prefix.split('.')
            old_number = shared_fleet_id(before, task, int(fleet[-1]))
            if (old_number is not None and old_number != number and not established and
                    prefix + 'Value' not in changed):
                raise ValueError(f'{task} 共享舰队已改为港区第 {number} 队，请同时填写这支新舰队的实测心情')
            for suffix, value in values.items():
                if prefix + suffix not in changed:
                    path = prefix + suffix
                    if deep_get(data, path) != value:
                        deep_set(data, path, copy.deepcopy(value))
                        inherited.add(path)
    return inherited


def sync_shared_emotion(data, before, changed):
    """锁内合并共享字段；加入继承已有队伍，明确校准或条件编辑同步全组。

    同一事务给同一港区队伍写入互相矛盾的值时拒绝整次保存，不能按字段次序选赢家。
    不同步控制线、预留值与道中队记录，退出共享时保留原字段。
    """
    previous = shared_groups(before)
    synced = set()
    for number, members in shared_groups(data, validate=True).items():
        sources = [prefix for prefix in members
                   if any(prefix + suffix in changed for suffix in SHARED_SUFFIXES)]
        established = [prefix for prefix in members if prefix in previous.get(number, [])]
        joining = set(members) != set(established)
        if not sources and not joining:
            continue
        # 新槽位连入已有港区队时，自己的旧数值和恢复地点不能覆盖共享账本。
        # 显式填写实测值或恢复条件仍作为本次编辑生效。
        source = sources[0] if sources else (established or members)[0]
        values = {suffix: deep_get(data, source + suffix) for suffix in SHARED_SUFFIXES}
        for other in sources[1:]:
            if any(deep_get(data, other + suffix) != values[suffix] for suffix in SHARED_SUFFIXES):
                raise ValueError(f'港区第 {number} 舰队的共享心情有冲突，请只在一个任务中校准或修改恢复条件')
        for prefix in members:
            for suffix, value in values.items():
                path = prefix + suffix
                if deep_get(data, path) != value:
                    deep_set(data, path, copy.deepcopy(value))
                    synced.add(path)
    return synced
