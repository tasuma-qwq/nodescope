"""Explicit synthetic-data UI preview. Never connects to Clash or probe sites."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if __name__ == "__main__":
    import uvicorn
    import routers.api as api
    import routers.views as views
    from tests.fakes import DemoChecker, DemoController
    from web import app

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8081)
    args = parser.parse_args()
    api.state.checker = DemoChecker()
    api.ClashController = DemoController
    api._load_verge_runtime_config = lambda: None
    views.templates.env.globals["demo_notice"] = True
    print("DEMO ONLY: synthetic data; no Clash connection or real service probes.")
    print("Paste examples/demo.yaml.example to try the workflow.")
    uvicorn.run(app, host="127.0.0.1", port=args.port)
