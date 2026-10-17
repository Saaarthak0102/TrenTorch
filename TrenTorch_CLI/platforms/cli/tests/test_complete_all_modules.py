"""Tests for complete_all_modules stop-at-first-unstarted-module behavior (issue #501)."""

from io import StringIO

import pytest
from rich.console import Console

import platforms.cli.processes.module_workflow.workflow as workflow_module
from platforms.cli.core.config import CLIConfig
from platforms.cli.processes.module_workflow.workflow import ModuleWorkflowCommand

# Full 20-module mapping matching the real repo's discovery order.
_FULL_MAPPING = {f"{i:02d}": f"{i:02d}_mod{i:02d}" for i in range(1, 21)}


@pytest.fixture
def workflow(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TREN_DEV_VERIFY_SOLUTION", raising=False)
    monkeypatch.setattr(workflow_module, "get_module_mapping", lambda: _FULL_MAPPING.copy())
    cmd = ModuleWorkflowCommand(CLIConfig.from_project_root(tmp_path))
    cmd.console = Console(file=StringIO(), width=200, no_color=True)
    # Seed empty progress
    cmd.save_progress_data({"started_modules": [], "completed_modules": []})
    return cmd


def _create_notebook(workflow, module_num: str):
    """Create a fake notebook for the given module number."""
    module_name = _FULL_MAPPING[module_num]
    short_name = module_name.split("_", 1)[1]
    module_dir = workflow.config.project_root / "data" / "modules" / module_name
    module_dir.mkdir(parents=True, exist_ok=True)
    (module_dir / f"{short_name}.ipynb").write_text("{}", encoding="utf-8")


def _stub_quiet(monkeypatch, *, fail_on=None):
    """Stub _complete_module_quiet to return 0 (or 1 for modules in fail_on)."""
    fail_set = set(fail_on or [])

    def _fake(self, module_num, module_name, skip_tests, skip_export):
        if module_num in fail_set:
            return 1
        # Record completion in progress (mirrors the real method)
        self.update_progress(module_num, module_name)
        return 0

    monkeypatch.setattr(ModuleWorkflowCommand, "_complete_module_quiet", _fake)


# ---------------------------------------------------------------------------
# Case 1: Nothing started -- no notebooks at all
# ---------------------------------------------------------------------------


def test_nothing_started_returns_1_and_says_no_modules_to_complete(workflow, monkeypatch):
    _stub_quiet(monkeypatch)

    rc = workflow.complete_all_modules(skip_tests=True, skip_export=True)
    output = workflow.console.file.getvalue()

    assert rc == 1
    assert "No modules to complete" in output
    assert "tren module start 01" in output
    assert "All modules completed" not in output
    assert not workflow.is_module_completed("01")


# ---------------------------------------------------------------------------
# Case 2: Notebooks for 01 and 03 only → completes 01, stops at 02,
#          names 03 as unreached
# ---------------------------------------------------------------------------


def test_gap_completes_up_to_gap_and_names_unreached(workflow, monkeypatch):
    _create_notebook(workflow, "01")
    _create_notebook(workflow, "03")
    _stub_quiet(monkeypatch)

    rc = workflow.complete_all_modules(skip_tests=True, skip_export=True)
    output = workflow.console.file.getvalue()

    assert rc == 0
    progress = workflow.get_progress_data()
    assert "01" in progress["completed_modules"]
    assert "03" not in progress["completed_modules"]
    assert "Stopped at module 02" in output
    assert "03" in output and "Not reached because of the gap" in output
    assert "All modules completed" not in output


# ---------------------------------------------------------------------------
# Case 3: Notebooks 01-03, module 02 fails → 03 never attempted
# ---------------------------------------------------------------------------


def test_failure_at_module_02_stops_and_does_not_attempt_03(workflow, monkeypatch):
    _create_notebook(workflow, "01")
    _create_notebook(workflow, "02")
    _create_notebook(workflow, "03")
    _stub_quiet(monkeypatch, fail_on={"02"})

    rc = workflow.complete_all_modules(skip_tests=True, skip_export=True)
    output = workflow.console.file.getvalue()

    assert rc == 1
    progress = workflow.get_progress_data()
    assert "01" in progress["completed_modules"]
    assert "02" not in progress["completed_modules"]
    assert "03" not in progress["completed_modules"]
    assert "Failed at module 02" in output


# ---------------------------------------------------------------------------
# Case 4: All 20 notebooks present → all complete, success panel
# ---------------------------------------------------------------------------


def test_all_notebooks_present_completes_all(workflow, monkeypatch):
    for num in _FULL_MAPPING:
        _create_notebook(workflow, num)
    _stub_quiet(monkeypatch)

    rc = workflow.complete_all_modules(skip_tests=True, skip_export=True)
    output = workflow.console.file.getvalue()

    assert rc == 0
    progress = workflow.get_progress_data()
    assert len(progress["completed_modules"]) == 20
    assert "All modules completed!" in output


# ---------------------------------------------------------------------------
# Case 5: 01 and 02 present, 03 missing, 04 present → completes 01+02,
#          stops at 03, names 04 as unreached
# ---------------------------------------------------------------------------


def test_stop_in_middle_names_later_notebooks(workflow, monkeypatch):
    _create_notebook(workflow, "01")
    _create_notebook(workflow, "02")
    # 03 missing
    _create_notebook(workflow, "04")
    _stub_quiet(monkeypatch)

    rc = workflow.complete_all_modules(skip_tests=True, skip_export=True)
    output = workflow.console.file.getvalue()

    assert rc == 0
    progress = workflow.get_progress_data()
    assert "01" in progress["completed_modules"]
    assert "02" in progress["completed_modules"]
    assert "03" not in progress["completed_modules"]
    assert "04" not in progress["completed_modules"]
    assert "Stopped at module 03" in output
    assert "04" in output and "Not reached because of the gap" in output
    assert "Progress Saved" in output
    assert "All modules completed" not in output
