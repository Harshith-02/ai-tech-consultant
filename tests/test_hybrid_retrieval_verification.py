import os
import sys
import json
import sqlite3
import pytest
from pathlib import Path

# Add project root and task1 directories to sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "task1-knowledge-brain"))

from retrieval.vector_store import KnowledgeVectorStore
from retrieval.embeddings import embedding_engine
from retrieval.qa_engine import QAEngine

DB_PATH = ROOT_DIR / "task1-knowledge-brain" / "data" / "knowledge_brain.db"

@pytest.fixture
def clean_env():
    """Ensure environment is isolated from Vercel or Turso external databases."""
    old_env = os.environ.copy()
    os.environ.pop("TURSO_DATABASE_URL", None)
    os.environ.pop("TURSO_AUTH_TOKEN", None)
    os.environ.pop("DATABASE_URL", None)
    os.environ.pop("VERCEL", None)
    os.environ.pop("ENV", None)
    yield
    os.environ.clear()
    os.environ.update(old_env)

def test_database_persistence_and_structure(clean_env):
    """Verify that the persistent SQLite database exists, is durable, and contains expected tables and row counts."""
    assert DB_PATH.exists(), f"Database file does not exist at {DB_PATH}"
    
    kvs = KnowledgeVectorStore(db_path=DB_PATH)
    status = kvs.get_storage_status()
    
    assert status["status"] == "connected"
    assert status["engine"] == "sqlite_local"
    assert status["is_durable"] is True
    
    with kvs._get_connection() as conn:
        cursor = conn.cursor()
        
        # Verify row counts
        cursor.execute("SELECT COUNT(*) FROM articles WHERE is_active = 1")
        active_articles = cursor.fetchone()[0]
        assert active_articles >= 70, f"Expected at least 70 articles, found {active_articles}"
        
        cursor.execute("SELECT COUNT(*) FROM chunks WHERE is_active = 1")
        active_chunks = cursor.fetchone()[0]
        assert active_chunks >= 400, f"Expected at least 400 chunks, found {active_chunks}"
        
        cursor.execute("SELECT COUNT(*) FROM chunks_fts")
        fts_chunks = cursor.fetchone()[0]
        assert fts_chunks == active_chunks, f"FTS5 index count ({fts_chunks}) mismatch with chunks ({active_chunks})"
        
        cursor.execute("SELECT COUNT(*) FROM sitemap_sources WHERE status = 'active'")
        sources_count = cursor.fetchone()[0]
        assert sources_count >= 2, f"Expected at least 2 active sources, found {sources_count}"
        
        cursor.execute("SELECT COUNT(*) FROM sitemap_urls WHERE status = 'active'")
        urls_count = cursor.fetchone()[0]
        assert urls_count >= 70, f"Expected at least 70 sitemap URLs, found {urls_count}"

def test_embeddings_stored_and_valid(clean_env):
    """Verify that all active chunks contain valid 384-dimensional vector embeddings stored directly in SQLite."""
    kvs = KnowledgeVectorStore(db_path=DB_PATH)
    with kvs._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, embedding_json FROM chunks WHERE is_active = 1")
        rows = cursor.fetchall()
        
        for r in rows:
            emb_str = r["embedding_json"]
            assert emb_str is not None, f"Chunk {r['id']} has NULL embedding"
            emb = json.loads(emb_str)
            assert isinstance(emb, list), f"Chunk {r['id']} embedding is not a list"
            assert len(emb) == 384, f"Chunk {r['id']} embedding has dimension {len(emb)}, expected 384"
            # Verify normalized
            magnitude = sum(x * x for x in emb) ** 0.5
            assert 0.99 <= magnitude <= 1.01, f"Chunk {r['id']} vector is not normalized (magnitude={magnitude})"

def test_hybrid_search_brilliant_directories(clean_env):
    """Verify that a Brilliant Directories inquiry returns Brilliant Directories documentation."""
    # Simulate fresh app startup
    kvs = KnowledgeVectorStore(db_path=DB_PATH)
    
    query = "How do I import categories via CSV file?"
    results = kvs.hybrid_search(query, top_k=3)
    
    assert len(results) > 0, "No results returned for Brilliant Directories query"
    top_result = results[0]
    
    # Must be from Brilliant Directories
    assert "brilliantdirectories.com" in top_result["url"], f"Expected BD URL, got {top_result['url']}"
    assert "categories" in top_result["title"].lower() or "csv" in top_result["title"].lower()
    assert top_result["relevance"] >= 0.50, f"Expected relevance >= 0.50, got {top_result['relevance']}"

def test_hybrid_search_divi(clean_env):
    """Verify that a Divi inquiry returns Divi documentation."""
    # Simulate fresh app startup
    kvs = KnowledgeVectorStore(db_path=DB_PATH)
    
    query = "How to download and install the Divi Builder plugin?"
    results = kvs.hybrid_search(query, top_k=3)
    
    assert len(results) > 0, "No results returned for Divi query"
    top_result = results[0]
    
    # Must be from Elegant Themes / Divi
    assert "elegantthemes.com" in top_result["url"], f"Expected Elegant Themes / Divi URL, got {top_result['url']}"
    assert "divi" in top_result["title"].lower() or "builder" in top_result["title"].lower()
    assert top_result["relevance"] >= 0.50, f"Expected relevance >= 0.50, got {top_result['relevance']}"

def test_cross_source_discrimination(clean_env):
    """Verify search does not confuse Brilliant Directories content with Divi content."""
    kvs = KnowledgeVectorStore(db_path=DB_PATH)
    
    # 1. BD Specific query
    bd_res = kvs.hybrid_search("import members CSV listing type profession name", top_k=3)
    assert len(bd_res) > 0
    assert all("brilliantdirectories.com" in r["url"] for r in bd_res), "Divi result leaked into BD specific query"
    
    # 2. Divi Specific query
    divi_res = kvs.hybrid_search("Visual Builder timeout error php memory limit", top_k=3)
    assert len(divi_res) > 0
    assert all("elegantthemes.com" in r["url"] for r in divi_res), "BD result leaked into Divi specific query"

def test_qa_engine_citations_both_sources(clean_env):
    """Verify QAEngine produces grounded responses with correct citations for both platforms."""
    engine = QAEngine()
    
    # Test BD query
    bd_resp = engine.generate_answer("How do I import categories via CSV file in Brilliant Directories?", top_k=3)
    assert len(bd_resp.sources) > 0
    assert any("brilliantdirectories.com" in s.url for s in bd_resp.sources)
    assert bd_resp.status in ["answered", "insufficient_evidence"]
    
    # Test Divi query
    divi_resp = engine.generate_answer("Where do I download and install the Divi Builder plugin?", top_k=3)
    assert len(divi_resp.sources) > 0
    assert any("elegantthemes.com" in s.url for s in divi_resp.sources)
    assert divi_resp.status in ["answered", "insufficient_evidence"]
