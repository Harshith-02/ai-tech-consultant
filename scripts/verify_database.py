#!/usr/bin/env python3
"""
Database & Search Verification Script
------------------------------------
Verifies the persistent SQLite database, FTS5 index, 384-dim vector embeddings,
and hybrid search functionality for interview submission verification.

Run directly via:
    python scripts/verify_database.py
"""

import os
import sys
import json
import sqlite3
from pathlib import Path

# Setup paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "task1-knowledge-brain"))

from retrieval.vector_store import KnowledgeVectorStore
from retrieval.qa_engine import QAEngine

def run_verification():
    print("=" * 75)
    print("   AI TECH CONSULTANT - KNOWLEDGE BRAIN DATABASE & SEARCH AUDIT   ")
    print("=" * 75)
    
    db_path = PROJECT_ROOT / "task1-knowledge-brain" / "data" / "knowledge_brain.db"
    if not db_path.exists():
        print(f"[FAIL] Database file not found at: {db_path}")
        sys.exit(1)
        
    print(f"\n[1] Verifying Database File & Storage Engine...")
    print(f"    Path: {db_path}")
    print(f"    File Size: {db_path.stat().st_size:,} bytes")
    
    kvs = KnowledgeVectorStore(db_path=db_path)
    storage_status = kvs.get_storage_status()
    print(f"    Status: {storage_status.get('status')}")
    print(f"    Engine: {storage_status.get('engine')}")
    print(f"    Durable Local Storage: {storage_status.get('is_durable')}")
    print(f"    Journal Mode: {storage_status.get('journal_mode')}")
    print(f"    Migrations Applied: {storage_status.get('migrations_count')}")
    
    print("\n[2] Verifying Table Row Counts...")
    with kvs._get_connection() as conn:
        cursor = conn.cursor()
        
        counts = {}
        tables = [
            "sitemap_sources",
            "sitemap_urls",
            "articles",
            "chunks",
            "chunks_fts",
            "article_version_history",
            "archived_articles",
            "escalations",
            "autonomy_settings",
            "sent_emails",
            "feedback_rules",
            "email_audit_log"
        ]
        
        for table in tables:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                counts[table] = cursor.fetchone()[0]
                print(f"    - {table:<25}: {counts[table]:>5} rows")
            except Exception as e:
                print(f"    - {table:<25}: Error ({e})")
                
        # Embeddings integrity verification
        cursor.execute("SELECT COUNT(*) FROM chunks WHERE embedding_json IS NOT NULL AND length(embedding_json) > 10")
        valid_embeddings = cursor.fetchone()[0]
        cursor.execute("SELECT embedding_json FROM chunks WHERE embedding_json IS NOT NULL LIMIT 1")
        sample_emb = json.loads(cursor.fetchone()[0])
        emb_dim = len(sample_emb)
        print(f"\n[3] Verifying Vector Embeddings...")
        print(f"    - Chunks with valid embeddings: {valid_embeddings} / {counts.get('chunks', 0)}")
        print(f"    - Embedding dimension: {emb_dim}-dim (normalized)")
        assert valid_embeddings == counts.get("chunks", 0), "Mismatch: some chunks lack embeddings!"
        assert emb_dim == 384, f"Unexpected embedding dimension: {emb_dim}"
        print("    [PASS] All chunks have persisted 384-dimensional vector embeddings.")
        
        # Sources breakdown
        print(f"\n[4] Knowledge Sources & Sitemap Sources Breakdown:")
        cursor.execute("SELECT id, name, root_sitemap_url, status FROM sitemap_sources")
        for s in cursor.fetchall():
            cursor.execute("SELECT COUNT(*) FROM sitemap_urls WHERE source_id = ?", (s["id"],))
            url_cnt = cursor.fetchone()[0]
            print(f"    - Source: {s['name']} (ID: {s['id']})")
            print(f"      URL: {s['root_sitemap_url'] or '(custom)'} | Status: {s['status']} | Discovered URLs: {url_cnt}")
            
        print(f"\n[5] Ingested Articles by Source Sitemap:")
        cursor.execute("SELECT sitemap_source, COUNT(*) FROM articles GROUP BY sitemap_source")
        for r in cursor.fetchall():
            print(f"    - {r[0]}: {r[1]} articles")

    # [6] Test Hybrid Search: Brilliant Directories
    print("\n[6] Testing Hybrid Search: Brilliant Directories Query...")
    bd_query = "How do I import categories via CSV file in Brilliant Directories?"
    print(f"    Query: \"{bd_query}\"")
    bd_results = kvs.hybrid_search(bd_query, top_k=3)
    assert len(bd_results) > 0, "No results returned for Brilliant Directories query"
    top_bd = bd_results[0]
    print(f"    Top Match: \"{top_bd['title']}\"")
    print(f"    Section:   \"{top_bd['section']}\"")
    print(f"    URL:       {top_bd['url']}")
    print(f"    Score:     {top_bd['relevance']}")
    assert "brilliantdirectories.com" in top_bd["url"], f"Top BD result was not from Brilliant Directories: {top_bd['url']}"
    print("    [PASS] Returned authentic Brilliant Directories documentation.")

    # [7] Test Hybrid Search: Divi
    print("\n[7] Testing Hybrid Search: Divi Query...")
    divi_query = "How to download and install the Divi Builder plugin?"
    print(f"    Query: \"{divi_query}\"")
    divi_results = kvs.hybrid_search(divi_query, top_k=3)
    assert len(divi_results) > 0, "No results returned for Divi query"
    top_divi = divi_results[0]
    print(f"    Top Match: \"{top_divi['title']}\"")
    print(f"    Section:   \"{top_divi['section']}\"")
    print(f"    URL:       {top_divi['url']}")
    print(f"    Score:     {top_divi['relevance']}")
    assert "elegantthemes.com" in top_divi["url"], f"Top Divi result was not from Elegant Themes: {top_divi['url']}"
    print("    [PASS] Returned authentic Divi documentation.")

    # [8] End-to-End QA Engine Grounding & Citations
    print("\n[8] Testing End-to-End QA Engine Grounded Citations...")
    qa = QAEngine()
    bd_ans = qa.generate_answer(bd_query, top_k=2)
    print(f"    BD Query Answer Status: {bd_ans.status} (Confidence: {bd_ans.confidence:.2f})")
    print(f"    BD Citations: {[s.url for s in bd_ans.sources]}")
    assert any("brilliantdirectories.com" in s.url for s in bd_ans.sources)

    divi_ans = qa.generate_answer(divi_query, top_k=2)
    print(f"    Divi Query Answer Status: {divi_ans.status} (Confidence: {divi_ans.confidence:.2f})")
    print(f"    Divi Citations: {[s.url for s in divi_ans.sources]}")
    assert any("elegantthemes.com" in s.url for s in divi_ans.sources)

    print("\n" + "=" * 75)
    print("   [SUCCESS] ALL DATABASE & HYBRID RETRIEVAL VERIFICATIONS PASSED!   ")
    print("=" * 75)

if __name__ == "__main__":
    run_verification()
