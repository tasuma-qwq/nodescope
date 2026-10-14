"""Offline tests for the end-of-run usage summary."""
from __future__ import annotations

import contextlib
import io
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import one_click_check as occ  # noqa: E402


def _result(pure, ip_src, ip_attr, risk_inputs=None, source="ippure"):
    row = {"ip": "1.2.3.4", "source": source, "pure_score": pure,
           "ip_src": ip_src, "multi_native": ip_src, "ip_attr": ip_attr, "ip_type": ip_attr}
    row.update(risk_inputs or {})
    return row


def _capture(fn):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn()
    return buf.getvalue()


def test_summary_ranks_and_excludes_hk_for_ai():
    results = {
        "🇭🇰 香港家宽01": _result("0%", "原生", "住宅"),          # cleanest overall, but HK
        "🇰🇷 韩国01": _result("3%", "原生", "住宅", {"dnsbl_blacklisted": False}),
        "🇺🇸 美国BGP09": _result("38%", "广播", "机房", {"is_proxy_votes": 2}),
        "🇯🇵 日本01": _result("87%", "广播", "机房"),
        "废节点": {"ip": "❓", "source": "failed"},                  # ignored
        "🇸🇬 新加坡01": _result("12%", "原生", "住宅"),
    }
    out = _capture(lambda: occ.print_usage_summary(results))
    assert "GPT/Gemini 首选" in out
    # AI picks must be non-HK, native+residential first, lowest risk/pure first:
    assert "韩国01" in out.split("GPT/Gemini 首选")[1].split("GitHub")[0]
    assert "香港家宽01" not in out.split("GPT/Gemini 首选")[1].split("GitHub")[0]
    assert "新加坡01" in out.split("GPT/Gemini 首选")[1].split("GitHub")[0]
    # General picks: lowest composite risk first — HK 家宽 (risk≈0) wins here.
    general = out.split("GitHub/X/日常")[1].split("地区概览")[0]
    assert "香港家宽01" in general
    assert "地区概览" in out


def test_summary_never_raises_and_short_circuits():
    assert _capture(lambda: occ.print_usage_summary({})) == ""
    assert _capture(lambda: occ.print_usage_summary({"a": {"ip": "❓", "source": "failed"}})) == ""
    junk = {"a": "not-a-dict", "b": 3, "c": None, "d": _result("bad%", "x", "y")}
    assert _capture(lambda: occ.print_usage_summary(junk)) == ""


def test_summary_delay_and_unlock_in_description():
    results = {
        f"节点{i}": _result("5%", "原生", "住宅") for i in range(4)
    }
    best = results["节点0"]
    best["_delay"] = 88
    best["unlock"] = {"chatgpt": {"status": "yes"}}
    out = _capture(lambda: occ.print_usage_summary(results))
    assert "88ms" in out and "GPT✅" in out


def test_summary_gpt_unlock_reorders_ai_picks():
    # 印尼干净但 GPT 确认封锁 → 必须排到 GPT 确认可用的日本节点之后。
    results = {
        "🇮🇩 印尼01": _result("3%", "原生", "住宅"),
        "🇯🇵 日本01": _result("30%", "广播", "机房"),
        "🇰🇷 韩国01": _result("20%", "原生", "住宅"),
        "🇸🇬 新加坡01": _result("15%", "原生", "住宅"),
    }
    results["🇮🇩 印尼01"]["unlock"] = {"chatgpt": {"status": "no"}}
    results["🇯🇵 日本01"]["unlock"] = {"chatgpt": {"status": "yes"}}
    results["🇰🇷 韩国01"]["unlock"] = {"chatgpt": {"status": "yes"}}
    results["🇸🇬 新加坡01"]["unlock"] = {"chatgpt": {"status": "unknown"}}
    out = _capture(lambda: occ.print_usage_summary(results))
    ai = out.split("GPT/Gemini 首选")[1].split("GitHub")[0]
    assert "已按实测 GPT 解锁排序" in out
    # 封锁的印尼必须跌出 top-3；两个 GPT 可用节点按质量排序（韩>日）。
    assert "印尼01" not in ai
    assert "日本01" in ai and "韩国01" in ai
    assert ai.index("韩国01") < ai.index("日本01")
    # 无解锁数据时排序退回质量口径（不炸）。
    for row in results.values():
        row.pop("unlock")
    out2 = _capture(lambda: occ.print_usage_summary(results))
    assert "GPT/Gemini 首选" in out2 and "已按实测" not in out2


def main() -> int:
    tests = [
        test_summary_ranks_and_excludes_hk_for_ai,
        test_summary_never_raises_and_short_circuits,
        test_summary_delay_and_unlock_in_description,
        test_summary_gpt_unlock_reorders_ai_picks,
    ]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
        except Exception as exc:
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"  FAIL  {fn.__name__}: {type(exc).__name__}: {exc}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
