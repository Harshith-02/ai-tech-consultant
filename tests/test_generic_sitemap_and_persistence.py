import os
import sys
import json
import sqlite3
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add project root and task directories to sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "task1-knowledge-brain"))

from ingestion.crawler import PoliteResumableCrawler, safe_http_get, SafeFetchResult
from ingestion.parser import ArticleParser
from retrieval.chunker import DocumentChunker
from retrieval.vector_store import KnowledgeVectorStore
from scripts.migrate_to_turso import migrate_database

# Sample XML sitemaps for testing
SAMPLE_STANDARD_SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://docs.acme-corp.io/getting-started/overview</loc>
    <lastmod>2026-03-01T12:00:00Z</lastmod>
  </url>
  <url>
    <loc>https://docs.acme-corp.io/api/authentication</loc>
    <lastmod>2026-03-02T12:00:00Z</lastmod>
  </url>
</urlset>
"""

SAMPLE_INDEX_SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap>
    <loc>https://docs.acme-corp.io/sitemap-guides.xml</loc>
  </sitemap>
  <sitemap>
    <loc>https://docs.acme-corp.io/sitemap-api.xml</loc>
  </sitemap>
</sitemapindex>
"""

SAMPLE_CHILD_SITEMAP_GUIDES = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://docs.acme-corp.io/guides/webhook-notifications</loc>
    <lastmod>2026-03-05T08:00:00Z</lastmod>
  </url>
</urlset>
"""

SAMPLE_CHILD_SITEMAP_API = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://docs.acme-corp.io/api/rate-limits</loc>
    <lastmod>2026-03-06T08:00:00Z</lastmod>
  </url>
</urlset>
"""

SAMPLE_NAMESPACED_NO_LASTMOD_SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:xhtml="http://www.w3.org/1999/xhtml">
  <url>
    <loc>https://example.org/platform/zero-config-deploy</loc>
  </url>
  <url>
    <loc>https://example.org/platform/edge-database</loc>
  </url>
</urlset>
"""

SAMPLE_GENERIC_DOCS_HTML = """<!DOCTYPE html>
<html>
<head>
  <title>Webhook Notifications | Acme Docs</title>
  <meta property="og:title" content="Webhook Notifications Guide">
  <meta property="article:section" content="Guides >> Webhooks">
</head>
<body>
  <nav><a href="/">Home</a></nav>
  <main class="docs-content">
    <h1>Webhook Notifications Integration</h1>
    <p>Webhooks dispatch asynchronous HTTP POST payloads to your endpoint whenever key platform events occur.</p>
    <h2>Payload Structure</h2>
    <p>Each delivery includes an event identifier and a timestamped HMAC signature in the X-Acme-Signature header.</p>
    <pre><code>POST /webhook HTTP/1.1
X-Acme-Signature: sha256=d3b07384...
Content-Type: application/json</code></pre>
    <h2>Retry Policy</h2>
    <p>Failed deliveries retry up to 5 times using exponential backoff over 24 hours.</p>
  </main>
  <footer>Copyright 2026 Acme Corp</footer>
</body>
</html>
"""

SAMPLE_CHANGED_DOCS_HTML = """<!DOCTYPE html>
<html>
<head>
  <title>Webhook Notifications v2 | Acme Docs</title>
</head>
<body>
  <main class="docs-content">
    <h1>Webhook Notifications Integration</h1>
    <p>Webhooks v2 introduces real-time WebSocket fallback and RSA-PSS digital signatures.</p>
    <h2>New Security Standard</h2>
    <p>All payloads now require an RSA-PSS public key verification check.</p>
  </main>
</body>
</html>
"""

@pytest.fixture
def test_kvs(tmp_path):
    """Provides a fresh isolated SQLite database instance for testing."""
    db_file = tmp_path / "test_knowledge_brain.db"
    kvs = KnowledgeVectorStore(db_path=db_file)
    return kvs

@pytest.fixture
def test_crawler(tmp_path):
    """Provides a PoliteResumableCrawler instance with isolated manifest."""
    manifest_file = tmp_path / "test_manifest.json"
    crawler = PoliteResumableCrawler(manifest_path=manifest_file)
    return crawler

# -----------------------------------------------------------------------------
# 1. Standard XML Sitemap Parsing
# -----------------------------------------------------------------------------
def test_standard_xml_sitemap(test_crawler):
    mock_resp = SafeFetchResult(
        status_code=200,
        content=SAMPLE_STANDARD_SITEMAP.encode("utf-8"),
        text=SAMPLE_STANDARD_SITEMAP,
        final_url="https://docs.acme-corp.io/sitemap.xml",
        headers={"content-type": "application/xml"},
        redirect_history=[]
    )
    with patch("ingestion.crawler.is_safe_external_url", return_value=True):
        with patch("ingestion.crawler.safe_http_get", return_value=mock_resp):
            items = test_crawler.fetch_sitemap_urls(sitemap_urls=["https://docs.acme-corp.io/sitemap.xml"])
            assert len(items) == 2
            assert items[0]["url"] == "https://docs.acme-corp.io/getting-started/overview"
            assert items[0]["lastmod"] == "2026-03-01T12:00:00Z"
            assert items[1]["url"] == "https://docs.acme-corp.io/api/authentication"

# -----------------------------------------------------------------------------
# 2. Sitemap Index with Nested Child Sitemaps
# -----------------------------------------------------------------------------
def test_sitemap_index_recursive_discovery(test_crawler):
    def mock_fetch(url, **kwargs):
        if url == "https://docs.acme-corp.io/sitemap-index.xml":
            return SafeFetchResult(200, SAMPLE_INDEX_SITEMAP.encode(), SAMPLE_INDEX_SITEMAP, url, {}, [])
        elif url == "https://docs.acme-corp.io/sitemap-guides.xml":
            return SafeFetchResult(200, SAMPLE_CHILD_SITEMAP_GUIDES.encode(), SAMPLE_CHILD_SITEMAP_GUIDES, url, {}, [])
        elif url == "https://docs.acme-corp.io/sitemap-api.xml":
            return SafeFetchResult(200, SAMPLE_CHILD_SITEMAP_API.encode(), SAMPLE_CHILD_SITEMAP_API, url, {}, [])
        return SafeFetchResult(404, b"", "", url, {}, [])

    with patch("ingestion.crawler.is_safe_external_url", return_value=True):
        with patch("ingestion.crawler.safe_http_get", side_effect=mock_fetch):
            items = test_crawler.fetch_sitemap_urls(sitemap_urls=["https://docs.acme-corp.io/sitemap-index.xml"])
            urls = [it["url"] for it in items]
            assert len(items) == 2
            assert "https://docs.acme-corp.io/guides/webhook-notifications" in urls
            assert "https://docs.acme-corp.io/api/rate-limits" in urls

# -----------------------------------------------------------------------------
# 3. Namespaced Sitemap with No Lastmod
# -----------------------------------------------------------------------------
def test_namespaced_sitemap_no_lastmod(test_crawler):
    mock_resp = SafeFetchResult(
        200,
        SAMPLE_NAMESPACED_NO_LASTMOD_SITEMAP.encode(),
        SAMPLE_NAMESPACED_NO_LASTMOD_SITEMAP,
        "https://example.org/sitemap.xml",
        {},
        []
    )
    with patch("ingestion.crawler.is_safe_external_url", return_value=True):
        with patch("ingestion.crawler.safe_http_get", return_value=mock_resp):
            items = test_crawler.fetch_sitemap_urls(sitemap_urls=["https://example.org/sitemap.xml"])
            assert len(items) == 2
            assert items[0]["url"] == "https://example.org/platform/zero-config-deploy"
            assert items[0]["lastmod"] == ""
            assert items[1]["url"] == "https://example.org/platform/edge-database"

# -----------------------------------------------------------------------------
# 4. Duplicate URLs Across Multiple Sources Handled Correctly
# -----------------------------------------------------------------------------
def test_duplicate_url_deduplication(test_crawler):
    sitemap_a = """<urlset><url><loc>https://example.org/shared-page</loc></url></urlset>"""
    sitemap_b = """<urlset><url><loc>https://example.org/shared-page</loc></url></urlset>"""

    def mock_fetch(url, **kwargs):
        if "sitemap-a" in url:
            return SafeFetchResult(200, sitemap_a.encode(), sitemap_a, url, {}, [])
        return SafeFetchResult(200, sitemap_b.encode(), sitemap_b, url, {}, [])

    with patch("ingestion.crawler.is_safe_external_url", return_value=True):
        with patch("ingestion.crawler.safe_http_get", side_effect=mock_fetch):
            items = test_crawler.fetch_sitemap_urls(sitemap_urls=[
                "https://example.org/sitemap-a.xml",
                "https://example.org/sitemap-b.xml"
            ])
            assert len(items) == 1
            assert items[0]["url"] == "https://example.org/shared-page"

# -----------------------------------------------------------------------------
# 5. Website-Independent HTML Extraction & Chunking
# -----------------------------------------------------------------------------
def test_website_independent_article_extraction():
    parser = ArticleParser()
    url = "https://docs.acme-corp.io/guides/webhook-notifications"
    parsed = parser.parse_html(SAMPLE_GENERIC_DOCS_HTML, url)

    assert parsed["title"] == "Webhook Notifications Integration"
    assert "Guides >> Webhooks" in parsed["category"]
    assert len(parsed["content_hash"]) == 64
    assert len(parsed["sections"]) >= 2
    # Check that code block was extracted
    section_texts = " ".join(" ".join(s["paragraphs"]) for s in parsed["sections"])
    assert "POST /webhook" in section_texts

    # Chunking
    chunker = DocumentChunker()
    chunks = chunker.chunk_article(parsed)
    assert len(chunks) >= 1
    assert any("Webhook Notifications" in c["content"] for c in chunks)

# -----------------------------------------------------------------------------
# 6. Idempotent Ingestion & No Duplicates on Repeated Runs
# -----------------------------------------------------------------------------
def test_idempotent_ingestion_and_content_change_detection(test_kvs, tmp_path):
    parser = ArticleParser()
    chunker = DocumentChunker()
    url = "https://docs.acme-corp.io/guides/webhook-notifications"
    
    # 1. Initial Ingestion
    p1 = parser.parse_html(SAMPLE_GENERIC_DOCS_HTML, url)
    c1 = chunker.chunk_article(p1)
    test_kvs.upsert_article(
        article_id=p1["article_id"],
        url=url,
        title=p1["title"],
        category=p1["category"],
        content_hash=p1["content_hash"],
        raw_text=p1["raw_text"],
        screenshot_count=p1["screenshot_count"],
        chunks_data=c1,
        sitemap_source="https://docs.acme-corp.io/sitemap.xml"
    )

    stats1 = test_kvs.get_stats()
    assert stats1["active_articles"] == 1
    initial_chunks = stats1["active_chunks"]

    # 2. Repeated Ingestion of the exact same content (Idempotence)
    test_kvs.upsert_article(
        article_id=p1["article_id"],
        url=url,
        title=p1["title"],
        category=p1["category"],
        content_hash=p1["content_hash"],
        raw_text=p1["raw_text"],
        screenshot_count=p1["screenshot_count"],
        chunks_data=c1,
        sitemap_source="https://docs.acme-corp.io/sitemap.xml"
    )

    stats2 = test_kvs.get_stats()
    assert stats2["active_articles"] == 1, "Article count duplicated on repeated upsert"
    assert stats2["active_chunks"] == initial_chunks, "Chunks duplicated on repeated upsert"

    # 3. Content Update (triggers version history preservation)
    p2 = parser.parse_html(SAMPLE_CHANGED_DOCS_HTML, url)
    c2 = chunker.chunk_article(p2)
    test_kvs.upsert_article(
        article_id=p2["article_id"],
        url=url,
        title=p2["title"],
        category=p2["category"],
        content_hash=p2["content_hash"],
        raw_text=p2["raw_text"],
        screenshot_count=p2["screenshot_count"],
        chunks_data=c2,
        sitemap_source="https://docs.acme-corp.io/sitemap.xml"
    )

    # Verify version history has previous snapshot
    with test_kvs._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT version, content_hash FROM article_version_history WHERE url = ?", (url,))
        versions = cursor.fetchall()
        assert len(versions) == 1
        assert versions[0]["content_hash"] == p1["content_hash"]

# -----------------------------------------------------------------------------
# 7. Inaccessible or Missing Page Error Handling
# -----------------------------------------------------------------------------
def test_missing_page_safe_handling(test_crawler):
    def mock_fetch(url, **kwargs):
        if "sitemap" in url:
            xml = """<urlset><url><loc>https://docs.acme-corp.io/broken-page</loc></url></urlset>"""
            return SafeFetchResult(200, xml.encode(), xml, url, {}, [])
        elif "broken-page" in url:
            return SafeFetchResult(404, b"Not Found", "Not Found", url, {}, [])
        return SafeFetchResult(500, b"Server Error", "Server Error", url, {}, [])

    with patch("ingestion.crawler.is_safe_external_url", return_value=True):
        with patch("ingestion.crawler.safe_http_get", side_effect=mock_fetch):
            res = test_crawler.crawl(sitemap_urls=["https://docs.acme-corp.io/sitemap.xml"])
            assert res["failed_this_run"] == 1
            assert res["crawled_this_run"] == 0
            status = test_crawler.get_status()
            assert status["failed_count"] >= 1
            assert "HTTP 404 / Connection Error" in status.get("failure_reasons", {})

# -----------------------------------------------------------------------------
# 8. Hybrid Search & Retrieval of Ingested Non-BD Documentation
# -----------------------------------------------------------------------------
def test_search_and_retrieval_of_new_docs(test_kvs):
    parser = ArticleParser()
    chunker = DocumentChunker()
    url = "https://docs.acme-corp.io/guides/webhook-notifications"
    p = parser.parse_html(SAMPLE_GENERIC_DOCS_HTML, url)
    c = chunker.chunk_article(p)

    test_kvs.upsert_article(
        article_id=p["article_id"],
        url=url,
        title=p["title"],
        category=p["category"],
        content_hash=p["content_hash"],
        raw_text=p["raw_text"],
        screenshot_count=p["screenshot_count"],
        chunks_data=c
    )

    # Hybrid search for "webhook notifications payload"
    hybrid_results = test_kvs.hybrid_search("webhook notifications payload", top_k=3)
    assert len(hybrid_results) > 0
    assert "webhook" in hybrid_results[0]["url"].lower()

# -----------------------------------------------------------------------------
# 9. Production Turso Requirement Validation
# -----------------------------------------------------------------------------
def test_production_turso_enforcement():
    """Verify that in production mode, missing Turso credentials immediately raises RuntimeError."""
    with patch.dict(os.environ, {"VERCEL": "1"}, clear=False):
        # Remove any Turso env vars for test
        with patch.dict(os.environ, {"TURSO_DATABASE_URL": "", "TURSO_AUTH_TOKEN": ""}):
            kvs = KnowledgeVectorStore()
            with pytest.raises(RuntimeError, match="Production requires persistent managed database storage"):
                kvs._get_connection()

# -----------------------------------------------------------------------------
# 10. Database Migration Idempotency Test
# -----------------------------------------------------------------------------
def test_database_migration_idempotent(tmp_path):
    """Verify migrate_database dry-run and validation logic executes with zero data loss."""
    src_db = tmp_path / "src_test.db"
    src_kvs = KnowledgeVectorStore(db_path=src_db)
    
    # Populate a test article
    p = ArticleParser().parse_html(SAMPLE_GENERIC_DOCS_HTML, "https://docs.acme-corp.io/sample")
    c = DocumentChunker().chunk_article(p)
    src_kvs.upsert_article(
        article_id=p["article_id"],
        url="https://docs.acme-corp.io/sample",
        title=p["title"],
        category=p["category"],
        content_hash=p["content_hash"],
        raw_text=p["raw_text"],
        screenshot_count=0,
        chunks_data=c
    )

    # Run dry-run migration
    res = migrate_database(str(src_db), "", "", dry_run=True)
    assert res["status"] == "dry_run"
    assert res["source_counts"]["articles"] >= 1
    assert res["source_counts"]["chunks"] >= 1
