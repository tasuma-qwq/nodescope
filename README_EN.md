# NodeScope

[简体中文](README.md) · [References](docs/references.md) · [Contributing](CONTRIBUTING.md)

A local Clash / Mihomo node inspection tool: compare IP reputation, risk signals, latency and service endpoint responses; export annotated subscriptions or anonymous JSON reports.

Derived from [tombcato/clash-ip-checker](https://github.com/tombcato/clash-ip-checker). Adds conservative probe verdicts, local access protections, credential filtering, anonymous reports and automated regression checks.

## Quick start

Python 3.10+ and a running Clash / Mihomo controller are required.

```bash
git clone https://github.com/tasuma-qwq/nodescope.git
cd nodescope
python -m venv .venv
```

Windows users can double-click `start.cmd`, or run:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe web.py
```

Linux / macOS:

```bash
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python web.py
```

Open [http://127.0.0.1:8080](http://127.0.0.1:8080), paste a YAML subscription and enter your controller address and secret. Initial installation needs Internet access; UI resources are bundled locally. Fast mode does not need browser installation. Browser mode additionally needs `python -m playwright install chromium` using the virtual environment interpreter.

Detection can switch nodes and reload controller configuration, interrupting active connections. Avoid important network activity while checking.

## Features

- Ping0 / IPPure fallback, optional multi-source reputation and DNSBL checks.
- Listener-based parallel checks with configuration / selector restoration and serial fallback.
- Numeric annotations, local history and trends, optional IPv6 and service probes.
- `GET /api/report`: anonymous metric-only JSON, excluding IPs, node names, credentials and raw messages.
- YAML export and stable subscription refresh at `/api/export/subscribe`.
- Loopback / same-origin checks; ordinary node responses omit private proxy configurations.

The Windows-specific `one_click_check.py` reads the active Clash Verge subscription. Options: `--unlock`, `--serial`, `--no-history`, `--trend <keyword>`, `--clean-exports`. Its local subscription server uses `127.0.0.1:57520`; other copies are not terminated automatically. Services must remain running for subscription refresh. The legacy CLI remains available via `config.yaml.example` and `clash_automator.py`.

## Interpretation and privacy

Lower pollution / risk is better. Missing data remains unknown. Challenges, throttling, server errors and unrecognized pages are not unlock evidence. Endpoint responses and region codes do not establish account eligibility, supported physical location, login or model access. GeoIP agreement does not prove residential ownership.

Configuration and history remain local. Detection queries external endpoints; optional API keys go to the respective providers. **Exported YAML contains proxy credentials and must not be shared.** Use the anonymous report instead.

Configuration, `.env`, `exports/`, `history/`, logs and environments are ignored. History auto-commits are disabled by default. This repository starts from a source-only snapshot and excludes private operational history and original screenshots. Do not expose it publicly.

## Development

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
python scripts/check_release.py
```

Tests use synthetic data, fake controllers and temporary directories. CI targets Windows / Linux and Python 3.10 / 3.12. See [validation scope](docs/validation.md).

For an explicitly labeled synthetic preview, run `python scripts/preview_demo.py`, open `http://127.0.0.1:8081` and paste `examples/demo.yaml.example`. This mode does not connect to Clash or external probe sites.

## License

NodeScope is an **AGPL-3.0 combined work**. Original GPL-3.0 portions from `tombcato/clash-ip-checker` retain their license, preserved in [LICENSES/GPL-3.0.txt](LICENSES/GPL-3.0.txt). Existing probes reference AGPL-3.0 projects `lmc999/RegionRestrictionCheck` and `xykt/IPQuality`. See [LICENSE](LICENSE) and [notices](THIRD_PARTY_NOTICES.md). Bundled frontend libraries retain their MIT licenses.

