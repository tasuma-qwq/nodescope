"""Real loopback HTTP tests with synthetic files and ephemeral ports."""
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
import one_click_check as cli


@pytest.mark.parametrize("stable", [False, True])
def test_subscription_servers_reject_cross_site_and_serve_native_clients(tmp_path, monkeypatch, stable):
    path = tmp_path / cli.STABLE_FILENAME
    path.write_bytes(b"proxies: []\n")
    monkeypatch.setattr(cli, "EXPORTS_DIR", tmp_path)
    if stable:
        server = cli.build_latest_server(port=0)
        port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()
    else:
        server, port, _ = cli.start_export_server(path)
    try:
        url = f"http://127.0.0.1:{port}/{path.name}"
        with urlopen(url, timeout=3) as response:
            assert response.read() == b"proxies: []\n"
            assert response.headers["Cache-Control"] == "no-store"
        for headers in ({"Host": "evil.example"}, {"Origin": "https://evil.example"},
                        {"Sec-Fetch-Site": "cross-site"}):
            with pytest.raises(HTTPError) as caught:
                urlopen(Request(url, headers=headers), timeout=3)
            assert caught.value.code == 403
    finally:
        server.shutdown()
        server.server_close()


def test_occupied_port_never_terminates_another_copy(monkeypatch):
    monkeypatch.setattr(cli, "_server_alive", lambda: False)
    monkeypatch.setattr(cli, "_port_occupied", lambda: True)
    monkeypatch.setattr(cli.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("must not spawn or kill another copy"))
    monkeypatch.setattr(cli.subprocess, "run", lambda *args, **kwargs: pytest.fail("must not enumerate or kill other processes"))
    assert cli.ensure_latest_server() is False
