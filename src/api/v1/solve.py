from fastapi import APIRouter, HTTPException, Request, status
from src.schemas import request as schemas_request
from src.schemas import response as schemas_response
from src.solver.scheduler import ScheduleSolver

router = APIRouter()

@router.post("/solve", response_model=schemas_response.JobResponse, status_code=status.HTTP_202_ACCEPTED)
async def solve(req: schemas_request.SolveRequest, request: Request):
    """Starts a new schedule calculation job."""
    job_manager = request.app.state.job_manager
    job_id = job_manager.start_solve_job(req.instance, req.params)
    return schemas_response.JobResponse(jobId=job_id, status="queued")

@router.post("/reoptimize", response_model=schemas_response.JobResponse, status_code=status.HTTP_202_ACCEPTED)
async def reoptimize(req: schemas_request.ReoptimizeRequest, request: Request):
    """Starts a new reoptimization job."""
    job_manager = request.app.state.job_manager
    job_id = job_manager.start_reoptimize_job(
        instance=req.instance,
        params=req.params,
        base=req.base,
        masks=req.masks
    )
    return schemas_response.JobResponse(jobId=job_id, status="queued")

@router.post("/explain", response_model=schemas_response.ExplainResponse)
async def explain(req: schemas_request.ExplainRequest):
    """Diagnoses conflicts for a specific proposed assignment."""
    try:
        solver = ScheduleSolver(req.instance, params=req.params)
        response = solver.explain_conflict(req.instance, req.focus_assignment, req.base or [])
        return response
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error during explanation: {str(e)}")

