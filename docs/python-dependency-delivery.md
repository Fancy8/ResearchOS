# Python 依赖交付与审计

当前批准目标为 **Windows x64 / CPython 3.12**。本轮保留原有 104 个应用/开发包的
版本，新增全部具体 wheel 的 SHA-256 固定、来源清单、下载验证与审计入口。
受支持生产平台的独立锁、解释器/服务二进制、完整机器与远程 CI 验证仍待完成。

## 批准清单

| 文件 | 数量 | 用途 |
| --- | --- | --- |
| backend/requirements.lock.txt | 104 | 当前完整应用与开发依赖，全部单一版本/二进制哈希 |
| backend/bootstrap-requirements.lock.txt | 1 | pip 26.2.1 安装引导及其哈希 |
| tools/audit-requirements.lock.txt | 29 | 独立 pip-audit 工具环境的全部包，包含 pip |
| backend/dependency-artifacts.json | 134 个锁条目 / 124 个不同 wheel | 精确文件名、目标平台、大小、SHA-256、官方下载/元数据 URL 与各锁文件摘要 |

全部不同 wheel 合计 **91,421,391 字节**，保存在项目内
`runtime/wheels/cp312-win_amd64`，不提交这些二进制缓存。清单和本地哈希均随代码审阅。
依赖包名按规范归一化；原 104 个版本经与上一提交逐项比较，没有改变。

批准来源为固定版本的 PyPI JSON 和 files.pythonhosted.org。刷新只读取版本锁，
选择当前目标可用的 wheel，拒绝 yanked/不兼容文件和重定向；不会自动升级版本。
已有批准哈希变化或跨锁冲突会失败。所有元数据取回并验证后才写锁与清单；
刷新过程中断造成的清单/锁不同步会被验证拒绝，需要完成刷新并审阅差异。
这不是崩溃原子发布或独立可信签名机制。

```powershell
.\runtime\venv\Scripts\python.exe tools/dependencies.py validate
.\runtime\venv\Scripts\python.exe tools/dependencies.py refresh
```

`refresh` 是显式维护操作，需要查看生成的锁和来源差异；正常 setup、审计和 CI
只消费已批准清单。初次信任仍依赖官方源、代码审查和仓库权限；哈希不能证明包
本身无恶意代码或未报告漏洞。来源与安装模式参考 [pip 安全安装文档](https://pip.pypa.io/en/stable/topics/secure-installs/)。

## 安装

```powershell
.\tools\install-python-dependencies.ps1
# 在另一个项目内环境验证相同安装流程：
.\tools\install-python-dependencies.ps1 -EnvironmentDirectory runtime/dependency-drill-20261015
```

入口先确认环境的最终路径位于项目根目录、平台匹配，再安装哈希固定的 pip。
安装引导之后的新环境尚无 packaging，工具仅在整个 packaging 包不存在时使用
该固定 pip 内置的解析器；其他模块缺失会直接报错。然后验证清单、下载/核对全部
应用 wheel，用 `--no-index --only-binary=:all: --require-hashes` 从项目缓存安装，
执行 pip check 和完整 105 包版本/额外包检查。setup.ps1 复用同一入口。

损坏的既有缓存文件直接失败并保留；不静默换包。下载使用独有临时文件，按清单
大小/哈希核对后发布，失败清理其临时文件。已有安装包的代码文件完整性不等同于
包版本检查；本机制认证交付文件，未认证正在运行的所有文件。只包含当前目标的
二进制哈希，不回退构建未经批准的源码包。

## 可重复审计

```powershell
.\tools\audit-dependencies.ps1
# 重建另一套全新审计环境并运行相同入口：
.\tools\audit-dependencies.ps1 -AuditEnvironmentDirectory runtime/audit-drill-20261015
```

入口验证三套锁/清单，核对主环境 105 包、用批准 wheel 准备隔离审计环境并核对
其 29 包，再分别导出**实际全部安装分发包**作为审计输入。未声明的额外包、重复
安装元数据、版本变化会被拒绝。审计只查询公共包版本，不运行自动修复或依赖解析。

每组审计在受监督子进程运行：总上限 600 秒、Job 内存 512 MiB、每输出流 256 KiB，
HTTP 单次超时 15 秒；子进程使用基本环境白名单和项目内的配置/缓存目录。过程
不继承应用数据库、S3、邮件或删除日志凭据。

通过条件要求审计退出 0、报告结构合法、每个输入包及版本精确覆盖、零跳过、零
漏洞记录。缺报告、错误对象、少包、重复项、版本错配、缺少漏洞结果字段、非零
工具退出均不能判为通过。重复公告保留原始记录，另计不同公告 ID。

`artifacts/python-advisory-run.json` 是本次总体状态，启动先写 passed=false，结束
记录成功或失败与 run_id。每个 run_id 有独立的只写一次输入、原始报告和摘要；
摘要绑定输入及原报告哈希，总体状态列出该 run_id 对应的摘要路径。
失败保留证据，固定路径的旧成功文件不能满足新调用。应同时检查总体状态、命令
退出码和当前 run_id 摘要；报告被外部篡改的防护仍依赖项目文件权限/仓库信任。

首次受控启动缺少 home 路径，审计未产生报告。该次整体状态已保留在
`artifacts/python-advisory-profile-failed.json`，对应独有 stderr 日志仍保留；流程正确
判为失败。现为子进程明确提供项目内 USERPROFILE/APPDATA/LOCALAPPDATA，实际
105/29 包审计均通过，零跳过、零已知命中。随后也以另一套全新 29 包审计环境
实际执行同一入口并通过，验证了初次创建及哈希安装分支。

`.github/workflows/python-advisories.yml` 配置按需、相关 PR 和每周扫描，仅授予
contents:read。两份工作流中的上游 Actions 引用已固定到从官方仓库读取的提交，
结构检查通过。**未在远程运行**，不能据此关闭 hosted CI 或生产供应链门槛。
本入口覆盖 Python；npm 和解释器/服务二进制仍需独立审查/定期检查。

## 本轮实测

- 124 个不同 wheel 的实际文件逐一复核；104 个应用/开发版本与旧提交相同。
- 全新环境的 pip check、105 包完整清单、真实 PDF 用例通过；该环境完整后端
  **158 项通过（427.61 秒）**，报告 `artifacts/hashed-environment-backend.xml`。
- 安全工具 **25 项测试通过**，包括损坏缓存、失败下载不发布、锁/来源/文件身份
  变化、额外/重复安装、审计不完整/失败报告及公告去重。
- 实际复制一个 colorama wheel 改动字节，用 pip 下载校验模式验证退出 1 并明确
  拒绝哈希不符，没有安装改动后的文件，报告 `artifacts/pip-tampered-wheel-proof.json`。
- 正常审计入口的 105 包/29 包报告均精确覆盖、零跳过、零已知命中，原始报告路径
  与摘要在 artifacts/；主环境未重装，浏览器代码未变。

全新 Python 环境仍使用本机已有解释器和本地 PostgreSQL/Redis/S3 服务。上述结果
不能作为全新操作系统、生产平台、完整 UI、外部 SMTP 或完整安全审查的证明。
