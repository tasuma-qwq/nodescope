# NodeScope · 节点透镜

[English](README_EN.md) · [检测口径](docs/behavior.md) · [来源](docs/references.md) · [贡献](CONTRIBUTING.md)

[![Tests](https://github.com/tasuma-qwq/nodescope/actions/workflows/tests.yml/badge.svg)](https://github.com/tasuma-qwq/nodescope/actions/workflows/tests.yml)

**下载或克隆 → 双击“一键检测当前订阅.cmd” → 自动检查当前 Clash Verge 订阅。**

自动读取本机配置、控制器地址和密钥，无需打开网页、粘贴 YAML 或手填 API 密钥。检测完成后生成带数字标注的订阅，在窗口里显示检测结果与推荐。

基于 [tombcato/clash-ip-checker](https://github.com/tombcato/clash-ip-checker) 的衍生项目，保留上游署名与许可。

## 第一次使用（Windows）

前提：已安装 **Python 3.10+**，使用 **Clash Verge Rev 默认数据目录**，并开启 External Controller。便携版、自定义数据目录和其他客户端的自动读取尚未支持。

1. 打开 Clash Verge Rev，选中要检测的订阅。
2. 点击仓库 **Code → Download ZIP** 后解压，或者运行：
   ```bash
   git clone https://github.com/tasuma-qwq/nodescope.git
   ```
3. 双击 **`一键检测当前订阅.cmd`**（英文入口 `start.cmd` 完全相同）。
4. 首次自动创建项目自己的 `.venv` 并安装检测依赖，需要联网。后续直接使用；无需安装浏览器，也不会启动 Web 页面。
5. 窗口自动检测当前订阅，默认包含 ChatGPT / Gemini / Claude / Netflix / YouTube 端点探测，结束后保留窗口，结果在 `exports/`。

**首次使用**会唤起 Clash Verge 导入“已检测”配置，请在客户端确认。以后重新检测后，在这张卡片点 **“更新”** 刷新分数和流量，不必重复导入。

固定更新服务使用本机 `127.0.0.1:57520`。服务需保持运行；端口被其他副本占用时，不会结束旧进程，而是回退到临时导入。项目移动位置后，旧服务和旧更新卡片可能需要你自行处理。

检测会临时切换节点或重载配置，可能中断网络连接。请避开会议、下载等不能中断的任务。完成后会尝试恢复配置和原分组选择；强制关窗口或终止进程可能来不及恢复。

## 能看到什么

- Ping0 / IPPure 污染度与主备降级，可选多源与 DNSBL 风险信号。
- Mihomo listeners 并行检测，前置条件不满足时回退串行。
- 数字标签，例如 `【8% 住宅|原生 共享10-50 综合12】`，保留原订阅节点。
- 延迟、地区概览、用途推荐与相较上次检测的变化。
- 本机历史与趋势，默认不自动提交 Git。
- AI / 流媒体端点访问线索：挑战页、限流或陌生页面保留未知，不能当作“已解锁”。

污染度、综合风险都越低越好，未知不会填成 0。“原生 / 广播”是地区一致性推断，不能证明住宅身份。IP 质量、页面可达和地区码不能证明账号资格、登录成功或真实模型可用性。见 [检测口径](docs/behavior.md)。

## 可选参数

用终端运行项目的 `start.cmd`，仍会自动准备环境，默认带 `--unlock`：

```powershell
.\start.cmd --help
.\start.cmd --serial
.\start.cmd --no-history
.\start.cmd --trend 节点关键词
```

熟悉 Python 的用户也可自行安装并运行，仅需 CLI 依赖：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-cli.txt
.\.venv\Scripts\python.exe one_click_check.py --unlock
```

直接运行 Python 入口而不加 `--unlock`，可以关闭额外服务探测。

## 数据保存在本机

运行时配置、密钥不需要手动搬运。检测会访问对应外部查询站点，查询结果和导出保存在本机。`exports/` 内 YAML **含真实代理凭据，不要公开分享**。本地 `history/` 可能含节点名与出口 IP。

`config.yaml`、`.env`、`exports/`、`history/`、日志和虚拟环境已忽略。公开仓库不包含原环境的私有 Git 历史、真实检测记录或原始截图。

## 开发与可选旧入口

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
python scripts/check_release.py
```

自动检查覆盖 Windows / Linux × Python 3.10 / 3.12；一键检测面向 Windows Clash Verge Rev。离线测试不连接正在使用的 Clash，见 [验证记录](docs/validation.md)。

原有 Web、匿名报告和其他客户端手动配置入口保留作高级功能，下载后的默认入口不依赖它们。需要时安装 `requirements.txt` 后运行 `web.py`；旧 CLI 使用 `config.yaml.example` 与 `clash_automator.py`。

## 来源与许可

直接基础为 `tombcato/clash-ip-checker`（GPL-3.0），已有探针参考 `lmc999/RegionRestrictionCheck` 和 `xykt/IPQuality`（AGPL-3.0）。组合分发采用 **AGPL-3.0**，原 GPL 部分许可保留在 [LICENSES/GPL-3.0.txt](LICENSES/GPL-3.0.txt)。见 [LICENSE](LICENSE) 与 [第三方说明](THIRD_PARTY_NOTICES.md)。

