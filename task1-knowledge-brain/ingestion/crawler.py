import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional
from xml.etree import ElementTree as ET
import httpx

from app.config import settings
from ingestion.parser import article_parser
from retrieval.chunker import document_chunker
from retrieval.vector_store import vector_store

class PoliteResumableCrawler:
    """
    Polite, resumable crawler for Brilliant Directories Solution Center.
    Features:
    - Sitemap XML ingestion with incremental diffing
    - Checkpoint manifest persistence (survives restarts)
    - Rate-limiting with jitter and exponential backoff
    - Deletion detection (deactivates removed help articles)
    - Idempotent re-indexing
    """
    def __init__(self, manifest_path: Optional[Path] = None):
        self.manifest_path = manifest_path or settings.MANIFEST_PATH
        self.manifest: Dict[str, Any] = self._load_manifest()
        self.is_running = False

    def _load_manifest(self) -> Dict[str, Any]:
        if self.manifest_path.exists():
            try:
                with open(self.manifest_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "last_sitemap_sync": None,
            "articles": {},
            "stats": {"total_crawled": 0, "total_failed": 0, "total_removed": 0}
        }

    def _save_manifest(self):
        with open(self.manifest_path, "w", encoding="utf-8") as f:
            json.dump(self.manifest, f, indent=2)

    def fetch_sitemap_urls(self) -> List[Dict[str, str]]:
        headers = {"User-Agent": settings.USER_AGENT}
        with httpx.Client(timeout=settings.REQUEST_TIMEOUT_SECONDS, follow_redirects=True, headers=headers) as client:
            resp = client.get(settings.SITEMAP_URL)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)

        results = []
        for url_node in root.findall("{http://www.sitemaps.org/schemas/sitemap/0.9}url"):
            loc = url_node.find("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")
            lastmod = url_node.find("{http://www.sitemaps.org/schemas/sitemap/0.9}lastmod")
            if loc is not None and loc.text:
                url_str = loc.text.strip()
                if "/articles/" in url_str:
                    results.append({
                        "url": url_str,
                        "lastmod": lastmod.text.strip() if lastmod is not None and lastmod.text else ""
                    })
        return results

    def sync_manifest_with_sitemap(self, sitemap_items: List[Dict[str, str]]) -> Dict[str, int]:
        current_urls = {item["url"]: item["lastmod"] for item in sitemap_items}
        stored_articles = self.manifest.get("articles", {})

        new_count = 0
        changed_count = 0
        removed_count = 0

        for url, lastmod in current_urls.items():
            if url not in stored_articles:
                stored_articles[url] = {
                    "status": "pending",
                    "lastmod": lastmod,
                    "content_hash": None,
                    "attempts": 0,
                    "error": None,
                    "crawled_at": None
                }
                new_count += 1
            else:
                existing = stored_articles[url]
                if lastmod and existing.get("lastmod") != lastmod:
                    existing["status"] = "pending"
                    existing["lastmod"] = lastmod
                    changed_count += 1

        for stored_url, info in stored_articles.items():
            if stored_url not in current_urls and info.get("status") != "removed":
                info["status"] = "removed"
                vector_store.deactivate_article(stored_url)
                removed_count += 1

        self.manifest["last_sitemap_sync"] = datetime.now(timezone.utc).isoformat()
        self.manifest["stats"]["total_removed"] = self.manifest["stats"].get("total_removed", 0) + removed_count
        self._save_manifest()

        return {"new": new_count, "changed": changed_count, "removed": removed_count}

    def fetch_article_with_retries(self, url: str) -> Optional[str]:
        headers = {"User-Agent": settings.USER_AGENT}
        for attempt in range(1, settings.MAX_CRAWL_RETRIES + 1):
            try:
                with httpx.Client(timeout=settings.REQUEST_TIMEOUT_SECONDS, follow_redirects=True, headers=headers) as client:
                    resp = client.get(url)
                    if resp.status_code == 200:
                        return resp.text
                    elif resp.status_code == 404:
                        return None
                    elif resp.status_code in [429, 500, 502, 503, 504]:
                        wait_sec = (2 ** attempt) * 0.5
                        time.sleep(wait_sec)
                    else:
                        return None
            except Exception:
                if attempt == settings.MAX_CRAWL_RETRIES:
                    return None
                time.sleep(1.0)
        return None

    def crawl(self, limit: Optional[int] = None, force_reindex: bool = False, delay: Optional[float] = None) -> Dict[str, Any]:
        self.is_running = True
        sleep_delay = delay if delay is not None else settings.CRAWL_DELAY_SECONDS
        
        try:
            sitemap_items = self.fetch_sitemap_urls()
            sync_stats = self.sync_manifest_with_sitemap(sitemap_items)

            articles_dict = self.manifest.get("articles", {})
            targets = []
            for url, info in articles_dict.items():
                if force_reindex or info.get("status") in ["pending", "failed"]:
                    targets.append(url)

            if limit:
                targets = targets[:limit]

            crawled_this_run = 0
            failed_this_run = 0

            for url in targets:
                record = articles_dict[url]
                record["attempts"] = record.get("attempts", 0) + 1

                html = self.fetch_article_with_retries(url)
                if not html:
                    record["status"] = "failed"
                    record["error"] = "HTTP fetch error or 404"
                    failed_this_run += 1
                    self._save_manifest()
                    time.sleep(sleep_delay)
                    continue

                try:
                    parsed = article_parser.parse_html(html, url)
                    chunks = document_chunker.chunk_article(parsed)

                    aid = parsed["article_id"]
                    raw_path = settings.RAW_ARTICLES_DIR / f"{aid}.json"
                    with open(raw_path, "w", encoding="utf-8") as f:
                        json.dump(parsed, f, indent=2)

                    vector_store.upsert_article(
                        article_id=aid,
                        url=url,
                        title=parsed["title"],
                        category=parsed["category"],
                        content_hash=parsed["content_hash"],
                        raw_text=parsed["raw_text"],
                        screenshot_count=parsed["screenshot_count"],
                        chunks_data=chunks
                    )

                    record["status"] = "completed"
                    record["content_hash"] = parsed["content_hash"]
                    record["crawled_at"] = datetime.now(timezone.utc).isoformat()
                    record["error"] = None
                    crawled_this_run += 1
                except Exception as e:
                    record["status"] = "failed"
                    record["error"] = str(e)
                    failed_this_run += 1

                self._save_manifest()
                time.sleep(sleep_delay)

            self.manifest["stats"]["total_crawled"] = self.manifest["stats"].get("total_crawled", 0) + crawled_this_run
            self.manifest["stats"]["total_failed"] = self.manifest["stats"].get("total_failed", 0) + failed_this_run
            self._save_manifest()

            return {
                "status": "completed",
                "crawled_this_run": crawled_this_run,
                "failed_this_run": failed_this_run,
                "total_sitemap_articles": len(sitemap_items),
                "sync_summary": sync_stats
            }
        finally:
            self.is_running = False

    def get_status(self) -> Dict[str, Any]:
        stats = vector_store.get_stats()
        articles_dict = self.manifest.get("articles", {})
        crawled = sum(1 for v in articles_dict.values() if v.get("status") == "completed")
        failed = sum(1 for v in articles_dict.values() if v.get("status") == "failed")
        return {
            "status": "running" if self.is_running else "idle",
            "is_running": self.is_running,
            "total_sitemap_urls": len(articles_dict),
            "crawled_count": crawled,
            "failed_count": failed,
            "chunk_count": stats["active_chunks"],
            "active_articles": stats["active_articles"],
            "last_run": self.manifest.get("last_sitemap_sync")
        }

crawler = PoliteResumableCrawler()
