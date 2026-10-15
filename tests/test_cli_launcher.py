"""The downloadable entry matches the user's direct-detection shortcut."""
from pathlib import Path
from types import SimpleNamespace

from scripts.launch_cli import cli_python, main


def environment(root):
    executable = cli_python(root)
    executable.parent.mkdir(parents=True)
    executable.touch()


def test_existing_environment_runs_direct_check_with_unlock(tmp_path):
    environment(tmp_path)
    calls = []
    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0)
    assert main([], root=tmp_path, runner=run) == 0
    command, options = calls[-1]
    assert command == [str(cli_python(tmp_path)), str(tmp_path / "one_click_check.py"), "--unlock"]
    assert options["cwd"] == tmp_path
    assert not any("web.py" in argument for args, _ in calls for argument in args)


def test_first_run_builds_environment_and_installs_only_cli_dependencies(tmp_path):
    created, calls = [], []
    class Builder:
        def create(self, target):
            created.append(target)
            environment(tmp_path)
    codes = iter([1, 0, 0])
    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=next(codes))
    assert main(["--serial"], root=tmp_path, runner=run, builder=Builder()) == 0
    assert created == [tmp_path / ".venv"]
    assert calls[1][-1] == str(tmp_path / "requirements-cli.txt")
    assert calls[-1][-2:] == ["--unlock", "--serial"]


def test_failed_install_never_starts_detection(tmp_path):
    environment(tmp_path)
    calls = []
    codes = iter([1, 23])
    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=next(codes))
    assert main([], root=tmp_path, runner=run) == 23
    assert len(calls) == 2
    assert not any(argument.endswith("one_click_check.py") for args in calls for argument in args)


def test_help_does_not_add_detection_options(tmp_path):
    environment(tmp_path)
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0)
    assert main(["--help"], root=tmp_path, runner=run) == 0
    assert calls[-1][-1] == "--help" and "--unlock" not in calls[-1]


def test_detection_exit_status_is_preserved(tmp_path):
    environment(tmp_path)
    codes = iter([0, 2])
    assert main([], root=tmp_path, runner=lambda *a, **k: SimpleNamespace(returncode=next(codes))) == 2


def test_named_entry_is_portable_and_forwards_arguments():
    root = Path(__file__).resolve().parents[1]
    entry = (root / "一键检测当前订阅.cmd").read_text(encoding="utf-8")
    assert '%~dp0start.cmd' in entry and '%*' in entry
    assert "D:" not in entry
