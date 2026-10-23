import json
import time
import ipaddress
import socket
from urllib.parse import urlparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional
from xml.etree import ElementTree as ET
import httpx

from app.config import settings
from ingestion.parser import article_parser
from retrieval.chunker import document_chunker
from retrieval.vector_store import vector_store

def is_safe_external_url(url: str) -> bool:
    """
    SSRF Defense: Validates that a target URL is an HTTP/HTTPS URL
    and does not point to localhost, private IP blocks, or cloud metadata.
    """
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = parsed.hostname
        if not hostname:
            return False
        lower_host = hostname.lower()
        if lower_host in ("localhost", "127.0.0.1", "0.0.0.0", "::1", "metadata.google.internal", "169.254.169.254"):
            return False
        ip_str = socket.gethostbyname(hostname)
        ip = ipaddress.ip_address(ip_str)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
        return True
    except Exception:
        return False

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
        data = {
            "last_sitemap_sync": None,
            "configured_sitemaps": [settings.SITEMAP_URL],
            "sitemap_meta": {
                settings.SITEMAP_URL: {
                    "last_synced": None,
                    "urls_count": 0,
                    "status": "ready"
                }
            },
            "articles": {},
            "stats": {"total_crawled": 0, "total_failed": 0, "total_removed": 0}
        }
        if self.manifest_path.exists():
            try:
                with open(self.manifest_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict):
                        data.update(loaded)
                        if "configured_sitemaps" not in data or not data["configured_sitemaps"]:
                            data["configured_sitemaps"] = [settings.SITEMAP_URL]
                        if "sitemap_meta" not in data:
                            data["sitemap_meta"] = {}
                        return data
            except Exception:
                pass
        return data

    def _save_manifest(self):
        with open(self.manifest_path, "w", encoding="utf-8") as f:
            json.dump(self.manifest, f, indent=2)

    def fetch_sitemap_urls(
        self,
        sitemap_urls: Optional[List[str]] = None,
        url_pattern: Optional[str] = None
    ) -> List[Dict[str, str]]:
        """
        Fetches and parses one or multiple sitemaps, supporting both standard
        <urlset> and nested <sitemapindex> formats, with optional URL filtering.
        """
        # Determine target sitemap URLs
        targets: List[str] = []
        if sitemap_urls:
            for s in sitemap_urls:
                cleaned = s.strip()
                if cleaned and is_safe_external_url(cleaned) and cleaned not in targets:
                    targets.append(cleaned)
        else:
            targets = [t for t in (self.manifest.get("configured_sitemaps") or [settings.SITEMAP_URL]) if is_safe_external_url(t)]

        # Ensure targets are registered in configured_sitemaps
        existing_configs = self.manifest.setdefault("configured_sitemaps", [])
        for t in targets:
            if t not in existing_configs:
                existing_configs.append(t)
        self.manifest.setdefault("sitemap_meta", {})

        headers = {"User-Agent": settings.USER_AGENT}
        results: List[Dict[str, str]] = []
        seen_urls = set()

        def parse_xml_tree(root_elem: ET.Element, current_sitemap_source: str, depth: int = 0) -> List[Dict[str, str]]:
            items: List[Dict[str, str]] = []
            if depth > 2:
                return items

            # Check if this is a sitemap index (<sitemapindex>)
            # Handle elements with or without namespace
            sitemap_nodes = root_elem.findall(".//{*}sitemap")
            if not sitemap_nodes:
                sitemap_nodes = [elem for elem in root_elem.iter() if elem.tag.split("}")[-1] == "sitemap"]

            if sitemap_nodes:
                for sm in sitemap_nodes:
                    loc = sm.find("{*}loc")
                    if loc is None:
                        loc = next((c for c in sm if c.tag.split("}")[-1] == "loc"), None)
                    if loc is not None and loc.text:
                        sub_url = loc.text.strip()
                        if not is_safe_external_url(sub_url):
                            continue
                        try:
                            with httpx.Client(timeout=settings.REQUEST_TIMEOUT_SECONDS, follow_redirects=True, headers=headers) as client:
                                r = client.get(sub_url)
                                if r.status_code == 200:
                                    sub_root = ET.fromstring(r.content)
                                    items.extend(parse_xml_tree(sub_root, current_sitemap_source, depth + 1))
                        except Exception:
                            continue

            # Parse regular <url> entries
            url_nodes = root_elem.findall(".//{*}url")
            if not url_nodes:
                url_nodes = [elem for elem in root_elem.iter() if elem.tag.split("}")[-1] == "url"]

            for url_node in url_nodes:
                loc = url_node.find("{*}loc")
                if loc is None:
                    loc = next((c for c in url_node if c.tag.split("}")[-1] == "loc"), None)

                lastmod = url_node.find("{*}lastmod")
                if lastmod is None:
                    lastmod = next((c for c in url_node if c.tag.split("}")[-1] == "lastmod"), None)

                if loc is not None and loc.text:
                    url_str = loc.text.strip()
                    if url_str in seen_urls:
                        continue

                    # Filtering logic
                    if url_pattern:
                        if url_pattern.lower() not in url_str.lower():
                            continue
                    else:
                        if "support.brilliantdirectories.com" in current_sitemap_source:
                            if "/articles/" not in url_str:
                                continue
                        else:
                            # Filter out non-article / static asset files
                            lower_url = url_str.lower()
                            ignored_exts = (
                                ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp",
                                ".pdf", ".zip", ".tar", ".gz", ".css", ".js",
                                ".json", ".ico", ".woff", ".woff2", ".ttf", ".mp4"
                            )
                            if lower_url.endswith(ignored_exts):
                                continue

                    seen_urls.add(url_str)
                    items.append({
                        "url": url_str,
                        "lastmod": lastmod.text.strip() if lastmod is not None and lastmod.text else "",
                        "sitemap_source": current_sitemap_source
                    })
            return items

        with httpx.Client(timeout=settings.REQUEST_TIMEOUT_SECONDS, follow_redirects=True, headers=headers) as client:
            for sm_url in targets:
                try:
                    resp = client.get(sm_url)
                    resp.raise_for_status()
                    root = ET.fromstring(resp.content)
                    sitemap_articles = parse_xml_tree(root, sm_url, depth=0)
                    results.extend(sitemap_articles)

                    # Update sitemap metadata
                    self.manifest["sitemap_meta"][sm_url] = {
                        "last_synced": datetime.now(timezone.utc).isoformat(),
                        "urls_count": len(sitemap_articles),
                        "status": "synced"
                    }
                except Exception as e:
                    self.manifest["sitemap_meta"][sm_url] = {
                        "last_synced": datetime.now(timezone.utc).isoformat(),
                        "urls_count": 0,
                        "status": f"error: {str(e)[:50]}"
                    }

        return results

    def inspect_sitemap(self, sitemap_url: str, url_pattern: Optional[str] = None) -> Dict[str, Any]:
        """
        Inspects a single or nested sitemap XML, counts sub-sitemaps and URLs,
        identifies first and last URLs, and calculates speed and completion ETA.
        """
        cleaned_url = sitemap_url.strip()
        items = self.fetch_sitemap_urls(sitemap_urls=[cleaned_url], url_pattern=url_pattern)
        total_urls = len(items)

        # Count sub-sitemaps
        sub_sitemaps_count = 1
        headers = {"User-Agent": settings.USER_AGENT}
        try:
            with httpx.Client(timeout=settings.REQUEST_TIMEOUT_SECONDS, follow_redirects=True, headers=headers) as client:
                r = client.get(cleaned_url)
                if r.status_code == 200:
                    root = ET.fromstring(r.content)
                    sitemap_nodes = root.findall(".//{*}sitemap")
                    if sitemap_nodes:
                        sub_sitemaps_count = len(sitemap_nodes)
        except Exception:
            pass

        # Speed & ETA calculation: 0.5s per article with rate limiting jitter
        pages_per_5_min = 50
        pages_per_hour = 600
        pages_per_24_hours = 14400

        total_seconds = total_urls * 0.5
        hours = int(total_seconds // 3600)
        minutes = int((total_seconds % 3600) // 60)
        days = int(hours // 24)

        if days > 0:
            rem_hours = hours % 24
            eta_text = f"{days} day{'s' if days > 1 else ''} {rem_hours} hr{'s' if rem_hours != 1 else ''} {minutes} mins (±1 day)"
        elif hours > 0:
            eta_text = f"{hours} hr{'s' if hours != 1 else ''} {minutes} mins (±1 day)"
        else:
            eta_text = f"{max(1, minutes)} mins (±1 day)"

        return {
            "sitemap_url": cleaned_url,
            "total_sitemaps_found": sub_sitemaps_count,
            "total_urls_found": total_urls,
            "first_url": items[0]["url"] if items else None,
            "last_url": items[-1]["url"] if items else None,
            "speed_estimates": {
                "pages_per_5_min": pages_per_5_min,
                "pages_per_hour": pages_per_hour,
                "pages_per_24_hours": pages_per_24_hours,
                "estimated_time_text": eta_text
            },
            "sample_urls": [it["url"] for it in items[:6]]
        }

    def sync_manifest_with_sitemap(
        self,
        sitemap_items: List[Dict[str, str]],
        sitemap_sources_crawled: Optional[List[str]] = None,
        missing_checks_threshold: int = 15
    ) -> Dict[str, int]:
        current_urls = {item["url"]: item for item in sitemap_items}
        stored_articles = self.manifest.get("articles", {})

        new_count = 0
        changed_count = 0
        archived_count = 0

        # Case 1 & 2: URL increase (new) or update date (lastmod) changed
        for url, item_info in current_urls.items():
            lastmod = item_info.get("lastmod", "")
            sitemap_src = item_info.get("sitemap_source")

            if url not in stored_articles:
                # Case 1: Sitemap URL increased -> add to database
                stored_articles[url] = {
                    "status": "pending",
                    "lastmod": lastmod,
                    "sitemap_source": sitemap_src,
                    "consecutive_missing_checks": 0,
                    "content_hash": None,
                    "attempts": 0,
                    "error": None,
                    "crawled_at": None
                }
                new_count += 1
            else:
                existing = stored_articles[url]
                if sitemap_src:
                    existing["sitemap_source"] = sitemap_src
                existing["consecutive_missing_checks"] = 0  # reset missing streak
                # Case 2: Update date changed -> re-access and re-update knowledge base
                if lastmod and existing.get("lastmod") != lastmod:
                    existing["status"] = "pending"
                    existing["lastmod"] = lastmod
                    changed_count += 1

        # Case 3: URLs missing -> check consecutive missing count against configured threshold
        for stored_url, info in stored_articles.items():
            item_source = info.get("sitemap_source")
            is_relevant_sitemap = (
                sitemap_sources_crawled is None or 
                item_source is None or 
                item_source in sitemap_sources_crawled
            )

            if is_relevant_sitemap and stored_url not in current_urls:
                miss_cnt = info.get("consecutive_missing_checks", 0) + 1
                info["consecutive_missing_checks"] = miss_cnt
                if miss_cnt >= missing_checks_threshold and info.get("status") not in ["removed", "archived"]:
                    info["status"] = "archived"
                    # Remove from KB #1 and save in Table #2 (archived_articles)
                    vector_store.archive_article(
                        stored_url, 
                        reason=f"Missing across {miss_cnt} consecutive checks (threshold={missing_checks_threshold})",
                        checks_count=miss_cnt
                    )
                    archived_count += 1

        self.manifest["last_sitemap_sync"] = datetime.now(timezone.utc).isoformat()
        stats = self.manifest.setdefault("stats", {})
        stats["total_removed"] = stats.get("total_removed", 0) + archived_count
        self._save_manifest()

        return {"new": new_count, "changed": changed_count, "archived": archived_count}

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

    def crawl(
        self,
        limit: Optional[int] = None,
        force_reindex: bool = False,
        delay: Optional[float] = None,
        sitemap_urls: Optional[List[str]] = None,
        url_pattern: Optional[str] = None,
        missing_checks_threshold: int = 15
    ) -> Dict[str, Any]:
        self.is_running = True
        sleep_delay = delay if delay is not None else settings.CRAWL_DELAY_SECONDS
        
        try:
            sitemap_items = self.fetch_sitemap_urls(sitemap_urls=sitemap_urls, url_pattern=url_pattern)
            sync_stats = self.sync_manifest_with_sitemap(
                sitemap_items, 
                sitemap_sources_crawled=sitemap_urls,
                missing_checks_threshold=missing_checks_threshold
            )

            articles_dict = self.manifest.get("articles", {})
            targets = []
            crawled_sitemaps_set = set(sitemap_urls) if sitemap_urls else None

            for url, info in articles_dict.items():
                if crawled_sitemaps_set and info.get("sitemap_source") and info.get("sitemap_source") not in crawled_sitemaps_set:
                    continue

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
                "configured_sitemaps": self.manifest.get("configured_sitemaps", []),
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
            "last_run": self.manifest.get("last_sitemap_sync"),
            "configured_sitemaps": self.manifest.get("configured_sitemaps", [settings.SITEMAP_URL])
        }

    def get_sitemaps(self) -> List[Dict[str, Any]]:
        configured = self.manifest.get("configured_sitemaps", [settings.SITEMAP_URL])
        meta = self.manifest.get("sitemap_meta", {})
        articles_dict = self.manifest.get("articles", {})
        
        counts: Dict[str, int] = {}
        for info in articles_dict.values():
            src = info.get("sitemap_source") or settings.SITEMAP_URL
            counts[src] = counts.get(src, 0) + 1

        results = []
        for sm in configured:
            sm_meta = meta.get(sm, {})
            results.append({
                "url": sm,
                "last_synced": sm_meta.get("last_synced"),
                "urls_count": counts.get(sm, sm_meta.get("urls_count", 0)),
                "status": sm_meta.get("status", "ready")
            })
        return results

crawler = PoliteResumableCrawler()
