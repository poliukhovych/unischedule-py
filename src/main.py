from fastapi import FastAPI
from contextlib import asynccontextmanager
from src.api.v1 import solve, jobs
from src.core.job_manager import JobManager
from src.schemas import response as schemas_response

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Application startup...")
    app.state.job_manager = JobManager()
    yield
    print("Application shutdown...")

app = FastAPI(lifespan=lifespan)

app.include_router(solve.router, prefix="/v1", tags=["Solver"])
app.include_router(jobs.router, prefix="/v1/jobs", tags=["Jobs"])

@app.get("/v1/health", response_model=schemas_response.HealthResponse, tags=["Health"])
def health_check():
    return {"status": "ok"}

