"""Offline tests for the opt-in legacy exports cleanup."""
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


def test_clean_keeps_stable_and_newest():
    with tempfile.TemporaryDirectory() as td:
        saved = occ.EXPORTS_DIR
        occ.EXPORTS_DIR = Path(td)
        try:
            files = {
                "checked_latest.yaml": b"stable",
                "meta.json": b"x",                       # not yaml → untouched
                "sub_checked_20260101-000000.yaml": b"old1",
                "sub_checked_20260201-000000.yaml": b"old2",
                "sub_checked_20260301-000000.yaml": b"old3",
                "clash_checked_ab12cd34.yaml": b"old4",
                "other.txt": b"y",
            }
            for name, body in files.items():
                p = Path(td) / name
                p.write_bytes(body)
            os.utime(Path(td) / "sub_checked_20260101-000000.yaml", (1000000, 1000000))
            os.utime(Path(td) / "sub_checked_20260201-000000.yaml", (2000000, 2000000))
            os.utime(Path(td) / "sub_checked_20260301-000000.yaml", (3000000, 3000000))
            os.utime(Path(td) / "clash_checked_ab12cd34.yaml", (4000000, 4000000))

            out = _capture(lambda: occ.clean_old_exports(keep=2))
            assert "已清理 2 个" in out, out
            assert (Path(td) / "checked_latest.yaml").exists()
            assert (Path(td) / "clash_checked_ab12cd34.yaml").exists()   # newest kept
            assert (Path(td) / "sub_checked_20260301-000000.yaml").exists()
            assert not (Path(td) / "sub_checked_20260201-000000.yaml").exists()
            assert not (Path(td) / "sub_checked_20260101-000000.yaml").exists()
            assert (Path(td) / "meta.json").exists() and (Path(td) / "other.txt").exists()

            again = _capture(lambda: occ.clean_old_exports(keep=2))
            assert "没有需要清理" in again
        finally:
            occ.EXPORTS_DIR = saved


def test_clean_missing_dir_never_raises():
    with tempfile.TemporaryDirectory() as td:
        saved = occ.EXPORTS_DIR
        occ.EXPORTS_DIR = Path(td) / "nope"
        try:
            out = _capture(lambda: occ.clean_old_exports())
            assert "没有需要清理" in out
        finally:
            occ.EXPORTS_DIR = saved


def main() -> int:
    tests = [
        test_clean_keeps_stable_and_newest,
        test_clean_missing_dir_never_raises,
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
