"""Text-only node labels: no emoji, numeric purity on the original name."""
from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.labels import FAIL_LABEL, format_data_label, strip_existing_label  # noqa: E402


def test_strip_emoji_and_data_suffixes():
    assert strip_existing_label("HK-01【⚪ 住宅|原生】") == "HK-01"
    assert strip_existing_label("HK-01【8% 住宅|原生 综合4】") == "HK-01"
    assert strip_existing_label("HK-01【8% 住宅|原生】【检测失败】") == "HK-01"
    assert strip_existing_label("剩余流量") == "剩余流量"
    assert strip_existing_label("") == ""


def test_numeric_label_no_emoji():
    label = format_data_label({
        "pure_score": "8%",
        "ip_attr": "住宅",
        "ip_src": "原生",
        "shared_users": "10-50",
    })
    assert "⚪" not in label and "🟢" not in label
    assert label.startswith("【") and label.endswith("】")
    assert "8%" in label
    assert "住宅|原生" in label
    assert "共享10-50" in label
    assert "综合4" in label  # 8% pollution → int(8*0.5)=4


def test_dirty_score_and_blacklist():
    label = format_data_label({
        "pure_score": "85",
        "ip_type": "数据中心",
        "multi_native": "广播",
        "dnsbl_blacklisted": True,
    })
    assert "85%" in label
    assert "数据中心|广播" in label
    assert "黑名单" in label
    assert "⚪" not in label


def test_export_keeps_original_subscription_nodes():
    import tempfile
    from pathlib import Path
    from one_click_check import export_checked_config

    original = {
        "proxies": [
            {"name": "HK-01【⚪ 住宅|原生】", "type": "ss"},
            {"name": "JP-02", "type": "ss"},
            {"name": "剩余流量", "type": "ss"},
        ],
        "proxy-groups": [{"name": "PROXY", "proxies": ["HK-01【⚪ 住宅|原生】", "JP-02", "剩余流量", "DIRECT"]}],
    }
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "out.yaml"
        export_checked_config(
            original,
            {"HK-01【⚪ 住宅|原生】": "【8% 住宅|原生 综合4】", "JP-02": "【检测失败】"},
            out,
        )
        import yaml
        data = yaml.safe_load(out.read_text(encoding="utf-8"))
        names = [p["name"] for p in data["proxies"]]
        assert names == ["HK-01【8% 住宅|原生 综合4】", "JP-02【检测失败】", "剩余流量"]
        assert "DIRECT" in data["proxy-groups"][0]["proxies"]
        assert data["proxy-groups"][0]["proxies"][0] == "HK-01【8% 住宅|原生 综合4】"


def test_missing_result_is_fail_text():
    assert format_data_label({}) == FAIL_LABEL
    assert format_data_label(None) == FAIL_LABEL  # type: ignore[arg-type]
    assert "❌" not in FAIL_LABEL
    assert "❓" not in FAIL_LABEL


def main() -> int:
    tests = [
        test_strip_emoji_and_data_suffixes,
        test_numeric_label_no_emoji,
        test_dirty_score_and_blacklist,
        test_export_keeps_original_subscription_nodes,
        test_missing_result_is_fail_text,
    ]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
        except Exception as exc:
            failed += 1
            print(f"  FAIL  {fn.__name__}: {type(exc).__name__}: {exc}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
