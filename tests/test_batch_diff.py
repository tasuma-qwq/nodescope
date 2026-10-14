"""Offline tests for the run-over-run diff (vs previous stable export)."""
from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
from pathlib import Path

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import one_click_check as occ  # noqa: E402


def _capture(fn):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn()
    return buf.getvalue()


def _result(pure, source="ippure"):
    return {"ip": "1.2.3.4", "source": source, "pure_score": pure}


def test_load_previous_labels_parses_and_strips():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "checked_latest.yaml"
        path.write_text(
            "proxies:\n"
            "  - name: '香港A 【5% 住宅|原生 综合2】'\n"
            "  - name: '日本B 【检测失败】'\n"
            "  - name: '无标注节点'\n",
            encoding="utf-8",
        )
        labels = occ.load_previous_labels(path)
        assert labels["香港A"] == {"pure": 5.0, "fail": False}, labels
        assert labels["日本B"]["fail"] is True
        assert labels["无标注节点"]["fail"] is False and labels["无标注节点"]["pure"] is None
        assert occ.load_previous_labels(Path(td) / "missing.yaml") == {}


def test_print_changes_categories():
    old = {
        "恢复了": {"pure": 50.0, "fail": True},
        "变坏了": {"pure": 10.0, "fail": False},
        "变脏了": {"pure": 20.0, "fail": False},
        "变净了": {"pure": 80.0, "fail": False},
        "没变化": {"pure": 30.0, "fail": False},
        "新节点": {"pure": 1.0, "fail": False},
    }
    results = {
        "恢复了": _result("40%"),
        "变坏了": _result("x", source="failed"),
        "变脏了": _result("45%"),
        "变净了": _result("55%"),
        "没变化": _result("31%"),
        "新节点": _result("1%"),
    }
    out = _capture(lambda: occ.print_changes_vs_previous(old, results))
    assert "与上次检测对比" in out
    assert "恢复检出: 恢复了" in out
    assert "转为失败: 变坏了" in out
    assert "变脏了（20% → 45%）" in out
    assert "变净了（80% → 55%）" in out
    assert "没变化" not in out and "新节点" not in out


def test_print_changes_quiet_paths_never_raise():
    assert _capture(lambda: occ.print_changes_vs_previous({}, {"x": _result("5%")})) == ""
    assert _capture(lambda: occ.print_changes_vs_previous(None, None)) == ""
    junk = {"a": {"pure": 5.0, "fail": False}}
    assert _capture(lambda: occ.print_changes_vs_previous(junk, {"a": "not-a-dict", "b": None})) == ""
    # Small shifts (<10) stay silent.
    out = _capture(lambda: occ.print_changes_vs_previous({"n": {"pure": 30.0, "fail": False}}, {"n": _result("35%")}))
    assert out == ""


def main() -> int:
    tests = [
        test_load_previous_labels_parses_and_strips,
        test_print_changes_categories,
        test_print_changes_quiet_paths_never_raise,
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
