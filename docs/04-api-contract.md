# API 与业务协议

状态：设计协议与实现约束。当前运行接口以 `contracts/openapi.json` 和生成的 TypeScript 契约为准；实施证据与未完成项见 `implementation-status.md`。下方保留设计阶段接口目录，实际方法名的差异以生成契约为准。

## 通用协议

统一前缀 `/api/v1`，路径 UUID，时间 UTC ISO 8601，日期 `YYYY-MM-DD`。成功返回 `{data, meta?}`；错误返回 `{error:{code,message,details?},request_id}`。服务端忽略或拒绝外部 workspace_id/actor_user_id，从会话上下文获取归属；为写入 schema 设置额外字段拒绝，防止批量属性注入。

列表统一 `limit=20`（最大 100）和不透明 cursor；返回 next_cursor/has_more，默认不提供昂贵的全量 count。游标编码排序字段+UUID，带查询条件指纹并校验；空间过滤在排序/分页前执行。切换查询条件重新分页。用户私有响应 `Cache-Control: no-store`。

2026-10-14 分页实现补充：

- 课题、线索、文献、证据、假设、决策、任务、笔记、活动、导出、课题/线索文献关联、课题笔记关联，以及历史修订/文件版本列表均返回 `{data:[], meta:{has_more,next_cursor}}`。普通实体按 `created_at DESC,id DESC`；历史按 `revision_no DESC,id DESC`，文件按 `version_no DESC,id DESC`。关联内嵌快照仍随所属详情返回，不作为独立列表分页。
- `GET /papers?q=...` 在服务端按标题做不区分大小写的字面包含检索，去除首尾空白，最多 100 字符；`%`、`_`、反斜杠不作为通配符。游标绑定规范化查询、空间、资源、父对象和排序方式；不能跨查询或父对象使用。非法游标返回 `422 INVALID_CURSOR`。分页不承诺跨请求数据库快照，新写入的前排记录在刷新后显示。
- `GET /projects/current` 独立返回当前空间未归档的默认课题；不存在默认时选最新未归档课题，没有可用课题时为 `null`。不依赖课题第一页；列表与此端点均需认证。
- Alpha 契约调整：`GET /notes/{id}/links?kind=project|thread|paper|evidence` 要求单个 `kind`，分页返回 `{id,title,thread_id}`，替代原先无界的分组对象；缺 `kind` 返回 422。前端已同步迁移，已删除笔记不暴露关联。
- `GET /papers/duplicates?sha256=...` 分页返回确切 `paper_file_id/version_no`，仅匹配已上传且仍可用的原件。复用跳转固定到该历史文件，不切换成当前版本。文献摘要公开 `availability_status`，通过一次批量查询取得一页文献的文件摘要。
- 前端每次取 20 条，显示已加载数量；列表、历史和关联选择器提供继续加载及重试。后页/后台刷新失败保留已经取得的记录；改变查询条件使用新的缓存键。表单内分页和重试按钮不会提交表单，多选项翻页后保留现有勾选。

成功响应契约已进一步补齐：认证、引导草稿/完成、聚合/搜索、上传/解析、关联维护、删除预览/凭据回执均有明确 DTO；后端执行响应校验与字段过滤。`/me` 与引导状态保留未出现字段，避免把空草稿自动变成完整状态。前端身份、活动、桌面、引导状态直接采用生成类型。

2026-10-15 任务筛选补充：`GET /tasks` 增加可组合的 `status=todo|doing|done|blocked`、`priority=low|medium|high`、`due_from` / `due_to`（含端点的截止日期范围），与原课题/线索/空间条件在 SQL 分页前应用。任一日期界限存在时，无截止日期任务不匹配；逆序范围或非法值返回 `422 VALIDATION_ERROR`。游标绑定全部筛选，换条件返回 `422 INVALID_CURSOR`，旧版任务游标应从第一页刷新。行为与失败恢复证据见 [task-state-acceptance.md](task-state-acceptance.md)。
PDF/ZIP 的成功响应声明为 `application/pdf`/`application/zip` 二进制；错误仍使用 JSON ErrorEnvelope。框架层未知路径/方法的 404/405 也统一错误外壳，并保留 `Allow` 头；413/415 加入公开错误契约。

2026-10-16 上传恢复补充：初始化和完成分别使用固定正文/幂等键；完成请求只确认后台任务接收，Worker 验证后才发布原件。完成重放保留原 job_id；不同完成键也不隐式重试失败解析、不重置处理中状态。已确认上传但缺失任务记录返回 `409 STATE_CONFLICT`，显式解析重试仍使用独立入口。客户端持久恢复和过期/并发边界见 [上传恢复验收](upload-recovery-acceptance.md)，本次无 DTO 或迁移变化。
`backend/tests/test_response_contracts.py` 遍历全部成功响应并递归检查其公开结构，拒绝空响应 schema 及存储键、租约、凭据哈希等内部字段；完整运行结果见实施状态，不据 schema 数量推断安全审计完成。

| HTTP | 机器码示例 | 前端处理 |
| --- | --- | --- |
| 200/201 | — | 展示服务器返回实体与版本 |
| 202 | — | 展示 job_id 与明确后台状态 |
| 400/422 | INVALID_REQUEST/VALIDATION_ERROR | 字段反馈，保留输入 |
| 401 | AUTH_REQUIRED | 登录后可恢复非敏感未提交输入 |
| 403 | OPERATION_FORBIDDEN | 已知合法上下文中的操作被禁用 |
| 404 | RESOURCE_NOT_FOUND | 不存在或不属于当前空间，统一回应 |
| 409 | VERSION_CONFLICT/STATE_CONFLICT/IDEMPOTENCY_CONFLICT/DEPENDENCY_EXISTS | 展示差异或阻塞依赖，不自动覆盖 |
| 413/415 | FILE_TOO_LARGE/UNSUPPORTED_FILE | 上传限制和格式提示 |
| 429 | RATE_LIMITED | 按 Retry-After 重试，禁止无限循环 |
| 500/503 | INTERNAL_ERROR/SERVICE_UNAVAILABLE | 显示 request_id，允许安全重试 |

笔记 PUT、解释 PATCH、状态更新等可变对象必须带 expected_version；决策追加必须带 expected_revision。缺少版本返回 422；过期返回 409 和 current_version。所有普通重试不能伪造新的幂等键来重复提交。

## 接口目录

下表补齐原文只有列表接口但缺少详情/关系维护/删除的路径。关联写入均验证对应复合归属和依赖。

| 模块 | 方法与路径（均带统一前缀） | 输入/输出要点 |
| --- | --- | --- |
| 认证 | POST /auth/register、/auth/login、/auth/logout | 邀请/邮箱/密码；注册原子创建用户、空间、画像；登录发会话 Cookie；logout 撤销 |
| 账号 | GET /me；POST /auth/password-reset-requests、/auth/password-resets、/auth/email-verifications | 请求找回统一回复防枚举；一次性令牌；重置后撤销旧会话 |
| 引导 | GET /onboarding；PUT /onboarding | 已完成步骤、首课题/线索；可恢复；最终提交幂等 |
| 画像 | GET/PATCH /research-profile | version、布局、阅读偏好、个性化开关 |
| 课题 | GET/POST /projects；GET/PATCH /projects/{id}；POST /projects/{id}/set-default | title、stage、status、version；默认切换锁空间 |
| 线索 | GET/POST /projects/{id}/threads；GET/PATCH /threads/{id}；GET /threads/{id}/revisions | 问题与状态；版本；历史；详情各分区有单独分页 |
| 文献 | GET/POST /papers；GET/PATCH /papers/{id} | 元数据和阅读状态；POST 为仅元数据建档，可后续上传 |
| 上传 | POST /papers/upload-init；POST /papers/{id}/upload-complete；GET /uploads/{id} | upload_id/paper_id/file_id、临时上传参数；完成请求接收后台验证与解析，由 Worker 固定和发布原件 |
| 文件 | GET /papers/{id}/files；GET /papers/{id}/file?file_id=...；POST /papers/{id}/files/{file_id}/set-current | 历史版本；授权阅读；设置 current 不重绑证据 |
| 解析 | GET /papers/{id}/parse-status?file_id=...；POST /papers/{id}/files/{file_id}/parse-retries；GET /papers/{id}/files/{file_id}/pages/{page} | 确切文件版本；状态/错误码；页文本和定位数据 |
| 文献关联 | GET/POST /projects/{id}/paper-links；DELETE /projects/{id}/paper-links/{paper_id}；POST/DELETE /threads/{id}/paper-links[/{paper_id}] | 依赖阻塞时 409；先建立课题级关系 |
| 证据 | GET/POST /threads/{id}/evidence；GET/PATCH /evidence/{id}；POST /evidence/{id}/reuse | 文件版本+来源；PATCH 仅解释；reuse 目标线索并形成新 ID |
| 假设 | GET/POST /threads/{id}/hypotheses；GET/PATCH /hypotheses/{id}；GET /hypotheses/{id}/revisions | statement/status/version；判断由用户设置 |
| 假设证据关系 | POST /hypotheses/{id}/evidence-links；PATCH/DELETE /hypotheses/{id}/evidence-links/{evidence_id} | relation/explanation；修改和移除也需 expected_version，生成假设修订 |
| 决策 | GET/POST /threads/{id}/decisions；GET /decisions/{id}；GET/POST /decisions/{id}/revisions；GET /decisions/{id}/revisions/{revision_no} | revision、依据 ID；服务端创建快照；不提供覆盖 revision 的 PUT |
| 任务 | GET/POST /tasks；GET/PATCH /tasks/{id}；POST /decisions/{id}/revisions/{revision_no}/tasks | status/date/version；从确切决策修订创建；完成/重开同事务写事件 |
| 笔记 | GET/POST /notes；GET/PUT/DELETE /notes/{id}；POST /notes/{id}/restore | content JSON/version；软删除与恢复；search_text 服务端派生 |
| 笔记关联 | POST/DELETE /notes/{id}/project-links[/{project_id}]、/thread-links[/{thread_id}]、/paper-links[/{paper_id}]、/evidence-links[/{evidence_id}] | 显式关系，不在富文本里伪造权限；正文引用和关系可以同事务保存 |
| 聚合 | GET /dashboard?project_id=...；GET /activity；GET /search?q=...&types=... | 课题上下文、权限分页、真实活动；搜索范围不包含全文 PDF（P0） |
| 导出 | POST /exports；GET /exports/{id}；GET /exports/{id}/download | include_files、job/status、快照时点、过期与授权下载 |
| 删除 | POST /deletion-previews；POST /deletions；GET /deletions/{id} | scope、对象 ID、依赖清单、预览令牌、再次验证身份、清理进度 |

`[/{id}]` 只是上表的路径简写：POST 使用集合路径，DELETE 使用具名对象路径；OpenAPI 中必须逐个展开。GET 文件接口不接受任意 storage_key。删除预览不修改数据；执行接口重新检查依赖，不能依赖过时预览放行。

## 会话与防伪造

采用高熵不透明会话令牌，摘要存 PostgreSQL，浏览器持有 `__Host-session` Cookie（Secure、HttpOnly、SameSite=Lax、Path=/、无 Domain）。写接口验证 Origin 与 CSRF token；严格同源 CORS。登录/密码重置轮换会话、退出即时撤销、空闲和绝对期限可配置。建议初值为 12 小时空闲/7 日绝对期限，由安全评审确认。[OWASP 会话管理](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)

密码使用成熟 Argon2id 实现，参数按服务硬件标定并保留升级机制，不自行编写哈希算法。[OWASP 密码存储](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)

## 幂等与版本协议

创建证据、决策、从决策建任务、上传初始化/完成、导出及最终引导提交使用 `Idempotency-Key`。键按空间+用户+操作作用域唯一；同键同规范化请求返回原 data/status；同键不同请求返回 409。保留期建议至少 24 小时，上传/job 的自然资源唯一性持续有效。

2026-10-16：POST /projects、/projects/{id}/threads、/notes 增加可选 Idempotency-Key，三个前端创建入口始终提供固定键；空间/用户/操作及线索父课题隔离。提供同键同规范化正文时返回原创建回执，后续编辑不改变该回执或回退当前实体。为兼容既有 API，无键仍按原创建语义执行，不能宣称这些调用具有去重保证；已提供但为空/过长的键返回 422 IDEMPOTENCY_KEY_REQUIRED。实现/恢复边界和暂停交接见 [创建恢复交接](research-creation-handoff.md)。

短事务中的幂等记录与业务结果共同提交；并发同键在唯一约束处串行化，不能先返回成功再执行。长上传验证领取 upload lease，同键在处理中返回 202 和稳定 upload_id；最终事务记录稳定 file/job ID，不缓存可能过期的签名 URL。数据库失败整笔回滚；安全重试仍用原键。

2026-10-15 决策页面实现补充：新建/修订均冻结未确认请求的路径、正文、键及 expected_revision，同页窗口关闭/重开不换键；明确拒绝可修正原请求，版本冲突须只读取得服务器版本并经用户明确比较后才形成新提交。成功回执和后续 GET 刷新分开处理。回执是原修订的确认，不能当成当前最新修订。普通幂等记录当前为一天，客户端未确认操作超过 23 小时停止重放；不提供跨页面卸载恢复。来源快照仍以首次成功事务提交时的服务器版本为准；实现/证据边界见 [decision-state-acceptance.md](decision-state-acceptance.md)。

2026-10-15 PDF 证据页面补充：未确认创建同时保留目标线索路径和正文/键，切换阅读文件/页/课题不会重绑来源；成功后明确开始下一条才创建新意图。服务端键为线索作用域，不能把同键跨线索提交当成全局去重。文件读取与创建状态独立；来源只从实际渲染完成的页取得。行为与故障证据见 [evidence-state-acceptance.md](evidence-state-acceptance.md)。

### 创建证据示例

```http
POST /api/v1/threads/{thread_id}/evidence
Idempotency-Key: client-generated-uuid
Content-Type: application/json
```

```json
{
  "paper_id": "8c8a2cdd-66d3-4f8a-ad72-4f1ae936598c",
  "paper_file_id": "d626f240-05fd-4b8c-8a55-20de00682072",
  "quote_text": "A selected passage from the paper.",
  "interpretation": "这段结果只适用于论文报告的实验条件。",
  "tags": ["实验结果"],
  "source": {
    "page_start": 4,
    "page_end": 4,
    "anchor_schema_version": 1,
    "text_quote": {"exact": "A selected passage from the paper.", "prefix": "", "suffix": ""},
    "rects": [{"page": 4, "x": 0.12, "y": 0.22, "width": 0.70, "height": 0.04}],
    "coordinate_space": "unrotated-cropbox-top-left-normalized"
  }
}
```

rect 为未旋转裁剪页面、左上原点、0–1 归一化坐标；每页分别保存，不能把缩放后的浏览器像素直接存成永久定位。服务端检查页数、边界、文本 exact/上下文、文件指纹及解析版本。重复文本或坐标不能确认时只接受 page_only；不存在页面、非法文件关系直接 422/404，不能伪报 located。证据、必要的文献关联、活动事件和幂等结果同事务提交。

### 决策修订示例

```json
{
  "expected_revision": 1,
  "title": "改用方法 B 开展对照",
  "decision_type": "adjust",
  "reason": "新增反面证据提示原方案需要调整。",
  "content": "保留方法 A 为基线。",
  "evidence_ids": ["evidence-uuid"],
  "hypothesis_ids": ["hypothesis-uuid"],
  "note_ids": ["note-uuid"]
}
```

数组中的 ID 是格式示意，正式 schema 全部为 UUID。reason 去空白后必须非空；引用对象逐个授权并锁定/稳定读取后快照。两个请求以 revision=1 提交，只允许一个成功产生 2，另一个 409。前端并列显示远端与本地内容，用户选择合并后使用 revision=2 再提交；禁止自动替用户改写科研判断。

## PDF 上传与不可覆盖协议

1. upload-init 校验额度与 metadata，锁定 Paper 分配 version_no，返回 upload_id、file_id 和仅能写 staging_key 的短期上传参数。新论文可在本操作创建；同键重试复用现有 ID。
2. 浏览器上传临时对象，进度以实际传输为准；供应商支持时使用带 size/content 条件的签名 POST，否则后端限流上传并二次验证。声明为 PDF 不等于内容合法。
3. upload-complete 领取租约，确认对象尺寸、内容签名、格式、页数、恶意内容及实际 SHA-256。ETag 不当作 SHA-256；拒绝加密或损坏文件时给明确错误。
4. 服务端把已验证对象复制到该 file_id 独占的最终键，客户端凭据永远无权写最终前缀。复制后验证最终对象摘要与大小，必要时固定存储 version_id。复制前后临时对象被重放导致内容变化，最终校验失败，不提交引用。
5. 最终数据库事务写 uploaded/current、文件指纹、processing_job、outbox、活动及幂等结果；旧当前文件状态切换在锁内完成。返回 202 和 job_id。上传失败不替换旧 current。
6. 清理临时键；DB 提交失败留下的孤儿最终对象进入延迟核对队列。浏览器关闭不终止已持久化的任务。

S3 签名上传 URL 可重复使用直至过期，向同键上传可替换已有对象，因此“使用唯一 file_id 键”仍需防止签名重放覆盖。本设计的 staging/final 分离是据此推导的防护。[AWS 签名 URL 文档](https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-presigned-url.html)

已验证扫描件可正常阅读，parse ready 同时带 has_text_layer=false；证据使用人工摘录/page_only。全文解析失败不妨碍已验证文件的授权阅读。解析与上传状态分开展示。

## 一致性导出与删除

导出 Worker 在 REPEATABLE READ 只读事务内，将个人业务对象、所有关系、所有修订快照与引用文件清单流式写到受控本地/私有临时包；记录 snapshot_at/schema_version。对象存储固定版本不变，文件打包期间建立保留锁，清理服务不得删除导出所需版本。长快照事务设定上限与监控，超限明确失败，不拼接混合时点数据。[PostgreSQL 隔离说明](https://www.postgresql.org/docs/16/transaction-iso.html)

档案包含 manifest.json、实体 JSON、关系 JSON、笔记 Markdown、原文件，原文件保持文件版本路径。manifest 记录对象数量、每文件 SHA-256/大小、缺失项、schema_version；验证全包后才 succeeded，缺原文件时明确 failed 或经用户选择只导结构数据，不能当完整导出成功。当前下载实现由应用重新授权并流式传输，不在 job 响应暴露 storage_key 或可长期复用的下载地址。

2026-10-16 导出恢复补充：客户端保存原 include_files/键/任务回执，同键重放原任务已完成或失败的创建回执，不隐式新建；任务状态独立读取。新的档案须用户明确开始，先成功核对原任务已终止。include_files=true 遇到被引用不可用原件仍失败；明确选择 false 时保留结构化出处，manifest 的 files 为空，并在 missing_files 中以 referenced_version_unavailable 标记该源。未引用的移除版本沿用 unreferenced_version_removed。已有 schema_version=1 的结构验证器支持此记录档案，本次无 ORM/迁移/DTO 变化。证据和下载生命周期见 [导出恢复验收](export-state-acceptance.md)。

账户删除先验证身份和影响，冻结空间、撤销会话、终止/等待活跃导出，按依赖清理关系/历史/业务表/文件/身份。清理角色与常规角色分离，分步骤幂等重试；备份依批准保留期过期。恢复备份后应用独立删除账本再开放访问，避免已删除资料重新出现。该流程设计不授权本次执行任何真实删除。

2026-10-15 实施补充：删除预览不写日志；授权、密码与预览校验通过后，先确认独立权威日志可读，再提交业务意图/outbox，随后追加独立日志，二者均持久化才返回 202。预检失败返回 `503 DELETION_JOURNAL_UNAVAILABLE`，未接受删除；业务提交后日志故障返回 `503 DELETION_JOURNAL_PENDING`，`error.details` 仅含 `id/receipt/scope`。客户端保留该回执并显示进度，不因错误自动重复创建删除请求；Worker 重试先持久化日志再物理清理。这里不宣称跨数据库原子事务。恢复核对签名全链、当前头部、已审阅清单、备份最低 checkpoint 及历史恢复下限，最终凭据清理和 CONNECT 授权在同一事务提交。
