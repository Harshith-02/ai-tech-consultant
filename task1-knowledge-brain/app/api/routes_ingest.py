from typing import List, Dict, Any
from fastapi import APIRouter, BackgroundTasks, HTTPException
from app.models import IngestionRunRequest, IngestionStatusResponse, SitemapInspectRequest, SitemapInspectResponse
from ingestion.crawler import crawler
from retrieval.vector_store import vector_store

router = APIRouter(prefix="/ingestion", tags=["Ingestion & Synchronization"])

@router.post("/inspect", response_model=SitemapInspectResponse)
async def inspect_sitemap_urls(request: SitemapInspectRequest):
    """
    Inspects a single or nested sitemap XML, counts sub-sitemaps and URLs,
    identifies first and last URLs, and calculates speed and completion ETA.
    """
    try:
        data = crawler.inspect_sitemap(request.sitemap_url, url_pattern=request.url_pattern)
        return SitemapInspectResponse(**data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to inspect sitemap: {str(e)}")

@router.post("/run", response_model=dict)
async def trigger_ingestion(request: IngestionRunRequest, background_tasks: BackgroundTasks):
    if crawler.is_running:
        return {"status": "already_running", "message": "An ingestion crawl is already in progress."}

    missing_policy = request.missing_retention_policy if request.missing_retention_policy is not None else 15
    background_tasks.add_task(
        crawler.crawl,
        limit=request.limit,
        force_reindex=request.force_reindex,
        delay=request.delay_seconds,
        sitemap_urls=request.sitemap_urls,
        url_pattern=request.url_pattern,
        missing_checks_threshold=missing_policy
    )
    
    count_sitemaps = len(request.sitemap_urls) if request.sitemap_urls else "default"
    return {
        "status": "started",
        "message": f"Ingestion initiated for {count_sitemaps} sitemap(s) (missing_policy={missing_policy} checks, frequency={request.update_frequency})."
    }

@router.get("/status", response_model=IngestionStatusResponse)
async def get_ingestion_status():
    status_data = crawler.get_status()
    archived = vector_store.get_archived_articles()
    status_data["archived_articles_count"] = len(archived)
    return IngestionStatusResponse(**status_data)

@router.get("/sitemaps", response_model=List[Dict[str, Any]])
async def list_configured_sitemaps():
    return crawler.get_sitemaps()

@router.get("/archived", response_model=List[Dict[str, Any]])
async def list_archived_articles():
    """Returns Table #2 / Database #2 archived knowledge articles."""
    return vector_store.get_archived_articles()
