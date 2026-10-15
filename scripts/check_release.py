"""Check tracked publication contents without reading ignored private files."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_DIRS = {".venv", "venv", "history", "exports", "work", "__pycache__", ".pytest_cache"}
TOKEN_PATTERNS = [
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
]


def main():
    result = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True)
    paths = [Path(name) for name in result.stdout.decode("utf-8").split("\0") if name]
    if not paths:
        print("FAIL: no tracked files; stage the reviewed source snapshot first.")
        return 1
    issues = []
    for path in paths:
        if (PRIVATE_DIRS.intersection(path.parts) or path.name == "config.yaml"
                or path.name.startswith(".env") or path.suffix == ".log"):
            issues.append(f"private runtime path tracked: {path.as_posix()}")
        data = (ROOT / path).read_bytes()
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".ico", ".webp"}:
            continue
        text = data.decode("utf-8-sig", errors="replace")
        for number, line in enumerate(text.splitlines(), 1):
            if any(pattern.search(line) for pattern in TOKEN_PATTERNS):
                # Never echo matched content: only filename and line number.
                issues.append(f"credential-like content: {path.as_posix()}:{number}")
        if path.suffix == ".md":
            for link in re.findall(r"\]\(([^)]+)\)", text):
                if re.match(r"^[a-z]+:", link) or link.startswith("#"):
                    continue
                target = link.split("#", 1)[0]
                if target and not (ROOT / path.parent / target).exists():
                    issues.append(f"broken local link: {path.as_posix()} -> {target}")
    vendor = ROOT / "static" / "vendor"
    manifest = json.loads((vendor / "manifest.json").read_text(encoding="utf-8-sig"))
    for entry in manifest:
        data = (vendor / entry["path"]).read_bytes()
        if len(data) != entry["bytes"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
            issues.append(f"vendor checksum mismatch: {entry['path']}")
    for required in ("LICENSE", "LICENSES/GPL-3.0.txt", "THIRD_PARTY_NOTICES.md", "README.md",
                     "README_EN.md", "SECURITY.md", ".github/workflows/tests.yml",
                     "start.cmd", "一键检测当前订阅.cmd", "requirements-cli.txt", "scripts/launch_cli.py"):
        if Path(required) not in paths:
            issues.append(f"required publication file missing: {required}")
    if issues:
        for issue in issues:
            print(f"FAIL: {issue}")
        return 1
    print(f"PASS: {len(paths)} tracked files; runtime path exclusions, token patterns, local links, licenses and vendor checksums checked.")
    print("This bounded check is not a guarantee that arbitrary sensitive content is absent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
