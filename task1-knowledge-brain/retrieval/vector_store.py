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
        self.db_path = str(db_path or settings.DB_PATH)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
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

vector_store = KnowledgeVectorStore()
