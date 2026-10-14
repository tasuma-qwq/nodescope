# 来源与第三方组件

NodeScope 是衍生与组合项目，不是从零独立编写的检测引擎。

- [tombcato/clash-ip-checker](https://github.com/tombcato/clash-ip-checker)：原 Python Web、CLI、核心和页面实现来自此 GPL-3.0 项目。原许可证逐字保留于 `LICENSES/GPL-3.0.txt`，原作者与贡献者权利保留。为避免传播私有记录，从源码快照开始公开，不复制本地 Git 历史。
- [RegionRestrictionCheck](https://github.com/lmc999/RegionRestrictionCheck)：已有 `core/unlock.py` 端点与判定适配来源，AGPL-3.0。
- [IPQuality](https://github.com/xykt/IPQuality)：已有探针思路及多源参考，AGPL-3.0。本次报告独立实现。
- [ipregion](https://github.com/vernette/ipregion)：多源地区表达的设计参考，MIT，未引入代码。

组合分发采用 AGPL-3.0，GPL-3.0 原部分继续遵循原许可。参见 GPL-3.0 第 13 节与根目录 `LICENSE`。新的 NodeScope 改动 Copyright (c) 2026 NodeScope contributors。

## 本地前端资源

固定版本分发文件保持原样。完整 MIT 许可保存在各自目录，来源与 SHA-256 在 `static/vendor/manifest.json`。

| 组件 | 版本 | 来源 |
| --- | --- | --- |
| Pico CSS | 2.1.1 | https://github.com/picocss/pico |
| Alpine.js | 3.14.9 | https://github.com/alpinejs/alpine |
| CodeMirror | 5.65.16 | https://github.com/codemirror/codemirror5 |

Python 依赖通过 requirements 安装，保留各自许可，源码未复制到本仓库。
