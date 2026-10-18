import sqlite3
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.models import HealthResponse
from app.api import routes_query, routes_ingest, routes_escalate
from retrieval.vector_store import vector_store

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.VERSION,
    description="Shared Knowledge Brain API for AI Tech Consultant. Ingests Brilliant Directories documentation, understands screenshots, serves grounded citations, and handles human escalations."
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(routes_query.router)
app.include_router(routes_ingest.router)
app.include_router(routes_escalate.router)

@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    stats = vector_store.get_stats()
    return HealthResponse(
        status="ok",
        version=settings.VERSION,
        database_ok=True,
        indexed_articles=stats["active_articles"],
        indexed_chunks=stats["active_chunks"]
    )

@app.get("/articles", tags=["Articles Inspection"])
async def list_articles(limit: int = 50):
    with sqlite3.connect(str(settings.DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT id, url, title, category, screenshot_count, is_active, updated_at FROM articles WHERE is_active = 1 LIMIT ?", (limit,))
        articles = [dict(row) for row in cursor.fetchall()]
        return {"total": len(articles), "articles": articles}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
