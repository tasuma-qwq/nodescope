"""Standalone tests for history trend matching by original_name.

Run: python tests/test_history_trend.py

Writes only into a TemporaryDirectory; never touches the real history/ dir.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core import history  # noqa: E402


def _ok(name: str) -> None:
    print(f"  PASS  {name}")


def _fail(name: str, msg: str) -> None:
    print(f"  FAIL  {name}: {msg}")


def _write_snap(tmpdir: Path, fname: str, created_at: str, nodes: list) -> None:
    payload = {
        "meta": {
            "created_at": created_at,
            "batch_id": "",
            "node_count": len(nodes),
            "summary": {},
        },
        "nodes": nodes,
    }
    with open(tmpdir / fname, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)


class _TempHistory:
    def __init__(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.path = Path(self._td.name)
        self._orig = history._snapshot_abs_dir

    def __enter__(self) -> Path:
        tmp = self.path
        history._snapshot_abs_dir = lambda p=tmp: p
        return tmp

    def __exit__(self, exc_type, exc, tb) -> None:
        history._snapshot_abs_dir = self._orig
        self._td.cleanup()


def test_snapshot_fields_include_original_name() -> None:
    assert "original_name" in history.SNAPSHOT_FIELDS
    assert "name" in history.SNAPSHOT_FIELDS
    assert "pure_score" in history.SNAPSHOT_FIELDS
    assert "risk" in history.SNAPSHOT_FIELDS


def test_save_snapshot_persists_original_name() -> None:
    with _TempHistory() as tmp:
        rel = history.save_snapshot([
            {
                "name": "HK-01 \U0001f7e2",
                "original_name": "HK-01",
                "pure_score": "10%",
                "risk": "low",
                "skip_me": "nope",
            }
        ])
        assert rel, "save_snapshot returned empty path"
        fname = os.path.basename(rel)
        assert (tmp / fname).is_file()
        data = history.load_snapshot(fname)
        assert isinstance(data, dict), data
        nodes = data.get("nodes")
        assert isinstance(nodes, list) and len(nodes) == 1, nodes
        node = nodes[0]
        assert node.get("original_name") == "HK-01", node
        assert node.get("name") == "HK-01 \U0001f7e2", node
        assert node.get("pure_score") == "10%", node
        assert node.get("risk") == "low", node
        assert "skip_me" not in node, node
        assert not (Path(ROOT) / "history" / fname).exists()


def test_same_original_name_aggregates_across_renames() -> None:
    with _TempHistory():
        _write_snap(
            history._snapshot_abs_dir(),
            "20260101_000000_aaaaaa.json",
            "2026-01-01T00:00:00Z",
            [{
                "name": "HK-01 \U0001f7e2",
                "original_name": "HK-01",
                "pure_score": "10%",
                "risk_score": 4,
                "risk_level": "\u4f4e\u98ce\u9669",
            }],
        )
        _write_snap(
            history._snapshot_abs_dir(),
            "20260102_000000_bbbbbb.json",
            "2026-01-02T00:00:00Z",
            [{
                "name": "HK-01 \U0001f534",
                "original_name": "HK-01",
                "pure_score": "80%",
                "risk_score": 42,
                "risk_level": "\u4e2d\u98ce\u9669",
            }],
        )
        items = history.trend_for_node("HK-01")
        assert len(items) == 2, items
        assert items[0]["time"] == "2026-01-01T00:00:00Z", items
        assert items[1]["time"] == "2026-01-02T00:00:00Z", items
        assert items[0]["pure_score"] == "10%", items
        assert items[1]["pure_score"] == "80%", items
        assert items[0]["risk_score"] == 4, items
        assert items[1]["risk_score"] == 42, items
        # Display-name suffix must not be the match key.
        assert history.trend_for_node("HK-01 \U0001f7e2") == []


def test_legacy_snapshot_matches_by_name() -> None:
    with _TempHistory():
        _write_snap(
            history._snapshot_abs_dir(),
            "20260101_120000_cccccc.json",
            "2026-01-01T12:00:00Z",
            [{
                "name": "JP-02",
                "pure_score": "25%",
                "risk_score": 8,
            }],
        )
        items = history.trend_for_node("JP-02")
        assert len(items) == 1, items
        assert items[0]["time"] == "2026-01-01T12:00:00Z", items
        assert items[0]["pure_score"] == "25%", items
        assert items[0]["risk_score"] == 8, items


def test_empty_and_non_str_return_empty() -> None:
    with _TempHistory():
        _write_snap(
            history._snapshot_abs_dir(),
            "20260101_000000_dddddd.json",
            "2026-01-01T00:00:00Z",
            [{"name": "HK-01", "original_name": "HK-01"}],
        )
        assert history.trend_for_node("") == []
        assert history.trend_for_node(None) == []  # type: ignore[arg-type]
        assert history.trend_for_node(123) == []  # type: ignore[arg-type]
        assert history.trend_for_node([]) == []  # type: ignore[arg-type]


def test_trend_never_raises() -> None:
    with _TempHistory() as tmp:
        (tmp / "not-json.json").write_text("{not json", encoding="utf-8")
        (tmp / "20260101_000000_eeeeee.json").write_text(
            json.dumps({"meta": {"created_at": "bad-time"}, "nodes": "nope"}),
            encoding="utf-8",
        )
        items = history.trend_for_node("anything")
        assert items == [], items


def main() -> int:
    tests = [
        test_snapshot_fields_include_original_name,
        test_save_snapshot_persists_original_name,
        test_same_original_name_aggregates_across_renames,
        test_legacy_snapshot_matches_by_name,
        test_empty_and_non_str_return_empty,
        test_trend_never_raises,
    ]
    failed = 0
    print("history trend_for_node")
    for fn in tests:
        name = fn.__name__
        try:
            fn()
        except Exception as exc:
            failed += 1
            _fail(name, f"{type(exc).__name__}: {exc}")
            traceback.print_exc()
        else:
            _ok(name)
    total = len(tests)
    print(f"\n{total - failed}/{total} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
