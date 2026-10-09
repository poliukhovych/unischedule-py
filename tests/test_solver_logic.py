from src.solver import ScheduleSolver
from src.schemas import request as schemas_request

def test_prepare_data_mappings_for_subgroups():
    instance_data = schemas_request.Instance(
        teachers=[],
        groups=[
            schemas_request.Group(id="g_cs_1", name="Main Group", size=30),
            schemas_request.Group(id="g_cs_1a", name="Subgroup A", size=15, parentGroupId="g_cs_1"),
            schemas_request.Group(id="g_math_1", name="Another Group", size=20)
        ],
        rooms=[], courses=[], timeslots=[],
        policy=schemas_request.Policy(soft_weights=schemas_request.SoftWeights())
    )
    params_data = schemas_request.Params(timeLimitSec=1)

    solver = ScheduleSolver(instance=instance_data, params=params_data)

    expected_mapping = {
        "g_cs_1": "g_cs_1",
        "g_cs_1a": "g_cs_1",
        "g_math_1": "g_math_1"
    }
    assert solver.group_to_main_group == expected_mapping


def _solve(courses, timeslots, teacher_available=None):
    instance = schemas_request.Instance(
        teachers=[schemas_request.Teacher(id="t1", name="T", available=teacher_available or timeslots)],
        groups=[schemas_request.Group(id="g1", name="G", size=20)],
        rooms=[schemas_request.Room(id="r1", name="R", capacity=30)],
        courses=courses,
        timeslots=timeslots,
        policy=schemas_request.Policy(soft_weights=schemas_request.SoftWeights()),
    )
    return ScheduleSolver(instance=instance, params=schemas_request.Params(timeLimitSec=5)).solve()


def _course(cid, frequency):
    return schemas_request.Course(id=cid, name=cid, groupIds=["g1"], teacherId="t1",
                                  countPerWeek=1, frequency=frequency)


def test_weekly_slot_overlaps_odd_slot_of_same_pair():
    # mon.all.1 runs every week, so it clashes with mon.odd.1; the weekly course must move to mon.all.2
    result = _solve([_course("weekly", "weekly"), _course("odd", "odd")],
                    ["mon.all.1", "mon.odd.1", "mon.all.2"])
    placed = {a.courseId: a.timeslot for a in result.assignments}
    assert result.status == "solved"
    assert placed == {"weekly": "mon.all.2", "odd": "mon.odd.1"}


def test_odd_and_even_courses_share_a_pair():
    result = _solve([_course("odd", "odd"), _course("even", "even")], ["mon.odd.1", "mon.even.1"])
    assert result.status == "solved"
    assert {a.timeslot for a in result.assignments} == {"mon.odd.1", "mon.even.1"}


def test_all_week_availability_covers_odd_slots():
    result = _solve([_course("odd", "odd")], ["mon.all.1", "mon.odd.1"], teacher_available=["mon.all.1"])
    assert result.status == "solved"
    assert result.assignments[0].timeslot == "mon.odd.1"


def test_no_valid_slot_is_infeasible_not_timeout():
    result = _solve([_course("weekly", "weekly"), _course("weekly2", "weekly")], ["mon.all.1"])
    assert result.status == "infeasible"

