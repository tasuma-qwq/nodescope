"""HTTP/privacy regressions; all node data is synthetic and stays in temp dirs."""
import asyncio
import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from core.privacy import public_data
from core.report import build_report
from schemas import StartRequest, RecheckRequest
from web import app
import routers.api as api

SENTINEL = "TEST-ONLY-SECRET-DO-NOT-EXPOSE"
SUBSCRIPTION = """proxies:
  - name: Demo node
    type: ss
    server: example.invalid
    port: 443
    cipher: aes-128-gcm
    password: TEST-ONLY-SECRET-DO-NOT-EXPOSE
proxy-groups:
  - name: Proxy
    type: select
    proxies: [Demo node, DIRECT]
"""


@pytest.fixture
def client(monkeypatch, tmp_path):
    node = {"id": 0, "name": "Private node", "original_name": "Demo node",
            "ip": "192.0.2.42", "pure_score": "8%", "risk_score": 4,
            "status": "✅", "proxy_config": {"name": "Demo node", "type": "ss",
                "server": "example.invalid", "password": SENTINEL}}
    fake_state = SimpleNamespace(nodes=[node], is_running=False, is_rechecking=False,
        task=None, events=[{"type": "progress", "node": node}],
        original_yaml=api.yaml.load(SUBSCRIPTION), task_id="test-only")
    monkeypatch.setattr(api, "state", fake_state)
    monkeypatch.setattr(api, "EXPORTS_DIR", str(tmp_path))
    # Do not enter the production lifespan: this test has its own state/checker.
    return TestClient(app, base_url="http://127.0.0.1:8080")


@pytest.mark.parametrize("headers", [
    {"Host": "evil.example"}, {"Host": "127.0.0.1.evil.example"},
    {"Origin": "https://evil.example"}, {"Origin": "null"},
    {"Origin": "http://localhost:8080"},
    {"Origin": "http://127.0.0.1:9000"},
    {"Origin": "http://127.0.0.1:8080/forged-path"},
    {"Sec-Fetch-Site": "cross-site"}, {"Sec-Fetch-Site": "same-site"},
    {"Host": "[broken"},
])
def test_reject_cross_site_and_rebinding(client, headers):
    assert client.get("/api/nodes", headers=headers).status_code == 403
    assert client.post("/api/validate", json={"yaml_content": SUBSCRIPTION}, headers=headers).status_code == 403


def test_same_origin_and_native_client_allowed(client):
    for headers in ({}, {"Origin": "http://127.0.0.1:8080", "Sec-Fetch-Site": "same-origin"}):
        response = client.post("/api/validate", json={"yaml_content": SUBSCRIPTION}, headers=headers)
        assert response.status_code == 200
        assert response.json()["node_count"] == 1
        assert "no-store" in response.headers["cache-control"]
        assert response.headers["x-frame-options"] == "DENY"


def test_ui_has_local_assets_and_brand(client):
    from html.parser import HTMLParser

    class Assets(HTMLParser):
        urls = []
        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == "script" and attrs.get("src"):
                self.urls.append(attrs["src"])
            if tag == "link" and attrs.get("href"):
                self.urls.append(attrs["href"])

    response = client.get("/")
    assert response.status_code == 200
    assert "NodeScope" in response.text and "匿名报告" in response.text
    assets = Assets()
    assets.feed(response.text)
    assert assets.urls
    for url in assets.urls:
        assert url.startswith("/static/")
        resource = client.get(url)
        assert resource.status_code == 200, url
        assert len(resource.content) > 100


def test_public_responses_hide_proxy_credentials_but_export_keeps_them(client):
    for path in ("/api/nodes", "/api/progress"):
        response = client.get(path)
        assert response.status_code == 200
        assert SENTINEL not in response.text and "proxy_config" not in response.text
    response = client.put("/api/nodes/0", json={"name": "New name"})
    assert response.status_code == 200 and SENTINEL not in response.text
    exported = client.post("/api/export", json={"node_ids": [0]})
    assert exported.status_code == 200
    assert SENTINEL in exported.json()["yaml"]
    stable = client.get(exported.json()["subscribe_url"])
    assert stable.status_code == 200 and SENTINEL in stable.text
    assert "attachment" in stable.headers["content-disposition"]


def test_report_is_anonymous_and_does_not_change_original_nodes(client):
    before = json.dumps(api.state.nodes)
    response = client.get("/api/report")
    assert response.status_code == 200
    for sensitive in (SENTINEL, "Private node", "Demo node", "192.0.2.42", "example.invalid", "proxy_config"):
        assert sensitive not in response.text
    report = response.json()
    assert report["nodes"][0]["node"] == "Node 001"
    assert report["nodes"][0]["risk_score"] == 4
    assert report["summary"]["measured"] == 1
    assert before == json.dumps(api.state.nodes)


@pytest.mark.parametrize("content", ["", "[]", "hello", "proxies: example", "proxies: [null]",
    "proxies: [{name: 2}]", "proxies: [{name: ''}]", "proxies: [{name: A}, {name: A}]",
    "proxies: [{name: A}]\nproxy-groups: invalid", "proxies: [", "proxies: [{name: A}]\nproxy-groups: [null]"])
def test_malformed_subscription_is_rejected_without_starting_a_task(client, content):
    for path in ("/api/validate", "/api/start"):
        response = client.post(path, json={"yaml_content": content})
        assert response.status_code == 400
    assert api.state.is_running is False and api.state.task is None


def test_stop_does_not_release_busy_guard_until_restore_finishes(monkeypatch):
    async def scenario():
        release = asyncio.Event()
        task = asyncio.create_task(release.wait())
        fake = SimpleNamespace(is_running=True, is_rechecking=False, task=task, events=[])
        monkeypatch.setattr(api, "state", fake)
        try:
            await api.stop_check()
            assert fake.is_running is False and api._busy()
            with pytest.raises(api.HTTPException) as caught:
                await api.start_check(StartRequest(yaml_content=SUBSCRIPTION))
            assert caught.value.status_code == 409
            with pytest.raises(api.HTTPException) as caught:
                await api.recheck_node(0, RecheckRequest())
            assert caught.value.status_code == 409
        finally:
            release.set()
            await task
        assert not api._busy()
    asyncio.run(scenario())


def test_recheck_is_exclusive_and_guard_is_released_on_failure(monkeypatch):
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        fake = SimpleNamespace(is_running=False, is_rechecking=False, task=None)
        monkeypatch.setattr(api, "state", fake)
        async def pending(*args):
            entered.set()
            await release.wait()
            raise RuntimeError("test failure")
        monkeypatch.setattr(api, "_recheck_node", pending)
        task = asyncio.create_task(api.recheck_node(0, RecheckRequest()))
        await entered.wait()
        try:
            with pytest.raises(api.HTTPException) as caught:
                await api.recheck_node(0, RecheckRequest())
            assert caught.value.status_code == 409
        finally:
            release.set()
            with pytest.raises(RuntimeError):
                await task
        assert not api._busy()
    asyncio.run(scenario())


def test_report_unknown_and_nonfinite_values_are_not_clean_scores():
    report = build_report([{"pure_score": "?", "risk_score": math.nan, "delay_ms": math.inf,
        "status": "pending", "error": SENTINEL,
        "unlock": {"claude": {"status": "unknown", "note": SENTINEL}, "extra": SENTINEL}}])
    row = report["nodes"][0]
    assert row["pollution_percent"] is None and row["risk_score"] is None
    assert row["delay_ms"] is None and row["service_signals"] == {"claude": "unknown"}
    assert SENTINEL not in json.dumps(report, allow_nan=False)


def test_recursive_filter_never_mutates_server_state():
    original = {"node": {"proxy_config": {"password": SENTINEL}, "ip": "192.0.2.1"}}
    assert public_data(original) == {"node": {"ip": "192.0.2.1"}}
    assert original["node"]["proxy_config"]["password"] == SENTINEL


@pytest.mark.parametrize("config", [{"skip_keywords_str": []}, {"fast_mode": "false"}, {"source": "unknown"}])
def test_invalid_options_do_not_leave_task_running(client, config):
    response = client.post("/api/start", json={"yaml_content": SUBSCRIPTION, "config": config})
    assert response.status_code == 400
    assert api.state.is_running is False and api.state.task is None


def test_validation_error_does_not_echo_submitted_secrets(client):
    response = client.post("/api/start", json={"yaml_content": SUBSCRIPTION, "config": SENTINEL})
    assert response.status_code == 422 and SENTINEL not in response.text


def test_failed_source_is_not_presented_as_measured():
    node = api._make_node_data(0, "test", {"password": SENTINEL}, {"ip": "❓", "source": "failed"})
    assert node["risk_score"] is None
    assert node["name"].endswith("【检测失败】")
    assert build_report([node])["summary"]["failed"] == 1


def test_local_history_auto_commit_defaults_off(tmp_path, monkeypatch):
    import core.history as history
    monkeypatch.setattr(history, "_snapshot_abs_dir", lambda: tmp_path)
    def forbidden(*args, **kwargs):
        pytest.fail("default history path must not invoke git")
    monkeypatch.setattr(history, "git_commit_snapshot", forbidden)
    result = history.save_with_git([{"name": "test", "proxy_config": {"password": SENTINEL}}])
    assert result["path"] and result["committed"] is False
    assert SENTINEL not in next(tmp_path.glob("*.json")).read_text(encoding="utf-8")


def test_vendor_assets_match_manifest():
    import hashlib
    root = Path(__file__).resolve().parents[1] / "static" / "vendor"
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8-sig"))
    for entry in manifest:
        data = (root / entry["path"]).read_bytes()
        assert len(data) == entry["bytes"]
        assert hashlib.sha256(data).hexdigest() == entry["sha256"]
