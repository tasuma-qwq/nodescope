# GitHub 参考与取舍

2026-10-14 查看仓库和 README，并结合本地实现检查。星数是当次快照，不代替质量验证。本次没有执行这些仓库的安装脚本。

| 项目 | 星数 / 许可 | 采用方向 |
| --- | --- | --- |
| [tombcato/clash-ip-checker](https://github.com/tombcato/clash-ip-checker) | 1,075 / GPL-3.0 | 直接源码基础，保留署名、原许可。基线 `4bbebe0a1bf1cbddcde55660b4248d5a272bef57`。 |
| [xykt/IPQuality](https://github.com/xykt/IPQuality) | 10,701 / AGPL-3.0 | 多源、结构化报告、隐私模式的产品方向。NodeScope 报告独立以白名单构造。 |
| [vernette/ipregion](https://github.com/vernette/ipregion) | 500 / MIT | 服务地区应各自表达，不把一个结论推广到所有服务。未引入其代码。 |
| [lmc999/RegionRestrictionCheck](https://github.com/lmc999/RegionRestrictionCheck) | 5,145 / AGPL-3.0 | 已有 Python 探针端点适配来源；本次增加挑战页、错误码与陌生页面分支。 |

优先修正已有可靠性与公开边界，不为数量增加未经验证的探针，也没有接入托管后台或在线报告收集服务。
