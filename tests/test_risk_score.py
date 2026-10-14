"""Standalone assertions for compute_risk_score. Run: python tests/test_risk_score.py"""
from __future__ import annotations

import os
import sys
import traceback

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.risk_score import compute_risk_score  # noqa: E402


def _ok(name: str) -> None:
    print(f"  PASS  {name}")


def _fail(name: str, msg: str) -> None:
    print(f"  FAIL  {name}: {msg}")


def test_pure_score_clean_is_low_risk() -> None:
    r = compute_risk_score({"pure_score": "8%"})
    assert r["breakdown"]["pure_score"] == 4, r
    assert r["risk_score"] == 4, r
    assert r["risk_level"] == "低风险", r
    assert "dns_leak" not in r["breakdown"], r


def test_pure_score_dirty_contributes_42() -> None:
    r = compute_risk_score({"pure_score": "85%"})
    assert r["breakdown"]["pure_score"] == 42, r
    assert r["risk_score"] == 42, r
    assert r["risk_level"] == "中风险", r


def test_broadcast_from_multi_native() -> None:
    r = compute_risk_score({"multi_native": "广播"})
    assert r["breakdown"].get("multi_native") == 10, r
    assert 10 in r["breakdown"].values(), r
    assert r["risk_score"] == 10, r
    assert "ip_type" not in r["breakdown"], r


def test_ip_type_datacenter_is_not_broadcast() -> None:
    r = compute_risk_score({"ip_type": "数据中心"})
    assert r["risk_score"] is None, r
    assert r["risk_level"] == "未知", r
    assert r["breakdown"] == {}, r


def test_dns_leak_never_scored() -> None:
    leak_only = compute_risk_score({"dns_leak_state": "leak"})
    assert "dns_leak" not in leak_only["breakdown"], leak_only
    assert leak_only["risk_score"] is None, leak_only
    assert leak_only["risk_level"] == "未知", leak_only

    combined = compute_risk_score({"pure_score": "8%", "dns_leak_state": "leak"})
    assert "dns_leak" not in combined["breakdown"], combined
    assert combined["breakdown"]["pure_score"] == 4, combined
    assert combined["risk_score"] == 4, combined
    assert combined["risk_level"] == "低风险", combined


def test_dnsbl_veto_at_least_90() -> None:
    r = compute_risk_score({"dnsbl_blacklisted": True})
    assert r["breakdown"]["dnsbl_blacklisted"] == 90, r
    assert r["risk_score"] >= 90, r
    assert r["risk_score"] == 90, r
    assert r["risk_level"] == "高风险", r


def test_empty_dict_unknown() -> None:
    r = compute_risk_score({})
    assert r["risk_score"] is None, r
    assert r["risk_level"] == "未知", r
    assert r["breakdown"] == {}, r


def test_non_dict_does_not_raise() -> None:
    for bad in (None, "foo", 123, [], 3.14, True, object()):
        r = compute_risk_score(bad)  # type: ignore[arg-type]
        assert r["risk_score"] is None, (bad, r)
        assert r["risk_level"] == "未知", (bad, r)
        assert r["breakdown"] == {}, (bad, r)


def test_broadcast_from_ip_src_or_native() -> None:
    src = compute_risk_score({"ip_src": "广播"})
    assert src["breakdown"].get("ip_src") == 10, src
    assert src["risk_score"] == 10, src

    native = compute_risk_score({"native": "广播"})
    assert native["breakdown"].get("native") == 10, native
    assert native["risk_score"] == 10, native


def test_remaining_weights_and_cap() -> None:
    r = compute_risk_score(
        {
            "abuse_score": 100,
            "ipqs_fraud_score": 100,
            "is_tor": True,
            "is_proxy_votes": 2,
            "is_vpn_votes": 2,
            "is_datacenter": True,
        }
    )
    assert r["breakdown"]["abuse_score"] == 30, r
    assert r["breakdown"]["ipqs_fraud_score"] == 20, r
    assert r["breakdown"]["is_tor"] == 30, r
    assert r["breakdown"].get("is_proxy") == 20, r
    assert "is_vpn" not in r["breakdown"], r
    assert r["breakdown"]["is_datacenter"] == 15, r
    # 30+20+30+20+15 = 115 → cap 100
    assert r["risk_score"] == 100, r
    assert r["risk_level"] == "高风险", r


def test_proxy_vpn_needs_two_source_agreement() -> None:
    # Two independent sources agree True on proxy → +20.
    two = compute_risk_score({"pure_score": "0%", "is_proxy": True, "is_proxy_votes": 2})
    assert two["breakdown"].get("is_proxy") == 20, two
    assert two["risk_score"] == 20, two

    # Same on vpn.
    vpn_two = compute_risk_score({"pure_score": "0%", "is_vpn": True, "is_vpn_votes": 2})
    assert vpn_two["breakdown"].get("is_vpn") == 20, vpn_two

    # One-source True (votes < 2): stays on the node, not scored.
    one = compute_risk_score({"pure_score": "0%", "is_proxy": True, "is_proxy_votes": 1})
    assert "is_proxy" not in one["breakdown"], one
    assert one["risk_score"] == 0, one

    # Votes field missing entirely (legacy/plain dicts): not scored either.
    none = compute_risk_score({"pure_score": "0%", "is_proxy": True, "is_vpn": True})
    assert "is_proxy" not in none["breakdown"] and "is_vpn" not in none["breakdown"], none

    # bool vote counts are garbage, not votes.
    junk = compute_risk_score({"pure_score": "0%", "is_proxy_votes": True})
    assert "is_proxy" not in junk["breakdown"], junk


def test_placeholders_skipped() -> None:
    r = compute_risk_score(
        {
            "pure_score": "❓",
            "abuse_score": "unknown",
            "ipqs_fraud_score": "n/a",
            "dns_leak_state": "leak",
            "ip_type": "广播",
            "multi_native": "未知",
            "ip_src": "?",
            "native": "",
        }
    )
    assert r["risk_score"] is None, r
    assert r["risk_level"] == "未知", r
    assert r["breakdown"] == {}, r


def test_pure_score_bounds() -> None:
    zero = compute_risk_score({"pure_score": 0})
    assert zero["breakdown"]["pure_score"] == 0, zero
    assert zero["risk_score"] == 0, zero
    assert zero["risk_level"] == "低风险", zero

    full = compute_risk_score({"pure_score": 100})
    assert full["breakdown"]["pure_score"] == 50, full
    assert full["risk_score"] == 50, full
    assert full["risk_level"] == "中风险", full


def main() -> int:
    tests = [
        test_pure_score_clean_is_low_risk,
        test_pure_score_dirty_contributes_42,
        test_broadcast_from_multi_native,
        test_ip_type_datacenter_is_not_broadcast,
        test_dns_leak_never_scored,
        test_dnsbl_veto_at_least_90,
        test_empty_dict_unknown,
        test_non_dict_does_not_raise,
        test_broadcast_from_ip_src_or_native,
        test_remaining_weights_and_cap,
        test_proxy_vpn_needs_two_source_agreement,
        test_placeholders_skipped,
        test_pure_score_bounds,
    ]
    failed = 0
    print("compute_risk_score")
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
