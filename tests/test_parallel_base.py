"""Offline tests for parallel-check base selection and payload dump."""
from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.clash_api import config_to_payload  # noqa: E402
from core.parallel import (  # noqa: E402
    config_has_nodes,
    looks_like_full_clash_config,
    select_parallel_base,
)


def _full(names):
    return {
        "mixed-port": 7897,
        "external-controller": "127.0.0.1:9097",
        "proxies": [{"name": n, "type": "ss", "server": "example.com"} for n in names],
    }


def test_fragment_is_not_full():
    fragment = {"proxies": [{"name": "a", "type": "ss"}]}
    assert looks_like_full_clash_config(fragment) is False
    assert looks_like_full_clash_config({"mixed-port": 7897}) is False
    assert looks_like_full_clash_config(None) is False
    assert looks_like_full_clash_config("x") is False


def test_full_config_accepted():
    cfg = _full(["hk", "jp"])
    assert looks_like_full_clash_config(cfg) is True
    assert config_has_nodes(cfg, ["hk", "jp"]) is True
    assert config_has_nodes(cfg, ["hk", "us"]) is False


def test_select_prefers_runtime_over_fragment():
    runtime = _full(["hk", "jp"])
    fragment = {"proxies": [{"name": "hk", "type": "ss"}, {"name": "jp", "type": "ss"}]}
    chosen = select_parallel_base(fragment, runtime, ["hk", "jp"])
    assert chosen is runtime


def test_select_uses_pasted_full_config_when_runtime_missing():
    pasted = _full(["hk", "jp"])
    chosen = select_parallel_base(pasted, None, ["hk", "jp"])
    assert chosen is pasted


def test_select_none_when_get_configs_summary():
    summary = {"mixed-port": 7897, "mode": "rule", "log-level": "info"}
    assert select_parallel_base(summary, None, ["hk"]) is None
    assert select_parallel_base(None, None, ["hk"]) is None
    assert select_parallel_base(_full(["hk"]), None, []) is None


def test_config_to_payload_is_yaml_not_json_object():
    payload = config_to_payload(_full(["hk"]))
    assert payload and "proxies:" in payload
    assert "mixed-port: 7897" in payload
    assert config_to_payload(None) is None
    assert config_to_payload({}) is None
    assert config_to_payload("nope") is None


def main() -> int:
    tests = [
        test_fragment_is_not_full,
        test_full_config_accepted,
        test_select_prefers_runtime_over_fragment,
        test_select_uses_pasted_full_config_when_runtime_missing,
        test_select_none_when_get_configs_summary,
        test_config_to_payload_is_yaml_not_json_object,
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
