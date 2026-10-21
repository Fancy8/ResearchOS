# 数据模型与 SQLAlchemy ORM 工程规范

S3 提供 25 张业务表的物理草案；S4 是空文件。本文件为补充工程设计；实际 ORM、迁移与数据库执行证据见 [implementation-status.md](implementation-status.md)。

## 领域关系与统一命名

一个 User 拥有一个 Workspace；空间下有多个 Project；课题下有多个 ResearchThread。Paper 是空间级文献，通过 project_papers 与 thread_papers 复用；Evidence 属于一个线索并固定 paper_file_id。Hypothesis 与 Evidence 的关系必须在同一线索内。Decision 有多个不可变 Revision，各自持有当时依据；Task 可以绑定其中的确切修订。Note 是空间级资产，可关联多个课题和线索。

以 S3 物理表名为准：`project_papers` 替代 PRD 的 `paper_project_links`；`thread_papers` 替代 `thread_paper_links`；`thread_notes` 替代 `thread_note_links`；`revision_no` 替代 `revision_number`。`decision_evidence_links` 统一为修订级 `decision_revision_evidence_links`。这些是同一概念的命名合并，不建立两套重复表。

UUID 稳定标识；TIMESTAMPTZ 存 UTC；截止日为 DATE；状态为 TEXT + 命名 CHECK；正文和配置为 JSONB。PK、FK、UNIQUE、CHECK、索引统一显式命名。引用父对象的复合 FK 必须覆盖 workspace_id，以及必要的 project_id/thread_id，不能只添加一个裸 UUID 外键。

## 原始 25 张业务表

完整字段草案见 S3 数据库 (private original; omitted from public snapshot)。下表给出最终实现的关键补充和验收边界，不能仅按“表数量正确”验收。

| 表 | 关键字段/约束 | 本次补充 |
| --- | --- | --- |
| users | email 大小写规范唯一、password_hash | account_status、email_verified_at；冻结用户立即撤销会话 |
| workspaces | owner_user_id UNIQUE | status；清理中禁止新写入 |
| research_profiles | workspace_id PK；JSONB 设置 | version；配置按课题分组并验证结构 |
| projects | (workspace_id,id) UNIQUE；一个默认课题部分唯一 | version；归档时间一致；默认课题切换锁空间行 |
| research_threads | (workspace_id,project_id,id) UNIQUE | current_revision、version；不可跨课题迁移 |
| papers | (workspace_id,id) UNIQUE；authors 为数组 | version；DOI 规范化用于提示，不自动合并 |
| paper_files | paper/version 唯一；最多一个 current | storage_version_id（若供应商支持）、availability_status、parser_version；最终键不可覆盖 |
| paper_pages | (paper_file_id,page_number) PK | 解析文本指纹和 parser_version；不把任意坐标当权威依据 |
| project_papers | (workspace,project,paper) PK | 关联删除前检查线索及证据依赖 |
| thread_papers | (workspace,project,thread,paper) PK | 必须引用对应 project_papers |
| evidence | 文件版本 FK、线索文献 FK、页码/quote/anchor | created_by、tags JSONB 数组；原始来源字段不可普通 PATCH；version 控制解释/标签修改 |
| hypotheses | 同空间/课题/线索 FK | version、current_revision；状态人工设置 |
| hypothesis_evidence_links | 同线索双复合 FK、关系枚举 | version、updated_at；新增/修改/移除关系生成假设修订 |
| research_decisions | 同线索 FK、current_revision | 延迟复合 FK 指向真实修订；revision 作为并发版本 |
| decision_revisions | (decision_id,revision_no) UNIQUE | title_snapshot/type_snapshot 在初始迁移内；固定所有可变依据 |
| decision_revision_evidence_links | 修订和证据同线索；原文/解释快照 | evidence_version、paper_file_id/page/source_anchor 快照；引用 ID 与快照同时保留 |
| tasks | 同课题/线索/决策 FK；done 与 completed_at 一致 | version、source_revision_no；绑定任务创建时的确切决策版本 |
| notes | JSONB content、search_text、version、deleted_at | last_saved_at；成功事务内更新派生纯文本 |
| project_notes | (workspace,project,note) PK | 复用而不复制正文 |
| thread_notes | 引用 thread 和 project_notes | 关联在事务内先补课题关系 |
| note_papers | 同空间双 FK | 引用更新时与正文事务一致 |
| note_evidence_links | 同空间双 FK | 引用可跨线索，但有明确课题/线索标签 |
| activity_events | 追加事件、actor、target、payload | event_schema_version；最小历史快照；无论文全文/笔记正文 |
| processing_jobs | 文件 FK、活跃任务部分唯一 | lease_owner/expires_at、attempt_token、heartbeat_at、parser_version、next_attempt_at |
| export_jobs | space、requester、status、expiry | snapshot_at/schema_version、lease/attempt、manifest_hash、progress；清理前保留引用 |

新增 version 字段采用正整数非空。时间更新选用统一数据库触发器，ORM 使用 server_onupdate/FetchedValue 显式取回；版本递增使用一种确定策略，不能同时交给应用和触发器各加一次。

## P0 新增 10 张工程支撑表

初始设计基线为 **25 张原业务表 + 10 张新增表 = 35 张**，另有 Alembic 元数据。新增表均为本次建议，不是四份文件已存在的代码。开发期 `0008` 再增加下述运维检查点表，当前实现为 36 张，不改变原业务范围。

| 新表 | 最小字段与关键约束 | 用途 |
| --- | --- | --- |
| auth_sessions | id/user_id/token_hash UNIQUE/created_at/expires_at/revoked_at/last_seen_at | 可撤销的不透明会话；只保存随机令牌摘要 |
| auth_tokens | id/purpose/user_id 可空/email/token_hash UNIQUE/expires_at/used_at | 一次性邀请、邮箱验证、密码重置；用途隔离、过期与单次消费 |
| upload_sessions | id/workspace/paper/file/staging_key UNIQUE/status/expires_at/expected_size/expected_sha256/lease_token | 跟踪临时上传、验证、最终固定、过期和重复完成 |
| api_idempotency_keys | workspace/actor/operation/key UNIQUE/request_hash/status/response_status/response_body/expires_at | 保证相同业务请求重试返回原结果；响应不存密码、令牌或签名 URL |
| outbox_events | id/workspace/event_type/aggregate_id/payload/created_at/dispatched_at/attempts/next_attempt_at | DB 提交后可靠派发；payload 仅含 job ID 等最小参数 |
| thread_revisions | id/workspace/project/thread/revision_no/title/question/description/status/created_by/created_at | 研究问题表述与状态历史，(thread_id,revision_no) 唯一 |
| hypothesis_revisions | id/workspace/project/thread/hypothesis/revision_no/statement/status/evidence_links_snapshot/created_by/created_at | 保留判断及支持/反面关系；JSON 快照格式固定并由服务端校验 |
| decision_revision_hypothesis_links | workspace/project/thread/revision/hypothesis/statement_snapshot/status_snapshot/hypothesis_revision_no | 与当时假设版本关联；同线索复合 FK；快照不可变 |
| decision_revision_note_links | workspace/project/thread/revision/note/note_version/content_snapshot | 保留同空间笔记依据；不随笔记后续编辑变化 |
| deletion_jobs | id/workspace/requested_by/status/scope/requested_at/lease/attempt/online_finished_at/backup_expiry_at/error_code | 业务删除意图与匿名回执；独立日志确认后才可物理清理 |

auth_tokens 不记录明文令牌；注册邀请码若绑定邮箱，其使用必须与注册身份一致。表中客户端键和值长度设限，避免幂等账本被滥用。删除完成后，deletion_jobs 去除个人 FK/标识，只保留匿名操作结果和保留期；不能为了保留清理账本永久留存用户。

独立删除权威另存于单独 PostgreSQL 数据库，使用独立 Alembic 配置 `backend/ledger-alembic.ini`：`ledger_entries`（只追加签名链）、`ledger_heads`（受保护当前头部）、`ledger_activation`（独立 owner 审阅的初始清单和恢复时间下限），以及自己的 Alembic 元数据。它们不计入上述 36 张业务/支撑 ORM 表，也不进入业务 pg_dump/用户资料导出。运行 writer 只可追加 entries；reader 只读；二者不能激活清单、改删数据或禁用触发器。业务迁移/应用/清理/备份角色没有该数据库的 CONNECT 权限。详见 [独立日志运行说明](deletion-journal-runbook.md)。

### 开发期新增运维表（0008）

`maintenance_checkpoints` 保存后台清理的空间轮转位置和对象/临时文件分页位置。
字段为 `name` 主键、可空的 `workspace_id`、JSONB `state`、`updated_at`；JSON 必须是对象。
仅清理角色可以读取/写入，应用角色无表权限，不进入用户资料档案或删除影响计数。
空间级检查点及全局轮转检查点均通过 FK 绑定对应空间，删除空间时 CASCADE 删除，避免全局游标留下已删除的原始空间标识。
隔离恢复完成后清空检查点，不能把源桶分页位置用于恢复桶。此表属于运维支撑，不增加产品用户流程。

## 不可变历史与来源约束

创建证据后，paper_id、paper_file_id、quote_text、页码和 source_anchor 为原始出处；普通修改只允许 interpretation、用户标签等解释字段。来源需更正时创建新证据，事件注明替代的旧 ID，旧证据继续为原决策提供出处。定位重新验证由受控服务更新 anchor_status，不改原文。

PDF 新版本上线时旧 evidence.paper_file_id 不变。旧文件可取且校验通过，证据仍可以 located；界面提示“引用历史版本”。文件丢失、不可用或定位失败时显示 unresolved/page_only；不能偷偷跳转到当前文件。

决策修订写入时保存 title/type/reason/content、证据的原文和解释、假设内容及判断、引用笔记正文/版本。revision 与三个依据快照关系表不可 UPDATE/DELETE；应用角色仅 SELECT/INSERT，受控清理角色另行管理。activity_events 同样追加写入。数据库角色规则需要在实际集成测试中验证。

为 decision_revisions 添加非延迟唯一键 `(workspace_id,project_id,thread_id,decision_id,revision_no)`；research_decisions 的 `(workspace_id,project_id,thread_id,id,current_revision)` 建立 `DEFERRABLE INITIALLY DEFERRED` FK 指向它。在同一事务先创建主对象、再插 revision，提交时保证指针合法；向前版本只能由修订服务更新。thread/hypothesis 的 current_revision 采用同样指针策略。

tasks.source_revision_no 绑定上述修订键。CHECK 要求 `decision_id IS NULL` 与 `source_revision_no IS NULL` 同时成立；一旦有 decision_id，thread_id 必须非空。数据库默认复合 FK 对 NULL 的处理可能跳过匹配，所以可选关联必须加上述 CHECK，不能把可空列外键当作完整规则。[PostgreSQL 16 约束文档](https://www.postgresql.org/docs/16/ddl-constraints.html)

## SQLAlchemy 工程约定

采用 `DeclarativeBase`、`Mapped[T]`、`mapped_column`，用统一 metadata naming_convention。关联表有 relation/explanation/snapshot 等业务字段时使用显式 Association Object；不能同时让裸 secondary 和显式对象各自写入同一关系。

复合 FK 用 `ForeignKeyConstraint([...],[...])`，其列顺序与目标唯一键一致。多条关系共享 workspace/project/thread 列时明示 foreign_keys/primaryjoin；不要用 overlaps 掩盖错误写入规则。关系加载用 selectinload 或明确 DTO 查询，核心路径设置 lazy='raise' 检测隐式加载；避免线索详情一条证据触发多次查询。

每个请求/并发任务独立 AsyncSession；不跨 asyncio.gather 共享。Worker 为每个 job 创建独立 session，禁止复用 Web 进程的连接池。[SQLAlchemy 2.0 异步会话文档](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)

笔记、解释和普通业务对象使用 expected_version + 原子条件更新；同一事务写活动及幂等结果。若使用 ORM `version_id_col`，必须通过 flush 路径；直接批量 UPDATE 不会自动得到同等版本保护。两种路径只能选择一种统一实现，不能混用而遗漏条件。[SQLAlchemy 版本计数器](https://docs.sqlalchemy.org/en/20/orm/versioning.html)

下面是设计级笔记更新 SQL，与服务层行为对应，不是已运行代码：

```sql
UPDATE notes
SET content = :content,
    search_text = :trusted_plain_text,
    version = version + 1,
    last_saved_at = now()
WHERE id = :id AND workspace_id = :workspace_id
  AND deleted_at IS NULL AND version = :expected_version
RETURNING id, version, updated_at, last_saved_at;
```

返回零行后，在同一授权范围区分不存在与版本冲突；返回 404 或 409，不暴露其他空间对象。JSONB 修改统一替换验证后的整体文档，或者采用经过测试的深层变更跟踪；不能依赖普通 dict 嵌套赋值自动被 ORM 检测。

默认数据库隔离 READ COMMITTED。需要序列化的操作加行锁：切换默认课题锁 Workspace、切换文件版本锁 Paper、修订决策锁 Decision。锁定后再对 expected_revision 检查；写入修订/快照/指针/事件/幂等结果同事务。不要在数据库锁内执行大文件传输或远程 API 调用。

## 迁移顺序与索引

保留 S3 M001–M012 的领域顺序：身份空间 → 课题线索 → 文献文件 → 关联 → 证据 → 假设 → 决策 → 任务 → 笔记 → 活动与 job → 搜索索引 → 审计触发器。新增认证表置于 M001，上传置于 M003，线索修订置于 M002，假设修订置于 M006，依据关联置于笔记建表后的迁移，幂等/outbox/deletion 置于 M010；循环指针 FK 在相关双方建表后补充。

因为尚无已运行数据库，直接在初始 revision 定义 title/type 快照，避免先加空默认值再打补丁。生产有历史数据时按“扩展可空字段 → 有来源回填 → 验证 → 收紧约束”处理。无法重建的历史内容标记来源为回填/缺失，不能把当前标题当作确切历史事实。

只允许一个 Alembic head；autogenerate 结果要人工审查部分索引、函数、trigger、CHECK 和权限。空库 upgrade、已有数据 upgrade、ORM/DDL drift、关键约束和恢复路径必须通过；不能以 `create_all()` 代替生产迁移。

索引首列优先 workspace_id，再按实际过滤列和排序列设计。保留当前文件/默认课题/活跃解析任务的部分唯一索引。列表采用 created_at/id 或 updated_at/id 稳定游标。关键词用 PostgreSQL ILIKE + 可选 pg_trgm；中文短词与英文缩写单独压测，不宣称完整中文语义搜索。对每条核心查询用真实规模 EXPLAIN 验证；不重复创建 PK/UNIQUE 已拥有的索引。

## 数据库必须验证的补充场景

原有 DB-01–DB-12 继续保留，新增：当前版本指向不存在的修订应拒绝；任务 decision_id 非空但 source_revision_no 为空应拒绝；应用角色不能覆写历史；同幂等键不同请求应拒绝；旧 Worker 不能用失效 attempt_token 提交；修订后快照与历史文件一致。测试必须在 PostgreSQL 上执行，SQLite 无法替代这些数据库语义。
