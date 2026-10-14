"""Exercise the actual HTTP workflow with a fake controller, including recheck."""
import json

from fastapi.testclient import TestClient

import routers.api as api
import web
from state import AppState
from tests.fakes import DEMO_YAML, DemoChecker, DemoController


def test_start_sse_report_recheck_export_and_refresh(monkeypatch, tmp_path):
    state = AppState()
    state.checker = DemoChecker()
    controllers = []
    def controller(*args):
        instance = DemoController()
        controllers.append(instance)
        return instance
    monkeypatch.setattr(api, "state", state)
    monkeypatch.setattr(web, "state", state)
    monkeypatch.setattr(api, "ClashController", controller)
    monkeypatch.setattr(api, "_load_verge_runtime_config", lambda: None)
    monkeypatch.setattr(api, "EXPORTS_DIR", str(tmp_path))
    config = {"parallel_check": False, "history_enabled": False}
    with TestClient(web.app, base_url="http://127.0.0.1:8080") as client:
        response = client.post("/api/start", json={"yaml_content": DEMO_YAML, "config": config})
        assert response.status_code == 200 and response.json()["total"] == 2
        stream = client.get("/api/progress")
        assert stream.status_code == 200
        events = [json.loads(line[6:]) for line in stream.text.splitlines() if line.startswith("data: ")]
        assert sum(event["type"] == "progress" for event in events) == 2
        assert events[-1]["type"] == "complete"
        assert "demo-only-not-a-real-proxy" not in stream.text
        assert not state.is_running
        assert controllers[-1].mode == "rule"
        report = client.get("/api/report").json()
        assert report["summary"]["measured"] == 2
        assert report["nodes"][0]["service_signals"] == {"claude": "unknown"}
        assert "192.0.2.42" not in json.dumps(report)
        rechecked = client.post("/api/nodes/0/recheck", json={"config": config})
        assert rechecked.status_code == 200
        assert "proxy_config" not in rechecked.json()["node"]
        assert controllers[-1].mode == "rule"
        assert controllers[-1].selections == {"GLOBAL": "Demo", "Demo": "Demo-B"}
        exported = client.post("/api/export", json={"node_ids": [0, 1]})
        assert exported.status_code == 200
        latest = client.get(exported.json()["subscribe_url"])
        assert latest.status_code == 200
        assert "demo-only-not-a-real-proxy" in latest.text
        assert "【8%" in latest.text
