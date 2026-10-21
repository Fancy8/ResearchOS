# ResearchOS 文档地图

[项目首页](../README.md) · [English](../README_EN.md) · [贡献指南](../CONTRIBUTING.md)

文档分成上手指南、产品与架构基线、实际验证记录、运行手册。**设计目标不等于已实现；局部验证不等于发布完成。** 当前阶段和未完成门禁以实际实现记录及 CI 为准。

## 推荐阅读顺序

| 角色 | 路径 |
| --- | --- |
| 想试用工作流 | [安装](getting-started.md) → [研究闭环示例](research-walkthrough.md) → [当前范围](roadmap.md) |
| 前端/后端开发 | [产品基线](01-product-baseline.md) → [架构](02-architecture.md) → [数据](03-data-and-orm.md) → [API](04-api-contract.md) |
| 测试与维护 | [实现进展](implementation-status.md) → [验收进度](acceptance-progress.md) → [质量方案](07-quality-and-operations.md) |

## 产品与工程基线

| 文档 | 主要内容 |
| --- | --- |
| [来源审查](00-source-review.md) | 原始材料的审查、冲突与补充决策；私人原文未分发 |
| [产品基线](01-product-baseline.md) | F01–F15、业务规则、验收映射与后续范围 |
| [架构](02-architecture.md) | 模块职责、事务、后台任务与部署设计 |
| [数据与 ORM](03-data-and-orm.md) | 数据约束、历史语义和迁移规范 |
| [API 契约](04-api-contract.md) | 授权、幂等、版本、上传与导出协议 |
| [体验设计](05-experience-design.md) | 页面、交互、空状态和错误反馈 |
| [研发流程](06-delivery-plan.md) | 工单、迭代和评审门禁 |
| [质量与运行方案](07-quality-and-operations.md) | 测试、发布、容量与恢复设计 |

## 实现与恢复行为

| 文档 | 关注点 |
| --- | --- |
| [实现进展](implementation-status.md) / [验收进度](acceptance-progress.md) | 当前实现、历史证据与未完成验收 |
| [创建恢复交接](research-creation-handoff.md) | 原始意图、幂等回执与剩余专门用例 |
| [上传恢复](upload-recovery-acceptance.md) | 上传与解析状态的恢复边界 |
| [证据状态](evidence-state-acceptance.md) | 来源版本、捕获与阅读定位 |
| [决策状态](decision-state-acceptance.md) | 历史修订与来源快照 |
| [任务状态](task-state-acceptance.md) / [导出状态](export-state-acceptance.md) | 任务关联、导出回执与来源可用性 |

## 本地运行与维护

| 文档 | 用途 |
| --- | --- |
| [本地运行](operating-local.md) | 账户与日常开发操作 |
| [依赖交付](python-dependency-delivery.md) / [依赖安全](dependency-security.md) | 锁文件、下载与审查 |
| [进程监督](process-supervision.md) / [队列恢复](broker-recovery-runbook.md) | 本地进程和消息状态 |
| [清理](maintenance-runbook.md) / [删除日志](deletion-journal-runbook.md) | 清理边界与独立日志操作 |
| [恢复](recovery-runbook.md) / [备份调度](backup-schedule-runbook.md) | 隔离演练与备份设计，非自动生产启用 |
| [公开发布说明](publication-notes.md) / [第三方许可](../THIRD_PARTY_NOTICES.md) | 公开快照范围与来源 |

运行手册可能包含会影响数据的命令。先理解各自前提与隔离要求，不要在正式研究数据上试验删除或恢复。
