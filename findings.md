# 发现与决策

## 需求
- 修复全量 unittest 中两个图片误报、两个委托断言和一个日报临时数据库锁。
- 保留用户现有 `CLAUDE.md` 修改，不提交、不推送。

## 研究发现
- 两张 PNG 本体可由 Pillow 独立校验；失败由 WebUI 伪 PIL 替换 `sys.modules` 后破坏旧 `Image` 引用引起。
- `Commission_DynamicProgramming` 已由提交 `3b99d4df22` 正式改为默认 true。
- 12 小时 deadline 下，延迟 1 个与 3 个高价值任务的整数阈值都为 43199；单调不增成立，严格递减不成立。
- 日报测试在状态离开 `generating` 后就停止等待，但 `sending` 是中间态，`sent` 后后台线程仍会执行数据库 cleanup。

## 技术决策
| 决策 | 理由 |
|------|------|
| 伪 PIL 只在真实 PIL 尚未加载时安装 | 保留 WebUI 冷启动优化，同时避免破坏真实 Pillow 进程状态 |
| 日报公开等待方法以 active 集合和条件变量为准 | `finally` 清理后才移除 active，且无需长期保存线程对象 |

## 遇到的问题
| 问题 | 解决方案 |
|------|---------|
| 暂无 | - |
