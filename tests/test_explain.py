import json
from pathlib import Path
from src.solver import ScheduleSolver
from src.schemas import request as schemas_request


def load_test_data(filename: str) -> dict:
    path = Path(__file__).parent.parent / "examples" / filename
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def test_explain_finds_clear_conflict():
    explain_data = load_test_data("explain_input.json")
    instance_data = schemas_request.Instance.model_validate(explain_data["instance"])
    params_data = schemas_request.Params.model_validate(explain_data["params"])
    focus_assignment = schemas_request.FocusAssignment.model_validate(explain_data["focus_assignment"])
    base_assignments = [schemas_request.BaseAssignment.model_validate(item) for item in explain_data["base"]]

    solver = ScheduleSolver(instance=instance_data, params=params_data)
    response = solver.explain_conflict(
        instance_data=instance_data,
        focus=focus_assignment,
        base=base_assignments
    )

    assert len(response.conflicts) > 0
    assert "Conflict: Room 'r300_lec' is already taken by course 'c_history' at mon.all.3." in response.conflicts
    assert "Teacher 'Морозов В.' is not available at mon.all.3." in response.conflicts


def test_explain_finds_no_conflict():
    explain_data = load_test_data("explain_input.json")
    instance_data = schemas_request.Instance.model_validate(explain_data["instance"])
    params_data = schemas_request.Params.model_validate(explain_data["params"])

    focus_assignment = schemas_request.FocusAssignment(
        courseId="c_physics",
        roomId="r101",
        timeslot="thu.all.3"
    )
    base_assignments = [schemas_request.BaseAssignment.model_validate(item) for item in explain_data["base"]]

    solver = ScheduleSolver(instance=instance_data, params=params_data)
    response = solver.explain_conflict(
        instance_data=instance_data,
        focus=focus_assignment,
        base=base_assignments
    )

    assert len(response.conflicts) == 0, f"Expected no conflicts, but found: {response.conflicts}"

