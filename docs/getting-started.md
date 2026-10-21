# 安装与首次使用

[首页](../README.md) · [文档导航](README.md) · [完整示例](research-walkthrough.md)

## 1. 环境要求

当前批准的依赖交付面向 Windows x64、64 位 CPython 3.12。安装 Git、Python、Node.js 26.1.0（含 npm）和 PowerShell，确认下面的命令可用：

```powershell
git --version
python --version
python -c "import struct,sys; print(sys.executable); print(struct.calcsize('P') * 8)"
node --version
npm --version
```

Python 应显示 3.12，位数为 64。Linux、macOS、其他 Python 版本不能直接使用当前 Windows wheel 锁。首次安装需要联网获取锁文件指定的依赖与本地服务二进制；阅读 `tools/setup.ps1` 和 `tools/services-lock.json` 可了解准备内容。

## 2. 克隆与安装

```powershell
git clone https://github.com/Fancy8/ResearchOS.git
cd ResearchOS
./tools/setup.ps1
```

安装使用项目内环境，不要求另行配置全局 PostgreSQL 服务。脚本创建数据库角色、运行 Alembic 迁移、准备存储与队列、构建前端并启动应用。生成的凭据和数据保存在忽略的 `runtime/`。不要把已有真实研究数据库用作首次安装目标。

## 3. 注册

```powershell
./runtime/venv/Scripts/python.exe ./tools/invite.py your-email@example.com
```

将邮箱改成自己的。命令只向本地终端输出邀请码，不发送邮件。打开 http://localhost:3000/login，切换注册，填写同一邮箱、邀请码、称呼以及至少 12 位密码。完成引导后，创建课题与研究线索。不要把邀请码、密码或会话截图提交到公开 Issue。

## 4. 再次启动

```powershell
./tools/start-services.ps1
./tools/start.ps1
```

Web 地址为 http://localhost:3000/login，API 文档为 http://127.0.0.1:58000/api/docs。端口与后台操作详见[本地运行手册](operating-local.md)。当前启动器绑定本机，不能把这组设置直接当作生产部署配置。

## 5. 开发验证

```powershell
./tools/verify.ps1
```

验证会使用专用真实 PostgreSQL 测试数据库、对象存储与浏览器测试。不要将测试配置指向生产数据。报告保存在忽略的 `artifacts/`。本地历史通过记录与远端 CI 状态分开理解，查看 [GitHub Actions](https://github.com/Fancy8/ResearchOS/actions) 获取实际托管运行结果。

## 常见问题

| 现象 | 检查方向 |
| --- | --- |
| 提示 Python 平台不受批准 | 检查 `python` 实际指向 CPython 3.12 x64；不要用删除哈希检查的方式绕过 |
| 下载或依赖安装失败 | 保留第一个失败步骤，核对网络和锁文件来源；[依赖交付说明](python-dependency-delivery.md)解释校验流程 |
| 登录页不能打开 | 从根目录启动服务与应用，查看忽略目录内的本地日志；分享日志前脱敏 |
| 注册被拒绝 | 确认邮箱与签发邀请码一致、邀请码未过期；服务端拒绝信息按实际处理 |
| PDF 没有可提取文字 | 先换自己制作的含文字 PDF；当前不提供扫描 OCR |
| 准备部署到公网 | 先阅读[路线图](roadmap.md)与[质量方案](07-quality-and-operations.md)，当前完整发布门禁未完成 |

有可复现错误请到 [Issues](https://github.com/Fancy8/ResearchOS/issues)，一般安装讨论到 [Discussions](https://github.com/Fancy8/ResearchOS/discussions)。仅附合成样例和脱敏信息。
