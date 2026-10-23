import os
import sqlite3
import json
import uuid
import re
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from pathlib import Path
from app.config import settings
from retrieval.embeddings import embedding_engine

DOMAIN_STOP_WORDS = {
    "brilliant", "directories", "directory", "support", "solutions", "articles", "article",
    "how", "what", "where", "when", "does", "with", "from", "into", "your", "their",
    "this", "that", "tell", "show", "can", "please", "using", "work", "make", "take",
    "help", "system", "override", "ignore", "previous", "instructions", "many", "much"
}

class KnowledgeVectorStore:
    def __init__(self, db_path: Optional[Path] = None):
        env_db = os.environ.get("DB_PATH")
        self.db_path = str(env_db or db_path or settings.DB_PATH)
        try:
            self._init_db()
        except Exception:
            pass

    def _get_connection(self) -> sqlite3.Connection:
        try:
            conn = sqlite3.connect(self.db_path)
        except Exception:
            conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS articles (
                id TEXT PRIMARY KEY,
                url TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                category TEXT,
                content_hash TEXT,
                raw_text TEXT,
                screenshot_count INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """)

            # Safe migration: ensure sitemap_source column exists on articles
            cursor.execute("PRAGMA table_info(articles)")
            cols = [col[1] for col in cursor.fetchall()]
            if "sitemap_source" not in cols:
                try:
                    cursor.execute("ALTER TABLE articles ADD COLUMN sitemap_source TEXT")
                except Exception:
                    pass

            cursor.execute("""
            CREATE TABLE IF NOT EXISTS chunks (
                id TEXT PRIMARY KEY,
                article_id TEXT NOT NULL,
                url TEXT NOT NULL,
                article_title TEXT NOT NULL,
                section_heading TEXT,
                content TEXT NOT NULL,
                image_urls TEXT,
                image_descriptions TEXT,
                embedding_json TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TEXT NOT NULL,
                FOREIGN KEY (article_id) REFERENCES articles(id)
            );
            """)

            cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                chunk_id UNINDEXED,
                article_title,
                section_heading,
                content,
                image_descriptions,
                tokenize='porter unicode61'
            );
            """)

            cursor.execute("""
            CREATE TABLE IF NOT EXISTS escalations (
                id TEXT PRIMARY KEY,
                question TEXT NOT NULL,
                status TEXT NOT NULL,
                user_email TEXT,
                reason TEXT,
                expert_answer TEXT,
                supporting_notes TEXT,
                approved_by TEXT,
                created_at TEXT NOT NULL,
                resolved_at TEXT
            );
            """)

            cursor.execute("""
            CREATE TABLE IF NOT EXISTS archived_articles (
                id TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                title TEXT NOT NULL,
                category TEXT,
                content_hash TEXT,
                raw_text TEXT,
                sitemap_source TEXT,
                consecutive_missing_checks INTEGER DEFAULT 0,
                archived_at TEXT NOT NULL,
                reason TEXT
            );
            """)

            cursor.execute("""
            CREATE TABLE IF NOT EXISTS sitemap_sources (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                root_sitemap_url TEXT UNIQUE NOT NULL,
                is_enabled INTEGER DEFAULT 1,
                refresh_enabled INTEGER DEFAULT 1,
                refresh_interval_days INTEGER DEFAULT 7,
                missing_threshold INTEGER DEFAULT 15,
                last_checked_at TEXT,
                last_successful_refresh_at TEXT,
                next_check_at TEXT,
                status TEXT DEFAULT 'active',
                error_summary TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """)

            cursor.execute("""
            CREATE TABLE IF NOT EXISTS sitemap_urls (
                id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                url TEXT NOT NULL,
                normalized_url TEXT NOT NULL,
                lastmod TEXT,
                etag TEXT,
                content_hash TEXT,
                consecutive_missing_checks INTEGER DEFAULT 0,
                status TEXT DEFAULT 'active',
                last_seen_at TEXT,
                last_checked_at TEXT,
                last_indexed_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (source_id) REFERENCES sitemap_sources(id),
                UNIQUE(source_id, normalized_url)
            );
            """)

            cursor.execute("""
            CREATE TABLE IF NOT EXISTS sitemap_refresh_runs (
                id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                status TEXT NOT NULL,
                discovery_complete INTEGER DEFAULT 0,
                sitemaps_discovered INTEGER DEFAULT 0,
                sitemaps_succeeded INTEGER DEFAULT 0,
                sitemaps_failed INTEGER DEFAULT 0,
                urls_discovered INTEGER DEFAULT 0,
                new_urls INTEGER DEFAULT 0,
                changed_urls INTEGER DEFAULT 0,
                missing_urls INTEGER DEFAULT 0,
                urls_archived INTEGER DEFAULT 0,
                pages_fetched INTEGER DEFAULT 0,
                pages_failed INTEGER DEFAULT 0,
                pages_indexed INTEGER DEFAULT 0,
                error_summary TEXT,
                details_json TEXT,
                FOREIGN KEY (source_id) REFERENCES sitemap_sources(id)
            );
            """)

            cursor.execute("""
            CREATE TABLE IF NOT EXISTS gmail_accounts (
                id TEXT PRIMARY KEY,
                email_address TEXT UNIQUE NOT NULL,
                connection_status TEXT DEFAULT 'connected',
                scopes TEXT,
                encrypted_access_token TEXT,
                encrypted_refresh_token TEXT,
                token_expiry TEXT,
                history_id TEXT,
                last_sync_at TEXT,
                last_sync_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """)

            cursor.execute("""
            CREATE TABLE IF NOT EXISTS email_audit_log (
                id TEXT PRIMARY KEY,
                account_id TEXT,
                email_id TEXT,
                event_type TEXT NOT NULL,
                actor_type TEXT NOT NULL,
                decision TEXT,
                reason TEXT,
                metadata_json TEXT,
                created_at TEXT NOT NULL
            );
            """)

            # Seed default documentation source if empty
            cursor.execute("SELECT COUNT(*) FROM sitemap_sources")
            if cursor.fetchone()[0] == 0:
                now_str = datetime.now(timezone.utc).isoformat()
                cursor.execute("""
                INSERT INTO sitemap_sources (id, name, root_sitemap_url, is_enabled, refresh_enabled, refresh_interval_days, missing_threshold, status, created_at, updated_at)
                VALUES ('src_default_bd', 'Brilliant Directories Documentation', 'https://support.brilliantdirectories.com/support/sitemap.xml', 1, 1, 7, 15, 'active', ?, ?)
                """, (now_str, now_str))

            conn.commit()

    def upsert_article(
        self,
        article_id: str,
        url: str,
        title: str,
        category: str,
        content_hash: str,
        raw_text: str,
        screenshot_count: int,
        chunks_data: List[Dict[str, Any]]
    ):
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
            INSERT INTO articles (id, url, title, category, content_hash, raw_text, screenshot_count, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title=excluded.title,
                category=excluded.category,
                content_hash=excluded.content_hash,
                raw_text=excluded.raw_text,
                screenshot_count=excluded.screenshot_count,
                is_active=1,
                updated_at=excluded.updated_at;
            """, (article_id, url, title, category, content_hash, raw_text, screenshot_count, now, now))

            cursor.execute("SELECT id FROM chunks WHERE article_id = ?", (article_id,))
            old_chunk_ids = [row["id"] for row in cursor.fetchall()]
            for cid in old_chunk_ids:
                cursor.execute("DELETE FROM chunks_fts WHERE chunk_id = ?", (cid,))
            cursor.execute("DELETE FROM chunks WHERE article_id = ?", (article_id,))

            for i, chunk in enumerate(chunks_data):
                cid = f"{article_id}_chunk_{i}"
                content = chunk.get("content", "")
                section = chunk.get("section_heading", "General")
                img_urls = json.dumps(chunk.get("image_urls", []))
                img_descs = json.dumps(chunk.get("image_descriptions", []))
                img_desc_text = " ".join(chunk.get("image_descriptions", []))
                
                text_to_embed = f"{title}\n{section}\n{content}\n{img_desc_text}"
                embedding = embedding_engine.get_embedding(text_to_embed)
                emb_json = json.dumps(embedding)

                cursor.execute("""
                INSERT INTO chunks (id, article_id, url, article_title, section_heading, content, image_urls, image_descriptions, embedding_json, is_active, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                """, (cid, article_id, url, title, section, content, img_urls, img_descs, emb_json, now))

                cursor.execute("""
                INSERT INTO chunks_fts (chunk_id, article_title, section_heading, content, image_descriptions)
                VALUES (?, ?, ?, ?, ?)
                """, (cid, title, section, content, img_desc_text))

            conn.commit()

    def deactivate_article(self, url: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM articles WHERE url = ?", (url,))
            row = cursor.fetchone()
            if not row:
                return False
            article_id = row["id"]

            cursor.execute("UPDATE articles SET is_active = 0 WHERE id = ?", (article_id,))
            cursor.execute("UPDATE chunks SET is_active = 0 WHERE article_id = ?", (article_id,))
            
            cursor.execute("SELECT id FROM chunks WHERE article_id = ?", (article_id,))
            for r in cursor.fetchall():
                cursor.execute("DELETE FROM chunks_fts WHERE chunk_id = ?", (r["id"],))

            conn.commit()
            return True

    def archive_article(self, url: str, reason: str = "Missing from sitemap across configured consecutive checks", checks_count: int = 15) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, url, title, category, content_hash, raw_text FROM articles WHERE url = ?", (url,))
            row = cursor.fetchone()
            article_id = row["id"] if row else f"archived_{uuid.uuid4().hex[:8]}"
            title = row["title"] if row else url.split("/")[-1].replace("-", " ").title()
            cat = row["category"] if row else "General"
            chash = row["content_hash"] if row else None
            rtext = row["raw_text"] if row else None
            now = datetime.now(timezone.utc).isoformat()
            cursor.execute("""
            INSERT OR REPLACE INTO archived_articles (id, url, title, category, content_hash, raw_text, consecutive_missing_checks, archived_at, reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (article_id, url, title, cat, chash, rtext, checks_count, now, reason))

            # Deactivate in active knowledge base #1
            cursor.execute("UPDATE articles SET is_active = 0, updated_at = ? WHERE id = ?", (now, article_id))
            cursor.execute("UPDATE chunks SET is_active = 0 WHERE article_id = ?", (article_id,))
            cursor.execute("SELECT id FROM chunks WHERE article_id = ?", (article_id,))
            for r in cursor.fetchall():
                cursor.execute("DELETE FROM chunks_fts WHERE chunk_id = ?", (r["id"],))

            conn.commit()
            return True

    def get_archived_articles(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM archived_articles ORDER BY archived_at DESC LIMIT ?", (limit,))
            return [dict(r) for r in cursor.fetchall()]

    def create_sitemap_source(
        self,
        name: str,
        root_url: str,
        refresh_interval_days: int = 7,
        missing_threshold: int = 15
    ) -> Dict[str, Any]:
        src_id = f"src_{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO sitemap_sources (id, name, root_sitemap_url, is_enabled, refresh_enabled, refresh_interval_days, missing_threshold, status, created_at, updated_at)
            VALUES (?, ?, ?, 1, 1, ?, ?, 'active', ?, ?)
            """, (src_id, name, root_url, refresh_interval_days, missing_threshold, now, now))
            conn.commit()
        return self.get_sitemap_source(src_id)

    def list_sitemap_sources(self) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM sitemap_sources ORDER BY created_at ASC")
            sources = [dict(r) for r in cursor.fetchall()]
            for s in sources:
                try:
                    cursor.execute("SELECT COUNT(*) FROM articles WHERE sitemap_source = ? AND is_active = 1", (s["root_sitemap_url"],))
                    s["active_articles_count"] = cursor.fetchone()[0]
                except Exception:
                    s["active_articles_count"] = 0
            return sources

    def get_sitemap_source(self, source_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM sitemap_sources WHERE id = ? OR root_sitemap_url = ?", (source_id, source_id))
            row = cursor.fetchone()
            if not row:
                return None
            res = dict(row)
            try:
                cursor.execute("SELECT COUNT(*) FROM articles WHERE sitemap_source = ? AND is_active = 1", (res["root_sitemap_url"],))
                res["active_articles_count"] = cursor.fetchone()[0]
            except Exception:
                res["active_articles_count"] = 0
            return res

    def update_sitemap_source(self, source_id: str, **kwargs) -> Optional[Dict[str, Any]]:
        valid_keys = {"name", "is_enabled", "refresh_enabled", "refresh_interval_days", "missing_threshold", "status", "last_checked_at", "last_successful_refresh_at", "next_check_at", "error_summary"}
        updates = {k: v for k, v in kwargs.items() if k in valid_keys}
        if not updates:
            return self.get_sitemap_source(source_id)
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
        values = list(updates.values()) + [source_id]
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"UPDATE sitemap_sources SET {set_clause} WHERE id = ?", values)
            conn.commit()
        return self.get_sitemap_source(source_id)

    def delete_sitemap_source(self, source_id: str, purge_content: bool = False) -> bool:
        src = self.get_sitemap_source(source_id)
        if not src:
            return False
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if purge_content:
                try:
                    # Cross-source safety rule: only deactivate content if no other active source references it
                    cursor.execute("SELECT url FROM articles WHERE sitemap_source = ?", (src["root_sitemap_url"],))
                    urls = [r[0] for r in cursor.fetchall()]
                    for u in urls:
                        cursor.execute("SELECT COUNT(*) FROM articles WHERE url = ? AND sitemap_source != ? AND is_active = 1", (u, src["root_sitemap_url"]))
                        shared_count = cursor.fetchone()[0]
                        if shared_count == 0:
                            self.archive_article(u, reason=f"Sitemap source '{src['name']}' deleted by user")
                except Exception:
                    pass
            cursor.execute("DELETE FROM sitemap_sources WHERE id = ?", (source_id,))
            conn.commit()
            return True

    def record_refresh_run(self, source_id: str, **kwargs) -> str:
        run_id = f"run_{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc).isoformat()
        cols = ["id", "source_id", "started_at", "status"]
        vals = [run_id, source_id, kwargs.get("started_at", now), kwargs.get("status", "completed")]
        for k, v in kwargs.items():
            if k not in ["id", "source_id", "started_at", "status"] and k in [
                "completed_at", "discovery_complete", "sitemaps_discovered", "sitemaps_succeeded", "sitemaps_failed",
                "urls_discovered", "new_urls", "changed_urls", "missing_urls", "urls_archived", "pages_fetched", "pages_failed", "pages_indexed", "error_summary", "details_json"
            ]:
                cols.append(k)
                vals.append(v)
        placeholders = ", ".join("?" for _ in cols)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"INSERT INTO sitemap_refresh_runs ({', '.join(cols)}) VALUES ({placeholders})", vals)
            conn.commit()
        return run_id

    def list_refresh_runs(self, source_id: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if source_id:
                cursor.execute("SELECT * FROM sitemap_refresh_runs WHERE source_id = ? ORDER BY started_at DESC LIMIT ?", (source_id, limit))
            else:
                cursor.execute("SELECT * FROM sitemap_refresh_runs ORDER BY started_at DESC LIMIT ?", (limit,))
            return [dict(r) for r in cursor.fetchall()]

    def hybrid_search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        query_cleaned = query.strip()
        if not query_cleaned:
            return []

        clean_fts_query = "".join(c if c.isalnum() or c.isspace() else " " for c in query_cleaned.lower())
        raw_tokens = [t for t in clean_fts_query.split() if len(t) >= 3]
        substantive_tokens = [t for t in raw_tokens if t not in DOMAIN_STOP_WORDS]

        if not substantive_tokens:
            return []

        q_embedding = embedding_engine.get_embedding(query_cleaned)
        fts_ranks: Dict[str, int] = {}

        with self._get_connection() as conn:
            cursor = conn.cursor()
            fts_query_str = " OR ".join(substantive_tokens)
            try:
                cursor.execute("""
                SELECT chunk_id, rank
                FROM chunks_fts
                WHERE chunks_fts MATCH ?
                ORDER BY rank
                LIMIT 30;
                """, (fts_query_str,))
                for idx, row in enumerate(cursor.fetchall()):
                    fts_ranks[row["chunk_id"]] = idx + 1
            except sqlite3.OperationalError:
                pass

            cursor.execute("""
            SELECT id, article_id, url, article_title, section_heading, content,
                   image_urls, image_descriptions, embedding_json
            FROM chunks
            WHERE is_active = 1
            """)
            chunks = cursor.fetchall()

        if not chunks:
            return []

        chunk_map = {}
        dense_sims: Dict[str, float] = {}

        for c in chunks:
            cid = c["id"]
            chunk_map[cid] = c
            emb_str = c["embedding_json"]
            if emb_str:
                emb = json.loads(emb_str)
                sim = embedding_engine.cosine_similarity(q_embedding, emb)
            else:
                sim = 0.0
            dense_sims[cid] = sim

        candidate_scores = []
        for cid, c in chunk_map.items():
            sim = dense_sims.get(cid, 0.0)
            has_fts = cid in fts_ranks

            full_text = f"{c['article_title']} {c['section_heading']} {c['content']}".lower()
            keyword_hits = sum(1 for t in substantive_tokens if t in full_text)

            # Require at least 1 keyword hit if 1-2 substantive tokens, or at least 2 if >= 3 tokens
            min_required_hits = 1 if len(substantive_tokens) <= 2 else 2
            if keyword_hits < min_required_hits:
                continue

            hit_ratio = keyword_hits / len(substantive_tokens)
            calibrated_relevance = (sim * 0.3) + (hit_ratio * 0.7)

            if calibrated_relevance >= settings.MIN_RELEVANCE_SCORE:
                candidate_scores.append((cid, calibrated_relevance, c))

        if not candidate_scores:
            return []

        candidate_scores.sort(key=lambda x: x[1], reverse=True)
        top_candidates = candidate_scores[:top_k]

        final_chunks = []
        for cid, relevance, c in top_candidates:
            final_chunks.append({
                "chunk_id": cid,
                "article_id": c["article_id"],
                "url": c["url"],
                "title": c["article_title"],
                "section": c["section_heading"],
                "content": c["content"],
                "image_urls": json.loads(c["image_urls"]) if c["image_urls"] else [],
                "image_descriptions": json.loads(c["image_descriptions"]) if c["image_descriptions"] else [],
                "relevance": round(float(relevance), 3)
            })

        return final_chunks

    search = hybrid_search

    def create_escalation(self, question: str, user_email: Optional[str] = None, reason: str = "Insufficient evidence") -> str:
        esc_id = f"ESC-{uuid.uuid4().hex[:8].upper()}"
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO escalations (id, question, status, user_email, reason, created_at)
            VALUES (?, ?, 'pending', ?, ?, ?)
            """, (esc_id, question, user_email, reason, now))
            conn.commit()
        return esc_id

    def list_escalations(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if status:
                cursor.execute("SELECT * FROM escalations WHERE status = ? ORDER BY created_at DESC", (status,))
            else:
                cursor.execute("SELECT * FROM escalations ORDER BY created_at DESC")
            return [dict(row) for row in cursor.fetchall()]

    def resolve_escalation(self, esc_id: str, expert_answer: str, supporting_notes: Optional[str], approved_by: str) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM escalations WHERE id = ?", (esc_id,))
            row = cursor.fetchone()
            if not row:
                return False

            cursor.execute("""
            UPDATE escalations
            SET status = 'resolved', expert_answer = ?, supporting_notes = ?, approved_by = ?, resolved_at = ?
            WHERE id = ?
            """, (expert_answer, supporting_notes, approved_by, now, esc_id))
            conn.commit()

        expert_chunk = {
            "section_heading": f"Expert Answer: {row['question'][:60]}",
            "content": f"Question: {row['question']}\n\nExpert Answer: {expert_answer}\n\nNotes: {supporting_notes or 'Verified by ' + approved_by}",
            "image_urls": [],
            "image_descriptions": []
        }
        self.upsert_article(
            article_id=f"expert_{esc_id}",
            url=f"https://support.brilliantdirectories.com/support/expert-answers/{esc_id}",
            title=f"Expert Verified: {row['question']}",
            category="Expert Resolution",
            content_hash=f"hash_{esc_id}",
            raw_text=expert_answer,
            screenshot_count=0,
            chunks_data=[expert_chunk]
        )
        return True

    def get_stats(self) -> Dict[str, Any]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM articles WHERE is_active = 1")
            active_articles = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM chunks WHERE is_active = 1")
            active_chunks = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM escalations WHERE status = 'pending'")
            pending_escalations = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM escalations WHERE status = 'resolved'")
            resolved_escalations = cursor.fetchone()[0]
            return {
                "active_articles": active_articles,
                "active_chunks": active_chunks,
                "pending_escalations": pending_escalations,
                "resolved_escalations": resolved_escalations
            }

    # =========================================================================
    # GMAIL ACCOUNTS & AUDIT LOGGING (UPGRADE B)
    # =========================================================================
    def save_gmail_account(
        self,
        email_address: str,
        encrypted_access_token: str,
        encrypted_refresh_token: str,
        token_expiry: Optional[str] = None,
        scopes: Optional[str] = None
    ) -> Dict[str, Any]:
        acc_id = f"acc_{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM gmail_accounts WHERE email_address = ?", (email_address,))
            row = cursor.fetchone()
            if row:
                acc_id = row["id"]
                cursor.execute("""
                UPDATE gmail_accounts
                SET connection_status = 'connected',
                    encrypted_access_token = ?,
                    encrypted_refresh_token = COALESCE(?, encrypted_refresh_token),
                    token_expiry = ?,
                    scopes = ?,
                    updated_at = ?
                WHERE id = ?
                """, (encrypted_access_token, encrypted_refresh_token, token_expiry, scopes, now, acc_id))
            else:
                cursor.execute("""
                INSERT INTO gmail_accounts (
                    id, email_address, connection_status, scopes,
                    encrypted_access_token, encrypted_refresh_token,
                    token_expiry, created_at, updated_at
                ) VALUES (?, ?, 'connected', ?, ?, ?, ?, ?, ?)
                """, (acc_id, email_address, scopes, encrypted_access_token, encrypted_refresh_token, token_expiry, now, now))
            conn.commit()
        return self.get_gmail_account(acc_id)

    def get_gmail_account(self, account_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM gmail_accounts WHERE id = ? OR email_address = ?", (account_id, account_id))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_active_gmail_account(self) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM gmail_accounts WHERE connection_status = 'connected' ORDER BY updated_at DESC LIMIT 1")
            row = cursor.fetchone()
            return dict(row) if row else None

    def disconnect_gmail_account(self, account_id_or_email: str) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            UPDATE gmail_accounts
            SET connection_status = 'disconnected',
                encrypted_access_token = NULL,
                updated_at = ?
            WHERE id = ? OR email_address = ?
            """, (now, account_id_or_email, account_id_or_email))
            conn.commit()
            return cursor.rowcount > 0

    def update_gmail_sync(self, account_id: str, history_id: Optional[str] = None, error: Optional[str] = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            UPDATE gmail_accounts
            SET last_sync_at = ?, history_id = COALESCE(?, history_id), last_sync_error = ?, updated_at = ?
            WHERE id = ?
            """, (now, history_id, error, now, account_id))
            conn.commit()

    def record_email_audit(
        self,
        event_type: str,
        actor_type: str = "system",
        decision: Optional[str] = None,
        reason: Optional[str] = None,
        email_id: Optional[str] = None,
        account_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        audit_id = f"aud_{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc).isoformat()
        meta_json = json.dumps(metadata) if metadata else None
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO email_audit_log (id, account_id, email_id, event_type, actor_type, decision, reason, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (audit_id, account_id, email_id, event_type, actor_type, decision, reason, meta_json, now))
            conn.commit()
        return audit_id

    def get_email_audit_logs(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM email_audit_log ORDER BY created_at DESC LIMIT ?", (limit,))
            return [dict(r) for r in cursor.fetchall()]

vector_store = KnowledgeVectorStore()

