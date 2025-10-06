from pydantic import BaseModel
from typing import List


class Stats(BaseModel):
    """Holds statistics about the solver run."""
    solve_time_sec: float
    status: str


class Assignment(BaseModel):
    """Represents a single course assignment in the final schedule."""
    courseId: str
    teacherId: str
    roomId: str
    timeslot: str
    groupIds: List[str]


class JobResult(BaseModel):
    """The final result of a solved job."""
    assignments: List[Assignment]
    objective: int
    status: str
    violations: List[str]
    stats: Stats


class JobResponse(BaseModel):
    """Standard response for endpoints that return a job ID and status."""
    jobId: str
    status: str


class HealthResponse(BaseModel):
    """Response for the health check endpoint."""
    status: str


class ExplainResponse(BaseModel):
    """Response for the /explain endpoint."""
    conflicts: List[str]
