import importlib.util
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "setup_wizard_fast_start", ROOT / "scripts" / "setup_wizard.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_requirements_satisfied_uses_local_metadata(tmp_path):
    module = _load()
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("Demo>=1,<2\n", encoding="utf-8")

    with patch.object(module.metadata, "version", return_value="1.5"):
        assert module._requirements_satisfied(str(requirements)) is True
    with patch.object(module.metadata, "version", return_value="2.5"):
        assert module._requirements_satisfied(str(requirements)) is False


def test_pip_is_not_started_when_dependencies_are_ready(tmp_path):
    module = _load()
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("Demo>=1\n", encoding="utf-8")

    with patch.object(module, "_requirements_satisfied", return_value=True), patch.object(
        module.subprocess, "run"
    ) as run:
        assert module._pip_install(str(requirements)) is True
        run.assert_not_called()


def test_one_click_mode_never_waits_for_optional_console_input():
    module = _load()
    assert module._decide_optional({}, []) is False
    assert module._decide_optional({"optional": True}, []) is True
