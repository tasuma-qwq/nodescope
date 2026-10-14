"""Offline tests for one-click history integration (--trend / save_run_history)."""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import core.history as history_mod  # noqa: E402
import one_click_check as occ  # noqa: E402


def _capture(fn):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn()
    return buf.getvalue()


def test_build_history_rows_shape():
    labels = {"香港A": "【8% 住宅|原生 综合4】", "坏节点": "【检测失败】"}
    results = {
        "香港A": {"ip": "1.2.3.4", "source": "ping0", "pure_score": "8%",
                  "geo": "HK", "isp": "ISP", "asn": "AS1", "ip_type": "住宅",
                  "multi_native": "原生", "dnsbl_blacklisted": False},
        "坏节点": {"ip": "❓", "source": "failed", "error": "down"},
    }
    rows = occ.build_history_nodes(labels, results)
    assert len(rows) == 2
    ok = rows[0]
    assert ok["name"] == "香港A【8% 住宅|原生 综合4】"
    assert ok["original_name"] == "香港A"
    assert ok["status"] == "✅" and ok["risk_score"] is not None
    bad = rows[1]
    assert bad["name"] == "坏节点【检测失败】" and bad["status"] == "❌ 失败"
    assert bad["risk_score"] is None and bad["risk_level"] == "未知"


def test_print_trend_reads_snapshots():
    with tempfile.TemporaryDirectory() as td:
        saved_dir_fn = history_mod._snapshot_abs_dir
        history_mod._snapshot_abs_dir = lambda: Path(td)
        try:
            for stamp, pure in (("20260917_090000", "12%"), ("20260918_090000", "8%")):
                snap = {
                    "meta": {"created_at": stamp, "node_count": 1, "batch_id": stamp, "summary": {}},
                    "nodes": [{
                        "name": f"香港A 【{pure} 住宅|原生 综合4】",
                        "original_name": "香港A",
                        "pure_score": pure,
                        "risk_score": 4,
                        "source": "ping0",
                        "status": "✅",
                    }],
                }
                (Path(td) / f"{stamp}_abc.json").write_text(
                    json.dumps(snap, ensure_ascii=False), encoding="utf-8"
                )
            out = _capture(lambda: occ.print_trend("香港A"))
            assert "[香港A]" in out
            assert out.index("12%") < out.index("8%"), "oldest first"
            nohit = _capture(lambda: occ.print_trend("不存在"))
            assert "没有匹配" in nohit
            empty = _capture(lambda: occ.print_trend(""))
            assert "用法" in empty
        finally:
            history_mod._snapshot_abs_dir = saved_dir_fn


def test_save_run_history_never_raises_offline():
    # auto_commit touches git; in-repo run is fine, but force an impossible
    # state (no labels/results) to confirm the silent paths.
    assert _capture(lambda: occ.save_run_history({}, {})) == ""
    junk = {"x": "not-a-dict"}
    _capture(lambda: occ.save_run_history({}, junk))


def main() -> int:
    tests = [
        test_build_history_rows_shape,
        test_print_trend_reads_snapshots,
        test_save_run_history_never_raises_offline,
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
