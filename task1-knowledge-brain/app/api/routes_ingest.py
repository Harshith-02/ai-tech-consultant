from fastapi import APIRouter, BackgroundTasks, HTTPException
from app.models import IngestionRunRequest, IngestionStatusResponse
from ingestion.crawler import crawler

router = APIRouter(prefix="/ingestion", tags=["Ingestion & Synchronization"])

@router.post("/run", response_model=dict)
async def trigger_ingestion(request: IngestionRunRequest, background_tasks: BackgroundTasks):
    if crawler.is_running:
        return {"status": "already_running", "message": "An ingestion crawl is already in progress."}

    background_tasks.add_task(
        crawler.crawl,
        limit=request.limit,
        force_reindex=request.force_reindex,
        delay=request.delay_seconds
    )
    return {
        "status": "started",
        "message": f"Ingestion initiated with limit={request.limit}, force_reindex={request.force_reindex}."
    }

@router.get("/status", response_model=IngestionStatusResponse)
async def get_ingestion_status():
    status_data = crawler.get_status()
    return IngestionStatusResponse(**status_data)
