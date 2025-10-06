import uuid
import pytest
from fastapi import status
from fastapi.testclient import TestClient
from src.main import app
from src.core.enums import JobStatus
from src.schemas.response import JobResult, Stats


def test_health_check():
    with TestClient(app) as client:
        response = client.get("/v1/health")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"status": "ok"}


def test_solve_endpoint_enqueues_job(mocker):
    fake_job_id = str(uuid.uuid4())
    mocker.patch('src.core.job_manager.JobManager.start_solve_job', return_value=fake_job_id)

    minimal_payload = {
        "instance": {
            "teachers": [], "groups": [], "rooms": [],
            "courses": [], "timeslots": [],
            "policy": {"soft_weights": {}}
        },
        "params": {"timeLimitSec": 5}
    }

    with TestClient(app) as client:
        response = client.post("/v1/solve", json=minimal_payload)

    assert response.status_code == status.HTTP_202_ACCEPTED
    response_data = response.json()
    assert response_data["jobId"] == fake_job_id
    assert response_data["status"] == "queued"


@pytest.mark.parametrize(
    "job_status, expected_status_code, expected_detail",
    [
        (JobStatus.QUEUED, status.HTTP_202_ACCEPTED, "Job is being processed."),
        (JobStatus.RUNNING, status.HTTP_202_ACCEPTED, "Job is being processed."),
        (JobStatus.ERROR, status.HTTP_500_INTERNAL_SERVER_ERROR, ["Something went wrong"]),
    ],
    ids=["queued_job", "running_job", "failed_job"]
)
def test_get_result_for_unfinished_or_failed_jobs(mocker, job_status, expected_status_code, expected_detail):
    fake_job_id = str(uuid.uuid4())
    mocker.patch('src.core.job_manager.JobManager.get_job_status', return_value=job_status)
    if job_status == JobStatus.ERROR:
        mocker.patch('src.core.job_manager.JobManager.get_job_result',
                     return_value=JobResult(assignments=[], objective=-1, status="ERROR",
                                            violations=["Something went wrong"],
                                            stats=Stats(solve_time_sec=0, status="WORKER_ERROR")))

    with TestClient(app) as client:
        response = client.get(f"/v1/jobs/{fake_job_id}/result")

    assert response.status_code == expected_status_code
    assert response.json()["detail"] == expected_detail


def test_get_result_for_solved_job(mocker):
    fake_job_id = str(uuid.uuid4())
    mocker.patch('src.core.job_manager.JobManager.get_job_status', return_value=JobStatus.SOLVED)

    mock_result = JobResult(
        assignments=[
            {"courseId": "c1", "teacherId": "t1", "roomId": "r1", "timeslot": "mon.all.1", "groupIds": ["g1"]}],
        objective=0,
        status="solved",
        violations=[],
        stats=Stats(solve_time_sec=1.23, status="OPTIMAL")
    )
    mocker.patch('src.core.job_manager.JobManager.get_job_result', return_value=mock_result)

    with TestClient(app) as client:
        response = client.get(f"/v1/jobs/{fake_job_id}/result")

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == mock_result.model_dump()


def test_get_result_for_nonexistent_job(mocker):
    fake_job_id = str(uuid.uuid4())
    mocker.patch('src.core.job_manager.JobManager.get_job_status', return_value=None)

    with TestClient(app) as client:
        response = client.get(f"/v1/jobs/{fake_job_id}/result")

    assert response.status_code == status.HTTP_404_NOT_FOUND

