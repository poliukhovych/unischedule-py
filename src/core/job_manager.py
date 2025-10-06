import os
from typing import Optional
from redis import Redis
from rq import Queue
from rq.job import Job
from rq.exceptions import NoSuchJobError
from src.schemas import request as schemas_request
from src.schemas import response as schemas_response
from src.core.enums import JobStatus
from src.solver import run_solve_task

class JobManager:
    def __init__(self):
        self.redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.redis_conn = Redis.from_url(self.redis_url)
        self.queue = Queue("default", connection=self.redis_conn)
        print(f"JobManager initialized. Connecting to Redis at {self.redis_url}")

    def get_job_status(self, job_id: str) -> Optional[JobStatus]:
        try:
            job = Job.fetch(job_id, connection=self.redis_conn)
            rq_status_map = {
                'queued': JobStatus.QUEUED,
                'started': JobStatus.RUNNING,
                'finished': JobStatus.SOLVED,
                'failed': JobStatus.ERROR,
            }
            return rq_status_map.get(job.get_status(), JobStatus.ERROR)
        except NoSuchJobError:
            return None

    def get_job_result(self, job_id: str) -> Optional[schemas_response.JobResult]:
        try:
            job = Job.fetch(job_id, connection=self.redis_conn)
            if job.is_finished and job.return_value() is not None:
                return schemas_response.JobResult.model_validate(job.return_value())
            return None
        except NoSuchJobError:
            return None

    def start_solve_job(self, instance: schemas_request.Instance, params: schemas_request.Params) -> str:
        job = self.queue.enqueue(
            run_solve_task,
            instance.model_dump(),
            params.model_dump(),
            None,
            None,
            job_timeout='30m'
        )
        return job.get_id()

    def start_reoptimize_job(self, instance: schemas_request.Instance, params: schemas_request.Params, base: list, masks: list) -> str:
        job = self.queue.enqueue(
            run_solve_task,
            instance.model_dump(),
            params.model_dump(),
            [b.model_dump() for b in base],
            [m.model_dump() for m in masks],
            job_timeout='30m'
        )
        return job.get_id()

