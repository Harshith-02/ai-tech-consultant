import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "task1-knowledge-brain"))

from ingestion.crawler import crawler
from retrieval.vector_store import vector_store

def test_change_detection_policies():
    print("\n--- Test 4: Ingestion 3-Case Change Detection & Table #2 Archival ---")
    
    # Mock current articles manifest in crawler
    test_url_active = "https://support.brilliantdirectories.com/support/solutions/articles/test-active"
    test_url_modified = "https://support.brilliantdirectories.com/support/solutions/articles/test-modified"
    test_url_missing = "https://support.brilliantdirectories.com/support/solutions/articles/test-missing"

    original_manifest = crawler.manifest
    original_path = crawler.manifest_path
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp_f:
        tmp_manifest_path = Path(tmp_f.name)
    
    try:
        crawler.manifest_path = tmp_manifest_path
        # Prepopulate crawler manifest articles
        crawler.manifest = {
            "articles": {
                test_url_active: {"url": test_url_active, "lastmod": "2026-01-01T00:00:00Z", "consecutive_missing_checks": 0},
                test_url_modified: {"url": test_url_modified, "lastmod": "2026-01-01T00:00:00Z", "consecutive_missing_checks": 0},
                test_url_missing: {"url": test_url_missing, "lastmod": "2026-01-01T00:00:00Z", "consecutive_missing_checks": 1}
            },
            "stats": {},
            "sitemap_meta": {}
        }

        # Simulate new sitemap fetch where:
        # 1. test_url_active has same lastmod (unchanged)
        # 2. test_url_modified has NEW lastmod (Case 2: date changed)
        # 3. test_url_missing is NOT in sitemap (Case 3: missing)
        # 4. test_url_brand_new is in sitemap (Case 1: URL increased)
        test_url_brand_new = "https://support.brilliantdirectories.com/support/solutions/articles/test-brand-new"
        
        sitemap_items = [
            {"url": test_url_active, "lastmod": "2026-01-01T00:00:00Z"},
            {"url": test_url_modified, "lastmod": "2026-10-23T12:00:00Z"},
            {"url": test_url_brand_new, "lastmod": "2026-10-23T12:00:00Z"}
        ]

        # Run sync manifest with missing_checks_threshold = 2
        # test_url_missing was at missing_count = 1, so hitting check #2 should trigger archival!
        results = crawler.sync_manifest_with_sitemap(sitemap_items, missing_checks_threshold=2)

        print("Sync results:", results)
        assert results["new"] == 1, "Brand new URL should be flagged for crawl (Case 1)"
        assert results["changed"] == 1, "Updated lastmod URL should be flagged for crawl (Case 2)"
        assert results["archived"] == 1, "Missing URL reaching threshold 2 should be archived (Case 3)"

        # Verify Table #2 archival in DB
        archived = vector_store.get_archived_articles()
        print(f"Total articles in Table #2 (archived_articles): {len(archived)}")
        assert any(a["url"] == test_url_missing for a in archived), "test_url_missing must be saved into Table #2"
        print("✓ Test 4 Passed: 3-Case Change Detection & Table #2 Archival verified!")
    finally:
        crawler.manifest = original_manifest
        crawler.manifest_path = original_path
        if tmp_manifest_path.exists():
            try:
                tmp_manifest_path.unlink()
            except Exception:
                pass

if __name__ == "__main__":
    test_change_detection_policies()
