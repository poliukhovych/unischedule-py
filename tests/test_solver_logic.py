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

