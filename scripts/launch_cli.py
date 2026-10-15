"""Prepare an isolated CLI environment, then check the active subscription."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parents[1]


def cli_python(root: Path) -> Path:
    return root / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def main(args=None, *, root=ROOT, runner=subprocess.run, builder=None):
    args = list(sys.argv[1:] if args is None else args)
    if sys.version_info < (3, 10):
        print("需要 Python 3.10 或更新版本，请安装后重新双击入口。")
        return 1
    python = cli_python(root)
    try:
        if not python.is_file():
            print("首次运行：正在创建项目专用 Python 环境……", flush=True)
            (builder or venv.EnvBuilder(with_pip=True)).create(root / ".venv")
        probe = runner(
            [str(python), "-c", "import one_click_check; from core.local_http import LocalSubscriptionHandler"],
            cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if probe.returncode:
            print("正在安装检测所需依赖（首次需要联网，不安装浏览器）……", flush=True)
            install = runner(
                [str(python), "-m", "pip", "install", "-r", str(root / "requirements-cli.txt")],
                cwd=root,
            )
            if install.returncode:
                print("依赖安装失败，请检查网络后重新双击入口；不会开始检测。")
                return install.returncode
        if "--unlock" not in args and not any(arg in args for arg in ("--help", "-h")):
            args.insert(0, "--unlock")
        print("NodeScope：直接检测 Clash Verge 当前订阅，无需打开网页。", flush=True)
        result = runner([str(python), str(root / "one_click_check.py"), *args], cwd=root)
        print(f"\n结果目录：{root / 'exports'}", flush=True)
        return result.returncode
    except (OSError, subprocess.SubprocessError) as error:
        print(f"启动失败：{type(error).__name__}。请检查 Python、项目目录权限和网络。")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
