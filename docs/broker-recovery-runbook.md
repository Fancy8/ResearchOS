# 队列未确认消息恢复与故障演练

本轮增加独立恢复扫描，补齐本地完整 Celery solo Worker 强制终止、Redis 未确认
消息重投递、业务租约/重复发布及真实临时残留清理的组合验证。生产平台和容量验收
仍未完成；Windows 不属于 Celery 官方支持的生产平台。

## 为什么增加独立扫描

固定依赖为 Celery 5.6.3 / Kombu 5.6.2。首次真实接管测试中，原 Worker 已被强制
终止，解析子进程退出，Redis 的 unacked/index 仍保留；接管 Worker 在 15 秒观察
窗口内没有恢复该消息。观察探针未记录到 QoS.restore_visible 调用，线程栈在同步
消费循环的 poll 路径。检查该版本代码可见：BRPOP 返回空时抛出 Empty，绕过
MultiChannelPoller.get 后面的 maybe_restore_messages。这里的结论限定于本次本地
同步路径，不推断所有平台和池都发生同样故障。

保留的失败报告为 `artifacts/broker-recovery-revised.xml`、
`broker-recovery-observation.xml`、`broker-recovery-diagnostic.xml`。最初另有注册邮件
导致消息数断言错误、测试前缀长度检查错误，保留于 `broker-recovery-initial.xml`；
两条精确测试命名空间已清理，记录在 `broker-initial-cleanup.json`。未使用 FLUSHDB。

依据：[Celery Redis visibility timeout](https://docs.celeryq.dev/en/v5.6.3/getting-started/backends-and-brokers/redis.html#visibility-timeout)、
[固定 Kombu 5.6.2 Redis 实现](https://github.com/celery/kombu/blob/v5.6.2/kombu/transport/redis.py)。
代码和本地源文件摘要记录在 `artifacts/broker-kombu-baseline.json`。上游 main 的新配置
不等于已安装稳定版，不能把 main 文档中的选项直接当成本地已生效。

## 当前运行机制

`app.workers.dispatcher.BrokerRecoverySchedule` 在现有独立 dispatcher 进程中启动，
默认每 10 秒尝试一次扫描，每次至多处理 100 个已过 visibility timeout 的投递。
使用与本应用相同的 broker URL、transport options、keyprefix 及 visibility timeout
（当前普通配置为 300 秒），连接与 socket 默认超时 5 秒。不消费业务任务，也不
创建替代消息 ID；复用固定 Kombu 的互斥锁、WATCH/MULTI 与原路由恢复。

扫描失败不会推进本进程的下次成功时间，dispatcher 循环会再尝试。扫描、数据库
租约/outbox 派发和到期清理调度分别捕获异常；一个失败不能跳过其他两个。日志
仅写 `dispatcher_broker_recovery_failed`、`dispatcher_outbox_failed` 或
`dispatcher_expiry_schedule_failed`，不打印异常值、连接 URL、密码或任务正文。

Redis 未确认索引在同一 DB/keyprefix 内共享。不同应用、环境或不同恢复策略必须
使用独立 broker DB/keyprefix 或独立实例；不能把这个扫描器接到含未知应用的共享
命名空间。所有扫描/消费进程必须使用一致的 visibility timeout，否则可能过早
重投递。当前本地服务使用项目内专用 Redis 进程/数据目录和 56379 端口；演练
使用随机 `researchos-crash-test-<uuid>:` 前缀，清理仅限该前缀。

Broker ACK 不代表业务已成功：任务结果以 PostgreSQL job 状态和 attempt_token 为准。
如果恢复的消息遇到尚有效的业务租约，该次消费会跳过并 ACK；租约后来到期，实际
dispatcher 将 job 重新排队并创建 outbox。新行的数据库时间可能晚于本次捕获的
调度时间，下一次循环才发送是合法行为。不能依赖一次函数调用即完成所有步骤。

## 只读诊断

从项目根目录执行：

```powershell
.\runtime\venv\Scripts\python.exe tools/broker_status.py
```

命令只读取默认队列各优先级待消费数量、unacked/index 数量、最老消息年龄、已过
visibility timeout 的数量和恢复互斥锁 TTL；不展示消息正文、连接参数或 delivery tag。
读取成功退出 0，不代表 Worker/业务整体健康；配置或连接失败只返回
`BROKER_STATUS_UNAVAILABLE` 并退出 2。`tools/verify.ps1` 已接入此检查。

统一回归曾发现首版诊断中 ZCARD/ZRANGE/ZCOUNT/TTL 没有被 Kombu 5.6.2 的前缀包装器
处理，隔离空间的真实一条索引被误读为零。已经改为共享该 broker 的连接池，用
原生 Redis 只读管道给所有键显式添加同一物理前缀，避免部分命令漏加或重复加前缀。
补充检查队列、hash/index、消息年龄、锁 TTL 和旁侧命名空间均保持不变；独立探针
结果在 `artifacts/broker-metadata-prefix-proof.json`。读取成功不再被误当作“所有计数
正确”的证据，最终组合用例还会在真实强杀后核对这些值。
首轮统一回归保留为 `artifacts/backend-broker-metadata-prefix-failed.xml`
（155 项通过、两条计数断言失败，393.45 秒），不与修正后的结果混用。

持续过期未确认数量、最老年龄、dispatcher 的三类固定错误和进程存活应共同监控。
TTL=-2 表示当前无锁，-1 表示存在无过期时间的锁，需要定位来源；不要自行删除
未知锁。重启恢复进程不会缩短其他所有者仍有效的锁 TTL。当前尚未认证报警阈值、
高负载下扫描公平性、Redis 故障/丢失恢复和生产 RTO。

## 本轮验证范围

先前的 12 项进程测试加本轮三个组合/故障用例，共 **15 项通过（59.38 秒）**。
报告 `artifacts/broker-and-process-composed.xml`。随后补充只读计数断言和 CLI 配置/
连接失败脱敏用例，最终统一验证结果见 implementation-status.md。

最终统一应用回归为 **158 项后端通过（404.03 秒）**、**9 条浏览器流程通过（约一
分钟）**。之后旧的真实到期清理队列测试迁入同样的独立 keyprefix/创建时进程监督，
并等待实际 ACK 后再退出，避免只删队列却留下共享 unacked；该调整及新 pip 下的
两个 CLI 用例另行 **3 项通过（16.67 秒）**。运行中只读盘点曾发现旧维护测试的
历史 unacked，类别摘要在 `broker-historical-inventory.json`；本轮没有任意清空或
删除未知历史消息，历史合成队列的完整盘点/定向清理仍需后续处理。

两条完整队列演练都使用真实独立进程、真实 Redis 消息和实际 pypdf/数据库/对象
存储；原任务由真实 outbox 派发。强制终止完整 Worker，确认子进程退出且未确认
记录保留；启动新 Worker 和独立恢复扫描进程，检查原 Celery ID 和 redelivered 标记。
分别覆盖“业务租约已过期”和“重投递时租约仍有效、稍后由 dispatcher 回收”。随后
通过真实 broker 再发送相同消息 ID，验证总共两次业务尝试、一次页集合/导入活动
发布、新 attempt token 及原始文件 SHA-256 一致。

实际被杀遗留的临时 PDF 被调旧 mtime：活跃任务期间保留，成功后由真实维护任务
清理，新鲜临时文件继续保留；原对象哈希不变。用例只在测试库推进该条业务租约
的到期时间；Redis visibility timeout 为 5 秒，扫描间隔为 0.5 秒。因此这些结果
证明恢复机制，**不证明普通 300/180 秒配置的恢复时长，也不证明生产 RPO/RTO**。
两份机制摘要为 `artifacts/broker-recovery-True.json` 与 `broker-recovery-False.json`。

仍需在受支持生产平台上验证进程监督、完整守护进程/连接重启、Redis 高可用/持久性、
恢复扫描互斥持有者强杀、队列积压和容量、公平性、监控和值班。PDF 的一次事务发布
结论不能推广为 SMTP 等外部副作用恰好一次。Kombu 恢复与元数据接口依赖固定实现，
升级依赖必须重跑此组测试；没有修改 site-packages 或直接采用未发布上游代码。
