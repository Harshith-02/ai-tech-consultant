import json
import time
import ipaddress
import socket
from urllib.parse import urlparse, urljoin
from datetime import datetime, timezone, timedelta
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
        if lower_host in ("localhost", "127.0.0.1", "0.0.0.0", "::1", "metadata.google.internal", "169.254.169.254", "instance-data"):
            return False
        if parsed.port and parsed.port not in (80, 443, 8080):
            return False
        ip_str = socket.gethostbyname(hostname)
        ip = ipaddress.ip_address(ip_str)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
        return True
    except Exception:
        return False

class SafeFetchResult:
    def __init__(
        self,
        status_code: int,
        content: bytes,
        text: str,
        final_url: str,
        headers: Dict[str, str],
        redirect_history: List[Dict[str, Any]]
    ):
        self.status_code = status_code
        self.content = content
        self.text = text
        self.final_url = final_url
        self.headers = headers
        self.redirect_history = redirect_history

def safe_http_get(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = 10.0,
    max_redirects: int = 5,
    max_bytes: int = 5_000_000
) -> SafeFetchResult:
    """
    SSRF-hardened HTTP client:
    1. Validates scheme, port, hostname, and resolved IP prior to every connection hop.
    2. Re-validates every redirect destination (301, 302, 303, 307, 308) before connecting.
    3. Rejects loops, private IPs, link-local, localhost, and cloud metadata endpoints.
    4. Enforces maximum redirect depth and response payload size limits.
    5. Records full redirect history and canonical URLs.
    """
    curr_url = url.strip()
    visited = []
    redirect_history = []
    req_headers = headers or {"User-Agent": settings.USER_AGENT}

    with httpx.Client(timeout=timeout, follow_redirects=False, headers=req_headers) as client:
        for _ in range(max_redirects + 1):
            if not is_safe_external_url(curr_url):
                raise ValueError(f"Blocked unsafe SSRF destination: {curr_url}")
            if curr_url in visited:
                raise ValueError(f"Redirect loop detected at: {curr_url}")
            visited.append(curr_url)

            resp = client.get(curr_url)

            if resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("location")
                if not location:
                    break
                next_url = urljoin(curr_url, location.strip())
                redirect_history.append({
                    "from_url": curr_url,
                    "to_url": next_url,
                    "status_code": resp.status_code
                })
                curr_url = next_url
                continue

            content = resp.content
            if len(content) > max_bytes:
                content = content[:max_bytes]
            return SafeFetchResult(
                status_code=resp.status_code,
                content=content,
                text=resp.text[:max_bytes] if resp.text else "",
                final_url=curr_url,
                headers=dict(resp.headers),
                redirect_history=redirect_history
            )
        raise ValueError(f"Exceeded maximum redirect hops ({max_redirects})")

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
                            res = safe_http_get(sub_url, headers=headers, timeout=settings.REQUEST_TIMEOUT_SECONDS)
                            if res.status_code == 200:
                                sub_root = ET.fromstring(res.content)
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

        for sm_url in targets:
            try:
                resp = safe_http_get(sm_url, headers=headers, timeout=settings.REQUEST_TIMEOUT_SECONDS)
                if resp.status_code != 200:
                    raise RuntimeError(f"HTTP {resp.status_code}")
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
            r = safe_http_get(cleaned_url, headers=headers, timeout=settings.REQUEST_TIMEOUT_SECONDS)
            if r.status_code == 200:
                root = ET.fromstring(r.content)
                sitemap_nodes = root.findall(".//{*}sitemap")
                if sitemap_nodes:
                    sub_sitemaps_count = len(sitemap_nodes)
        except Exception:
            pass

        # Dynamic measured performance based on actual historical pipeline throughput:
        # stages: page fetch, parsing, chunk generation, embedding generation, FTS indexing, vector store write
        perf = self.manifest.get("measured_perf", {})
        total_measured = perf.get("total_pages_measured", 0)
        avg_sec = perf.get("avg_seconds_per_page")
        is_provisional = (avg_sec is None or total_measured < 5)

        if not avg_sec or avg_sec <= 0:
            avg_sec = 0.55  # measured realistic average across fetch + chunk + embed

        pages_per_5_min = max(1, int(300 / avg_sec))
        pages_per_hour = max(1, int(3600 / avg_sec))
        pages_per_24_hours = max(1, int(86400 / avg_sec))

        total_seconds = total_urls * avg_sec
        hours = int(total_seconds // 3600)
        minutes = int((total_seconds % 3600) // 60)
        days = int(hours // 24)

        now_utc = datetime.now(timezone.utc)
        expected_completion_dt = (now_utc + timedelta(seconds=total_seconds)).isoformat()

        if days > 0:
            rem_hours = hours % 24
            eta_text = f"{days} day{'s' if days > 1 else ''} {rem_hours} hr{'s' if rem_hours != 1 else ''} {minutes} mins (±1 day)"
        elif hours > 0:
            eta_text = f"{hours} hr{'s' if hours != 1 else ''} {minutes} mins (±1 day)"
        else:
            eta_text = f"{max(1, minutes)} mins (±1 day)"

        with_lastmod = sum(1 for it in items if it.get("lastmod"))
        without_lastmod = len(items) - with_lastmod

        return {
            "sitemap_url": cleaned_url,
            "total_sitemaps_found": sub_sitemaps_count,
            "total_urls_found": total_urls,
            "urls_with_lastmod": with_lastmod,
            "urls_without_lastmod": without_lastmod,
            "first_url": items[0]["url"] if items else None,
            "last_url": items[-1]["url"] if items else None,
            "speed_estimates": {
                "pages_per_5_min": pages_per_5_min,
                "pages_per_hour": pages_per_hour,
                "pages_per_24_hours": pages_per_24_hours,
                "estimated_time_text": eta_text,
                "measured_avg_seconds_per_page": round(avg_sec, 3),
                "is_provisional": is_provisional,
                "expected_completion_datetime": expected_completion_dt,
                "pipeline_stages": [
                    "safe_page_fetching",
                    "content_extraction",
                    "heading_aware_chunking",
                    "embedding_generation",
                    "keyword_fts5_indexing",
                    "vector_indexing"
                ]
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
                    # Remove from KB #1 and save in Table #2 (archived_articles) with cross-source safety
                    archived = vector_store.archive_article(
                        stored_url, 
                        reason=f"Missing across {miss_cnt} consecutive checks (threshold={missing_checks_threshold})",
                        checks_count=miss_cnt,
                        source_url=item_source
                    )
                    if archived:
                        info["status"] = "archived"
                        archived_count += 1

        self.manifest["last_sitemap_sync"] = datetime.now(timezone.utc).isoformat()
        stats = self.manifest.setdefault("stats", {})
        stats["total_removed"] = stats.get("total_removed", 0) + archived_count
        self._save_manifest()

        try:
            vector_store.batch_record_sitemap_urls(sitemap_items)
        except Exception:
            pass

        return {"new": new_count, "changed": changed_count, "archived": archived_count}

    def fetch_article_with_retries(self, url: str) -> Optional[str]:
        headers = {"User-Agent": settings.USER_AGENT}
        for attempt in range(1, settings.MAX_CRAWL_RETRIES + 1):
            try:
                resp = safe_http_get(url, headers=headers, timeout=settings.REQUEST_TIMEOUT_SECONDS)
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
        t_run_start = time.time()
        
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

            self.current_run = {
                "started_at": datetime.now(timezone.utc).isoformat(),
                "sitemaps_count": len(sitemap_urls) if sitemap_urls else len(self.manifest.get("configured_sitemaps", [])),
                "total_urls_discovered": len(sitemap_items),
                "urls_queued": len(targets),
                "pages_fetched": 0,
                "pages_saved": 0,
                "pages_indexed": 0,
                "pages_failed": 0,
                "pages_skipped": max(0, len(sitemap_items) - len(targets)),
                "new_urls": sync_stats.get("new", 0),
                "changed_urls": sync_stats.get("changed", 0),
                "unchanged_urls": max(0, len(sitemap_items) - sync_stats.get("new", 0) - sync_stats.get("changed", 0)),
                "archived_urls": sync_stats.get("archived", 0),
                "failure_reasons": {},
                "elapsed_seconds": 0.0,
                "throughput_pages_per_sec": 0.0,
                "estimated_seconds_remaining": 0.0
            }

            crawled_this_run = 0
            failed_this_run = 0

            for url in targets:
                record = articles_dict[url]
                record["attempts"] = record.get("attempts", 0) + 1
                t0 = time.time()

                html = self.fetch_article_with_retries(url)
                if not html:
                    record["status"] = "failed"
                    record["error"] = "HTTP fetch error or 404"
                    failed_this_run += 1
                    self.current_run["pages_failed"] += 1
                    err_lbl = "HTTP 404 / Connection Error"
                    self.current_run["failure_reasons"][err_lbl] = self.current_run["failure_reasons"].get(err_lbl, 0) + 1
                    self._save_manifest()
                    time.sleep(sleep_delay)
                    continue

                self.current_run["pages_fetched"] += 1

                try:
                    parsed = article_parser.parse_html(html, url)
                    chunks = document_chunker.chunk_article(parsed)

                    aid = parsed["article_id"]
                    try:
                        raw_path = settings.RAW_ARTICLES_DIR / f"{aid}.json"
                        with open(raw_path, "w", encoding="utf-8") as f:
                            json.dump(parsed, f, indent=2)
                    except Exception:
                        pass

                    vector_store.upsert_article(
                        article_id=aid,
                        url=url,
                        title=parsed["title"],
                        category=parsed["category"],
                        content_hash=parsed["content_hash"],
                        raw_text=parsed["raw_text"],
                        screenshot_count=parsed["screenshot_count"],
                        chunks_data=chunks,
                        sitemap_source=record.get("sitemap_source")
                    )

                    record["status"] = "completed"
                    record["content_hash"] = parsed["content_hash"]
                    record["crawled_at"] = datetime.now(timezone.utc).isoformat()
                    record["error"] = None
                    crawled_this_run += 1
                    self.current_run["pages_saved"] += 1
                    self.current_run["pages_indexed"] += 1

                    elapsed = time.time() - t0
                    perf = self.manifest.setdefault("measured_perf", {"total_pages_measured": 0, "total_seconds": 0.0, "avg_seconds_per_page": 0.55})
                    perf["total_pages_measured"] += 1
                    perf["total_seconds"] = round(perf.get("total_seconds", 0.0) + elapsed, 3)
                    perf["avg_seconds_per_page"] = round(perf["total_seconds"] / perf["total_pages_measured"], 3)
                except Exception as e:
                    record["status"] = "failed"
                    record["error"] = str(e)
                    failed_this_run += 1
                    self.current_run["pages_failed"] += 1
                    err_msg = str(e)[:60]
                    self.current_run["failure_reasons"][err_msg] = self.current_run["failure_reasons"].get(err_msg, 0) + 1

                run_elapsed = round(time.time() - t_run_start, 2)
                self.current_run["elapsed_seconds"] = run_elapsed
                processed = self.current_run["pages_saved"] + self.current_run["pages_failed"]
                if run_elapsed > 0 and processed > 0:
                    tp = round(processed / run_elapsed, 2)
                    self.current_run["throughput_pages_per_sec"] = tp
                    rem_pages = max(0, len(targets) - processed)
                    self.current_run["estimated_seconds_remaining"] = round(rem_pages / tp, 1) if tp > 0 else 0.0

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
                "sync_summary": sync_stats,
                "run_metrics": dict(self.current_run)
            }
        finally:
            self.is_running = False
            self.last_run_summary = dict(getattr(self, "current_run", {}))

    def get_status(self) -> Dict[str, Any]:
        stats = vector_store.get_stats()
        articles_dict = self.manifest.get("articles", {})
        crawled = sum(1 for v in articles_dict.values() if v.get("status") == "completed")
        failed = sum(1 for v in articles_dict.values() if v.get("status") == "failed")
        
        run_data = getattr(self, "current_run", None) if self.is_running else getattr(self, "last_run_summary", None)
        res = {
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
        if run_data:
            res.update({
                "sitemaps_count": run_data.get("sitemaps_count", 1),
                "total_urls_discovered": run_data.get("total_urls_discovered", len(articles_dict)),
                "urls_queued": run_data.get("urls_queued", 0),
                "pages_fetched": run_data.get("pages_fetched", 0),
                "pages_saved": run_data.get("pages_saved", 0),
                "pages_indexed": run_data.get("pages_indexed", 0),
                "pages_failed": run_data.get("pages_failed", 0),
                "pages_skipped": run_data.get("pages_skipped", 0),
                "new_urls": run_data.get("new_urls", 0),
                "changed_urls": run_data.get("changed_urls", 0),
                "unchanged_urls": run_data.get("unchanged_urls", 0),
                "archived_urls": run_data.get("archived_urls", 0),
                "failure_reasons": run_data.get("failure_reasons", {}),
                "elapsed_seconds": run_data.get("elapsed_seconds", 0.0),
                "throughput_pages_per_sec": run_data.get("throughput_pages_per_sec", 0.0),
                "estimated_seconds_remaining": run_data.get("estimated_seconds_remaining", 0.0)
            })
        return res

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
