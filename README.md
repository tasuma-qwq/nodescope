# NodeScope · 节点透镜

[English](README_EN.md) · [使用与边界](docs/behavior.md) · [参考项目](docs/references.md) · [参与贡献](CONTRIBUTING.md)

[![Tests](https://github.com/tasuma-qwq/nodescope/actions/workflows/tests.yml/badge.svg)](https://github.com/tasuma-qwq/nodescope/actions/workflows/tests.yml)

在自己的电脑上批量检查 Clash / Mihomo 节点，对比 IP 污染度、综合风险、延迟与服务访问线索，再导出带数字标注的订阅。

**基于 [tombcato/clash-ip-checker](https://github.com/tombcato/clash-ip-checker) 的衍生项目**，保留原有检测与导出能力，补充隐私边界、保守服务判定、匿名报告和自动回归。

## 功能

- **批量检测**：Ping0 / IPPure 主备源；可选 ip-api、AbuseIPDB、IP2Location、IPQS、DNSBL 交叉参考。
- **并行与恢复**：Mihomo listeners 并行检查，退出恢复基础配置与分组选择，前置条件不满足时回退串行。
- **数字标注**：例如 `【8% 住宅|原生 共享10-50 综合12】`；污染度和综合风险都越低越好。
- **历史趋势**：按原节点名比较，本地保存，默认不自动提交 Git。
- **匿名 JSON 报告**：使用 `Node 001` 别名，排除 IP、订阅、凭据和原始错误，适合分享指标。
- **可选服务探针**：ChatGPT、Gemini、Claude、Netflix、YouTube；挑战页、限流和陌生页面保留未知。
- **本地 Web**：页面资源随仓库提供，无需第三方 CDN；接口限制本地同源访问。

## 第一次使用（Windows）

1. 安装 **Python 3.10 或更新版本**，打开 Clash Verge / Mihomo 客户端。
2. 在本仓库点击 **Code → Download ZIP**，解压到普通文件夹。
3. 双击 **`start.cmd`**。首次会在项目 `.venv` 中安装依赖，需要联网。看到地址后打开 [http://127.0.0.1:8080](http://127.0.0.1:8080)。
4. 粘贴 YAML 订阅，将客户端设置里的 **External Controller 地址和密钥** 填入工具，再开始检测。
5. 选择节点并导出 YAML。**YAML 含真实代理凭据，仅用于自己的客户端**；想分享指标时点击“匿名报告”。

检测会访问外部 IP / 服务站点，可能切换节点、重载配置并中断活动连接。请避开下载、会议或不能中断的任务。检测失败不代表节点永久不可用。

## 手动安装（Windows / Linux / macOS）

```bash
git clone https://github.com/tasuma-qwq/nodescope.git
cd nodescope
python -m venv .venv
```

Windows：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe web.py
```

Linux / macOS：

```bash
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python web.py
```

极速模式无需安装浏览器。只有关闭极速模式时，才需要额外运行 `python -m playwright install chromium`（使用你的虚拟环境 Python）。

Web 入口跨平台；**自动读取 Clash Verge 当前订阅的一键入口针对 Windows**：

```powershell
.\.venv\Scripts\python.exe one_click_check.py
.\.venv\Scripts\python.exe one_click_check.py --unlock
.\.venv\Scripts\python.exe one_click_check.py --serial
.\.venv\Scripts\python.exe one_click_check.py --trend 节点关键词
```

一键入口尝试在 `127.0.0.1:57520` 提供稳定订阅，Web 提供 `/api/export/subscribe`。首次导入后在 Clash Verge 点“更新”即可刷新同一张卡片；服务必须保持运行。其他副本占用端口时，不会自动终止它。

旧版 CLI：复制 `config.yaml.example` 为 `config.yaml`，填写 `yaml_path` 与控制器参数，再运行 `python clash_automator.py`。

## 如何理解结果

| 指标 | 含义与限制 |
| --- | --- |
| 污染度 | 数据库估算，低值通常更好；未知不会填 0。 |
| 综合风险 | 按可用信号加权；DNSBL 命中至少 90，无足够数据为未知。 |
| 原生 / 广播 | 多源地区一致性推断，不能证明注册、线路或住宅真实性。 |
| 服务信号 | 端点访问线索；`❔` 为未知/失败，不能推导可用或封锁。 |
| 延迟 | 到测试 URL 的瞬时测量，不代表吞吐量或长期稳定性。 |
| DNS / WebRTC | 诊断参考，不是完整隐私证明；WebRTC 需要主动点击。 |

IP 质量、地区码或页面可达，**均不能证明账号资格、官方支持地区、登录成功或真实模型可用性**。详见 [行为说明](docs/behavior.md)。

## 数据与开源范围

配置和历史保存在本机；检测会向对应外部服务发送查询，配 Key 的服务会收到其 Key。页面不会自动将订阅上传到项目作者的服务器。

`config.yaml`、`.env`、`exports/`、`history/`、日志和虚拟环境已忽略。公开仓库不包含原环境的 Git 历史、真实检测记录与原始截图。不要将本工具直接暴露到公网。

## 开发与验证

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
python scripts/check_release.py
```

测试使用假控制器、模拟响应和临时目录，不连接正在使用的 Clash。CI 覆盖 Windows / Linux 与 Python 3.10 / 3.12；见 [验证范围](docs/validation.md)。

没有真实节点也可预览：运行 `python scripts/preview_demo.py`，打开 `http://127.0.0.1:8081`，粘贴 `examples/demo.yaml.example`。页面会明确标注“演示模式”，所有结果为模拟数据。

## 来源与许可

直接源码基础为 `tombcato/clash-ip-checker`（GPL-3.0），已有服务探针参考 `lmc999/RegionRestrictionCheck` 与 `xykt/IPQuality`（AGPL-3.0）。NodeScope 组合分发采用 **AGPL-3.0**，原 GPL 部分及许可继续保留于 [LICENSES/GPL-3.0.txt](LICENSES/GPL-3.0.txt)。见 [LICENSE](LICENSE)、[第三方说明](THIRD_PARTY_NOTICES.md)。

