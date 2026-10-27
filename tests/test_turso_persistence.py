import os
import sys
import sqlite3
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Ensure project roots in path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "task1-knowledge-brain"))

from retrieval.vector_store import (
    KnowledgeVectorStore,
    DatabaseRow,
    LibsqlConnectionAdapter,
    LibsqlCursorAdapter
)

def test_database_row_compatibility():
    """Verify DatabaseRow supports both positional index and dict key access and dict() cast."""
    cols = ["id", "title", "score", "is_active"]
    values = ["art_01", "How to Setup Stripe", 0.95, 1]
    row = DatabaseRow(cols, values)
    
    # 1. Positional access
    assert row[0] == "art_01"
    assert row[1] == "How to Setup Stripe"
    assert row[2] == 0.95
    assert row[3] == 1
    
    # 2. Key access
    assert row["id"] == "art_01"
    assert row["title"] == "How to Setup Stripe"
    assert row["score"] == 0.95
    assert row["is_active"] == 1
    
    # 3. dict() conversion
    d = dict(row)
    assert d == {
        "id": "art_01",
        "title": "How to Setup Stripe",
        "score": 0.95,
        "is_active": 1
    }
    
    # 4. dict methods
    assert list(row.keys()) == cols
    assert list(row.values()) == values
    assert row.get("non_existent", "default") == "default"
    assert len(row) == 4

def test_production_missing_turso_token_raises():
    """Verify that in production (VERCEL set), setting TURSO_DATABASE_URL without token raises immediately."""
    with patch.dict(os.environ, {
        "VERCEL": "1",
        "TURSO_DATABASE_URL": "libsql://test-db.turso.io",
        "TURSO_AUTH_TOKEN": ""
    }, clear=False):
        with pytest.raises(RuntimeError, match="TURSO_AUTH_TOKEN is missing"):
            KnowledgeVectorStore()

def test_production_no_silent_fallback_on_connection_error():
    """Verify that when Turso connection fails in production, it fails safely with RuntimeError and does NOT silently fall back to /tmp."""
    with patch.dict(os.environ, {
        "VERCEL": "1",
        "TURSO_DATABASE_URL": "libsql://invalid-turso-endpoint.turso.io",
        "TURSO_AUTH_TOKEN": "invalid_token_xyz"
    }, clear=False):
        with pytest.raises(RuntimeError, match="Failed to connect to persistent Turso database"):
            KnowledgeVectorStore()

def test_storage_status_diagnostics_sanitizes_credentials():
    """Verify GET storage status reports accurate engine and masks credentials."""
    with patch.dict(os.environ, {
        "TURSO_DATABASE_URL": "libsql://ai-tech-consultant-harshith-02.aws-ap-south-1.turso.io",
        "TURSO_AUTH_TOKEN": "secret_jwt_token_123456789"
    }, clear=False):
        kvs = KnowledgeVectorStore()
        # Mock connection to verify status format
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {"version": "001_baseline_schema", "name": "001", "applied_at": "2026-10-23T00:00:00Z"},
            {"version": "002_multi_tenant_isolation", "name": "002", "applied_at": "2026-10-23T00:00:00Z"},
            {"version": "003_auth_and_sessions", "name": "003", "applied_at": "2026-10-23T00:00:00Z"}
        ]
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.__enter__.return_value = mock_conn
        
        with patch.object(kvs, "_get_connection", return_value=mock_conn):
            status = kvs.get_storage_status()
            assert status["engine"] == "turso_libsql"
            assert status["is_durable"] is True
            assert "secret_jwt_token" not in str(status)
            assert "secret_jwt_token" not in status.get("database_path", "")
            assert status["database_path"] == "libsql://ai-tech-consultant-harshith-02.aws-ap-south-1.turso.io"
            assert status["migrations_count"] == 3

def test_local_sqlite_is_labeled_separately_from_ephemeral():
    """Verify local SQLite path is reported as sqlite_local and durable locally."""
    with patch.dict(os.environ, {
        "TURSO_DATABASE_URL": "",
        "TURSO_AUTH_TOKEN": "",
        "VERCEL": ""
    }, clear=False):
        kvs = KnowledgeVectorStore(db_path=Path("task1-knowledge-brain/data/knowledge_brain.db"))
        status = kvs.get_storage_status()
        assert status["engine"] == "sqlite_local"
        assert status["is_durable"] is True

def test_ephemeral_storage_status_warning():
    """Verify ephemeral /tmp storage status is correctly flagged as not durable."""
    with patch.dict(os.environ, {
        "TURSO_DATABASE_URL": "",
        "TURSO_AUTH_TOKEN": "",
        "DB_PATH": "/tmp/test_ephemeral.db"
    }, clear=False):
        kvs = KnowledgeVectorStore(db_path=Path("/tmp/test_ephemeral.db"))
        status = kvs.get_storage_status()
        assert status["engine"] == "sqlite_ephemeral"
        assert status["is_durable"] is False
        assert any("CRITICAL" in r for r in status["recommendations"])

def test_libsql_adapter_with_fts5_and_transactions(tmp_path):
    """Test LibsqlConnectionAdapter with real file-backed libSQL client, FTS5 and atomic transactions."""
    import libsql_client
    db_file = tmp_path / "test_libsql_fts.db"
    client = libsql_client.create_client_sync(f"file:{db_file}")
    conn = LibsqlConnectionAdapter(client)
    
    with conn:
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE articles (id TEXT PRIMARY KEY, title TEXT)")
        cursor.execute("CREATE VIRTUAL TABLE chunks_fts USING fts5(chunk_id UNINDEXED, content)")
        cursor.execute("INSERT INTO articles VALUES (?, ?)", ("art_1", "Stripe Guide"))
        cursor.execute("INSERT INTO chunks_fts (chunk_id, content) VALUES (?, ?)", ("chk_1", "Stripe payment gateway integration"))
        
        # Test FTS5 match
        cursor.execute("SELECT chunk_id, rank FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY rank", ("stripe",))
        results = cursor.fetchall()
        assert len(results) == 1
        assert results[0]["chunk_id"] == "chk_1"
        assert results[0][0] == "chk_1"
        
        # Test dict conversion
        art_res = cursor.execute("SELECT * FROM articles WHERE id = ?", ("art_1",)).fetchone()
        assert dict(art_res) == {"id": "art_1", "title": "Stripe Guide"}
    
    client.close()
