from fastapi import APIRouter, HTTPException, Response, status, Request
from src.schemas import response as schemas_response
from src.core.enums import JobStatus

router = APIRouter()

@router.get("/{job_id}", response_model=schemas_response.JobResponse)
async def get_status(job_id: str, request: Request):
    """Gets the current status of a job."""
    job_manager = request.app.state.job_manager
    job_status = job_manager.get_job_status(job_id)
    if not job_status:
        raise HTTPException(status_code=404, detail="Job not found")
    return schemas_response.JobResponse(jobId=job_id, status=job_status.value)

@router.get("/{job_id}/result")
async def get_result(job_id: str, request: Request, response: Response):
    """Gets the result of a job."""
    job_manager = request.app.state.job_manager
    job_status = job_manager.get_job_status(job_id)

    if not job_status:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")

    if job_status == JobStatus.SOLVED:
        result = job_manager.get_job_result(job_id)
        return result or Response(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)

    if job_status == JobStatus.ERROR:
        result = job_manager.get_job_result(job_id)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=result.violations if result else "Job failed.")

    response.status_code = status.HTTP_202_ACCEPTED
    return {"status": job_status.value, "detail": "Job is being processed."}

