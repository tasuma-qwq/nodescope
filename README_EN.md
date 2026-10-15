# NodeScope

[简体中文](README.md) · [Behavior](docs/behavior.md) · [Attribution](THIRD_PARTY_NOTICES.md)

**Download / clone → double-click `start.cmd` → inspect the active Clash Verge subscription.**

The portable launcher reads the local subscription, controller address and secret automatically. No website, pasted YAML or manually entered controller key is needed. Derived from [tombcato/clash-ip-checker](https://github.com/tombcato/clash-ip-checker).

## Windows quick start

Requires **Python 3.10+**, **Clash Verge Rev with its default data directory**, and External Controller enabled. Portable installations, custom data directories and automatic discovery for other clients are not supported.

1. Open Clash Verge Rev and select the subscription to inspect.
2. Download **Code → Download ZIP** and extract, or `git clone https://github.com/tasuma-qwq/nodescope.git`.
3. Double-click **`start.cmd`** or **`一键检测当前订阅.cmd`**. Both are equivalent.
4. On first use, the launcher creates a project-local `.venv` and installs CLI dependencies over the Internet. No browser installation or Web UI is needed.
5. Detection starts automatically with service probes (`--unlock`) enabled. The window stays open afterward; exports are stored in `exports/`.

On first completion, confirm the checked subscription import in Clash Verge. On subsequent runs, click **Update** on that card to refresh scores and traffic information.

The local subscription service uses `127.0.0.1:57520` and must remain running for refresh. A conflicting server is not terminated; the tool falls back to temporary import. Moving the project can require manually retiring the old server / card.

Detection can switch nodes and reload configuration, interrupting connections. Avoid important network activity. Normal completion attempts to restore configuration and selector choices; forcibly terminating the process can prevent restoration.

## Results

- Ping0 / IPPure reputation with fallback, optional multi-source and DNSBL signals.
- Listener-based parallel checking with serial fallback.
- Numeric node annotations, latency, region summaries, usage suggestions and changes since the previous run.
- Local history / trends, with automatic Git commits disabled.
- ChatGPT, Gemini, Claude, Netflix and YouTube endpoint signals. Challenges, throttling and unrecognized pages remain unknown.

Lower pollution / risk is better. Unknown is not zero. GeoIP consistency is not proof of residential ownership. Endpoint / region signals do not establish account eligibility, login or model access.

## Optional commands

```powershell
.\start.cmd --help
.\start.cmd --serial
.\start.cmd --no-history
.\start.cmd --trend keyword
```

These prepare the environment automatically and add `--unlock` by default. For direct Python use:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-cli.txt
.\.venv\Scripts\python.exe one_click_check.py --unlock
```

Omit `--unlock` on the direct Python command to skip service probes.

## Privacy and development

Exported YAML contains proxy credentials; do not share it. Local history can contain node names and exit IPs. Configuration, `.env`, exports, history, logs and environments are ignored. Private operational Git history was not included.

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
python scripts/check_release.py
```

CI covers Windows / Linux and Python 3.10 / 3.12. Actual one-click detection targets Windows Clash Verge Rev. Tests do not connect to the active controller. See [validation](docs/validation.md).

The previous Web UI / anonymous reports remain optional advanced tools: install `requirements.txt` and run `web.py`. The downloadable default entry does not use them.

## License

AGPL-3.0 combined work; original GPL-3.0 portions retain their license in [LICENSES/GPL-3.0.txt](LICENSES/GPL-3.0.txt). Existing probes reference AGPL-3.0 projects RegionRestrictionCheck and IPQuality. See [LICENSE](LICENSE) and [notices](THIRD_PARTY_NOTICES.md).

