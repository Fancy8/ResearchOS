# 本地进程监督与中断验证

本轮覆盖 Windows 开发/验证环境的 PDF 解析和 PostgreSQL 转储、恢复工具。
统一入口为 `backend/app/core/processes.py`。该入口在 CreateProcess 创建时绑定
Windows Job，避免创建子进程后再分配 Job 的间隙。Job 句柄禁止继承；父进程失去
最后一个句柄时终止该 Job 的进程树。正常主进程退出也关闭 Job，清理残留后代。

## 已实现边界

| 项目 | 当前行为 |
| --- | --- |
| 可执行文件、工作目录、临时目录 | 必须位于项目根目录内；不经过 shell |
| 标准句柄 | 显式继承 stdin 的空设备、stdout、stderr；不继承 Job 句柄 |
| 环境 | 使用基本系统变量白名单；PDF 不继承数据库、存储、邮件或日志凭据；PG 工具仅增加自己的 PG 连接变量 |
| PDF | 120 秒；单进程及整个 Job 512 MiB；stdout、stderr 各最多 32 MiB |
| pg_dump、pg_restore | 默认 600 秒；单进程及整个 Job 512 MiB；stdout、stderr 各最多 256 KiB；不向异常复制工具输出 |
| 进程数 | 每个 Job 最多 8 个进程，包含虚拟环境启动器与后代 |
| 平台 | 当前只验证 Windows；其他平台拒绝启动这些受监督工具，不能直接宣称支持 Linux 部署 |

stdout/stderr 分别并发排空并限制存储；超限、超时、启动失败及内部观察回调失败
均执行 Job/句柄清理。内部 `on_started` 回调只供生命周期测试使用；正常业务不传入
回调。测试用启动屏障不计入业务执行超时，不能作为用户可调用接口开放。

Job 是进程生命周期和资源控制，不能代替低权限账户、OS 文件/网络隔离或 CPU 配额。
PDF 现有 Python audit hook 仍只是一层限制，不构成完整恶意文件执行沙箱。
生产 OS 沙箱、CPU 限制、原生扩展行为、Linux 等价监督与干净主机仍须验证。
PG 环境白名单可能排除外部部署所需的证书/服务配置；本地回环连接通过，外部 TLS
连接应通过明确的受控配置实现并验证，不能直接假定兼容。

当前安装 Celery 5.6.3 / Kombu 5.6.2。Celery 官方 [Windows 支持说明](https://docs.celeryq.dev/en/v5.6.3/faq.html#does-celery-support-windows)
明确不再支持 Windows，因此本地 solo Worker 的通过结果不能作为 Windows 生产支持
承诺。生产部署需完成受支持平台上的等价进程监督、Worker/队列故障与干净环境验证；
目前 Windows 本地运行和其他平台拒绝运行的组合并未关闭该发布门槛。

## 实际测试及解释

`backend/tests/test_processes.py` 的 12 项测试于 2026-10-15 通过（28.83 秒），
报告 `artifacts/process-containment-final.xml`：

- Unicode/空格/引号参数、双输出流和凭据不继承；两类输出超限不回显内容。
- 真正运行的超时子进程、观察器异常、内存分配失败，以及正常主进程退出后仍存活的后代。
- 强制终止真实 Python 所有者，检查其子进程及孙进程退出。外层测试 Job 在断言期间
  保持打开，避免外层清理掩盖被测内层 Job 的缺陷。
- 真正 pg_dump 连接测试库后，在输出管道阻塞时终止所有者；检查工具退出及数据库
  连接消失。这验证的是该中断点，不是电源故障或所有转储阶段。
- 真正备份调度进程生成转储、仍持有快照/保留锁时被强制终止。检查锁释放、签名目录
  保持 running、未发布成功包。真实调度重启标记 BACKUP_INTERRUPTED、清理其已登记
  工作目录，按退避重试，随后成功恢复到独立数据库/桶并核对原始文件哈希。
- 真正 PDF 任务进程取得业务租约、启动实际 pypdf 解析子进程后被终止。检查解析子进程
  退出、无半成品页发布；推进测试库中该条租约到期时间，调用真实 dispatcher，随后
  在新进程执行相同任务。验证新 attempt token、恰好一组页/导入活动和原件哈希；
  重复任务调用不再发布。测试中 broker send_task 用记录器捕获，**尚不证明 Celery
  守护进程被杀后的 Redis 未确认消息可见性恢复**。后续完整本地组合验证见
  broker-recovery-runbook.md；生产平台恢复仍是独立发布门槛。
- 在无应用后台连接线程的独立探针中，40 次启动失败前后检查原生进程句柄计数。

父进程被强制终止不能执行 Python finally，因此备份转储/PDF 临时文件可能保留。
备份重启清理已在上述测试中实测；PDF 用例只清理精确已知测试残留，未把它计为
自动维护验证。普通维护的年龄宽限及活跃任务保护保持原规则。完整临时文件中断
与维护组合、全守护进程/队列重投递已由后续本地组合演练补充，详见
broker-recovery-runbook.md；受支持生产平台、大容量和 RPO/RTO 仍待演练。

首次 `process-containment-initial.xml` 中测试设施事后分配 Job 被 Windows 拒绝，且
pywin32 无所用句柄计数 API；后续改为创建时绑定的外层测试 Job、原生计数 API。
`process-containment-crash-retry.xml` 还保留句柄计数受共享测试进程后台活动影响、复用
旧探针 marker 导致读到已退出 PID 的失败。已改为独立句柄探针和每次启动清理屏障
marker，未将这些失败报告覆盖为成功。最终统一回归结果见 implementation-status.md。

补充并发探针以 8 路并发运行 24 个独立子进程，分别核对 stdout/stderr 精确字节、
无交叉混流，0.375 秒通过；报告 `artifacts/process-concurrency-proof.json`。这是启动和
输出隔离的机制检查，不能当作业务吞吐量或生产容量结论。

实现依据为微软 [Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)
及 [UpdateProcThreadAttribute](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute)
中的 JOB_LIST / HANDLE_LIST；本地 pywin32 未直接提供启动属性，因此使用 ctypes 调用
公开 Win32 API，并继续使用已有 pywin32 包配置 Job 限制。
