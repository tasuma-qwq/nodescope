"""Offline unit tests for DNSBL hit classification (no real DNS queries)."""
from __future__ import annotations

import asyncio
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.sources.dnsbl import DNSBLSource, _is_dnsbl_a_hit  # noqa: E402


class TestIsDnsblAHit(unittest.TestCase):
    def test_typical_listing_127_0_0_2(self):
        self.assertTrue(_is_dnsbl_a_hit("127.0.0.2"))

    def test_typical_listing_127_0_0_4(self):
        self.assertTrue(_is_dnsbl_a_hit("127.0.0.4"))

    def test_spamhaus_query_refused_254(self):
        self.assertFalse(_is_dnsbl_a_hit("127.255.255.254"))

    def test_spamhaus_blocked_range_1(self):
        self.assertFalse(_is_dnsbl_a_hit("127.255.255.1"))

    def test_public_resolver_not_a_hit(self):
        self.assertFalse(_is_dnsbl_a_hit("8.8.8.8"))

    def test_invalid_ip_string(self):
        self.assertFalse(_is_dnsbl_a_hit("not-an-ip"))

    def test_spamhaus_blocked_range_255(self):
        self.assertFalse(_is_dnsbl_a_hit("127.255.255.255"))

    def test_typical_listing_range(self):
        for last in range(2, 12):
            self.assertTrue(_is_dnsbl_a_hit(f"127.0.0.{last}"), f"127.0.0.{last}")

    def test_ipv6_not_a_hit(self):
        self.assertFalse(_is_dnsbl_a_hit("::1"))
        self.assertFalse(_is_dnsbl_a_hit("2001:db8::1"))


class TestDNSBLSourceCheckOffline(unittest.TestCase):
    def test_invalid_ip_returns_empty_hits(self):
        result = asyncio.run(DNSBLSource().check("not-an-ip"))
        self.assertEqual(result, {"hits": [], "reasons": {}})

    def test_empty_and_ipv6_return_empty_hits(self):
        src = DNSBLSource()
        self.assertEqual(asyncio.run(src.check("")), {"hits": [], "reasons": {}})
        self.assertEqual(asyncio.run(src.check("::1")), {"hits": [], "reasons": {}})
        self.assertEqual(asyncio.run(src.check("2001:db8::1")), {"hits": [], "reasons": {}})


if __name__ == "__main__":
    unittest.main()
