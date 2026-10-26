"""
tests/test_turso_migration_isolated.py
======================================
Isolated tests for Turso / libSQL migration tool (scripts/migrate_to_turso.py).
Tests schema creation, versioned migrations (001-005), data reconciliation,
embedding preservation, repeat-run idempotency, and fail-closed target handling.

All tests operate strictly on disposable synthetic databases in tmp_path.
The original application database is never read, modified, or targeted.
"""

import os
import sys
import json
import sqlite3
import pytest
from pathlib import Path
from unittest.mock import patch

# Ensure repo root is discoverable
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "task1-knowledge-brain"))

from scripts.migrate_to_turso import migrate_database, MIGRATION_TABLES, MIGRATION_DDL
from retrieval.vector_store import KnowledgeVectorStore, hash_password
import libsql_client


# -----------------------------------------------------------------------------
# 1. Target Handling & Fail-Closed Validation Tests
# -----------------------------------------------------------------------------
def test_migration_fails_closed_when_destination_is_missing():
    """Verify migrate_database raises ValueError when live migration lacks destination."""
    with pytest.raises(ValueError, match="Invalid destination URL scheme"):
        migrate_database("task1-knowledge-brain/data/knowledge_brain.db", "", dry_run=False)


def test_migration_fails_closed_for_remote_destination_without_token():
    """Verify remote Turso URLs fail closed if auth token is missing."""
    with pytest.raises(ValueError, match="requires TURSO_AUTH_TOKEN"):
        migrate_database(
            "task1-knowledge-brain/data/knowledge_brain.db",
            "libsql://ai-tech-consultant.turso.io",
            turso_token="",
            dry_run=False
        )


def test_migration_fails_closed_for_missing_source_file():
    """Verify migrate_database raises FileNotFoundError if source DB does not exist."""
    with pytest.raises(FileNotFoundError, match="Source database file not found"):
        migrate_database("non_existent_source_path.db", "file:dest.db", dry_run=False)


# -----------------------------------------------------------------------------
# 2. End-to-End Isolated Migration with Synthetic Data Fixture
# -----------------------------------------------------------------------------
def test_isolated_synthetic_migration_end_to_end(tmp_path):
    """
    Creates a disposable source database using synthetic fixtures,
    migrates it to a disposable libSQL file-backed destination,
    and asserts complete schema, data, embedding, and FTS5 integrity.
    """
    src_db = tmp_path / "synthetic_source.db"
    dest_db = tmp_path / "synthetic_dest.db"

    # Initialize synthetic source schema and tables via KnowledgeVectorStore
    kvs = KnowledgeVectorStore(db_path=src_db)

    # 1. Populate synthetic non-sensitive records
    now_iso = "2026-10-26T12:00:00+00:00"
    with sqlite3.connect(src_db) as conn:
        c = conn.cursor()

        # Synthetic Article
        c.execute("""
            INSERT INTO articles (id, url, title, category, content_hash, raw_text, screenshot_count, is_active, sitemap_source, created_at, updated_at, account_id)
            VALUES ('art_synth_01', 'https://example.com/synth-stripe', 'Stripe Setup Guide', 'billing', 'hash_01', 'Full setup instructions for Stripe payment gateway.', 0, 1, 'src_synth', ?, ?, 'acc_synth')
        """, (now_iso, now_iso))

        # Synthetic Chunk with 384-dimensional normalized vector
        synth_vector = [0.051] * 384
        c.execute("""
            INSERT INTO chunks (id, article_id, url, article_title, section_heading, content, image_urls, image_descriptions, embedding_json, is_active, created_at, account_id)
            VALUES ('chk_synth_01', 'art_synth_01', 'https://example.com/synth-stripe', 'Stripe Setup Guide', 'Connecting API Keys', 'Enter your secret key in the admin billing settings page.', '[]', '[]', ?, 1, ?, 'acc_synth')
        """, (json.dumps(synth_vector), now_iso))

        # Synthetic Escalation
        c.execute("""
            INSERT INTO escalations (id, question, status, user_email, reason, expert_answer, supporting_notes, approved_by, created_at, account_id)
            VALUES ('esc_synth_01', 'Can I refund a deposit?', 'pending', 'user@example.com', 'insufficient_evidence', NULL, NULL, NULL, ?, 'acc_synth')
        """, (now_iso,))

        # Synthetic User Account and User (with Bcrypt password hash)
        c.execute("""
            INSERT INTO user_accounts (id, name, plan, created_at)
            VALUES ('acc_synth', 'Synthetic Test Org', 'enterprise', ?)
        """, (now_iso,))

        synth_bcrypt_hash = hash_password("synthetic_password_2026")
        c.execute("""
            INSERT INTO users (id, account_id, email, password_hash, role, created_at)
            VALUES ('usr_synth_01', 'acc_synth', 'tester@synthetic.io', ?, 'Lead AI Consultant', ?)
        """, (synth_bcrypt_hash, now_iso))

        # Synthetic Revoked Token
        c.execute("""
            INSERT INTO revoked_tokens (jti, account_id, user_id, revoked_at, expires_at)
            VALUES ('jti_synth_01', 'acc_synth', 'usr_synth_01', ?, '2026-10-27T12:00:00+00:00')
        """, (now_iso,))

        # Synthetic Feedback Rule
        c.execute("""
            INSERT INTO feedback_rules (id, category, email_id, rule_text, original_draft, final_sent, diff_summary, account_id, created_at)
            VALUES ('fb_synth_01', 'billing', 'EM-SYNTH-01', 'Supervisor prefers concise billing explanations', 'Draft body', 'Final body', 'Diff', 'acc_synth', ?)
        """, (now_iso,))

        # Synthetic Sent Email
        c.execute("""
            INSERT INTO sent_emails (id, email_id, recipient, subject, body, category, is_autonomous, gmail_message_id, created_at, account_id)
            VALUES ('sent_synth_01', 'EM-SYNTH-01', 'customer@example.com', 'Re: Billing', 'Here is how to configure billing', 'billing', 0, 'mock_msg_01', ?, 'acc_synth')
        """, (now_iso,))

        # Synthetic Email Audit Log
        c.execute("""
            INSERT INTO email_audit_log (id, account_id, email_id, event_type, actor_type, decision, reason, metadata_json, created_at)
            VALUES ('aud_synth_01', 'acc_synth', 'EM-SYNTH-01', 'draft_approved_and_sent', 'user', 'approved', 'Manual approval', '{}', ?)
        """, (now_iso,))

        # Synthetic Rate Limit Timestamp
        c.execute("""
            INSERT INTO rate_limits (key, timestamp)
            VALUES ('rate_synth_key', 1700000000.0)
        """)

        conn.commit()

    # 2. Execute migration targeting disposable libSQL destination
    dest_url = f"file:{dest_db}"
    result = migrate_database(str(src_db), dest_url, turso_token="", dry_run=False)

    assert result["status"] == "success"
    assert result["fts_count"] >= 1

    # 3. Verify destination database integrity using direct libSQL client
    client = libsql_client.create_client_sync(dest_url)

    # A. Verify all 5 schema migrations are recorded
    mig_res = client.execute("SELECT version, name FROM schema_migrations ORDER BY version")
    mig_versions = [row[0] for row in mig_res.rows]
    assert "001_baseline_schema" in mig_versions
    assert "002_multi_tenant_isolation" in mig_versions
    assert "003_auth_and_sessions" in mig_versions
    assert "004_secure_password_hashing" in mig_versions
    assert "005_durable_rate_limits" in mig_versions

    # B. Verify tables exist and row counts match synthetic source
    art_res = client.execute("SELECT COUNT(*) FROM articles")
    assert art_res.rows[0][0] >= 1

    chk_res = client.execute("SELECT COUNT(*) FROM chunks")
    assert chk_res.rows[0][0] >= 1

    rate_res = client.execute("SELECT COUNT(*) FROM rate_limits")
    assert rate_res.rows[0][0] >= 1

    # C. Verify embedding preservation (384 dimensions intact)
    chunk_row = client.execute("SELECT id, embedding_json FROM chunks WHERE id = 'chk_synth_01'")
    assert len(chunk_row.rows) == 1
    loaded_vector = json.loads(chunk_row.rows[0][1])
    assert len(loaded_vector) == 384
    assert loaded_vector[0] == pytest.approx(0.051)

    # D. Verify Bcrypt password preservation
    user_row = client.execute("SELECT id, email, password_hash FROM users WHERE id = 'usr_synth_01'")
    assert len(user_row.rows) == 1
    assert user_row.rows[0][1] == "tester@synthetic.io"
    assert user_row.rows[0][2].startswith("$2b$")

    # E. Verify FTS5 search on destination
    fts_search = client.execute("SELECT chunk_id, rank FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY rank", ["billing"])
    assert len(fts_search.rows) >= 1

    client.close()


# -----------------------------------------------------------------------------
# 3. Repeat-Run Idempotency & Rate Limit Reconciliation Test
# -----------------------------------------------------------------------------
def test_isolated_migration_repeat_run_idempotency(tmp_path):
    """Verify running migration a second time succeeds without duplicating rows, including rate_limits."""
    src_db = tmp_path / "idempotent_src.db"
    dest_db = tmp_path / "idempotent_dest.db"

    # Setup synthetic source
    KnowledgeVectorStore(db_path=src_db)
    with sqlite3.connect(src_db) as conn:
        conn.execute("INSERT INTO rate_limits (key, timestamp) VALUES ('rl_key_1', 1700000000.0)")
        conn.execute("INSERT INTO rate_limits (key, timestamp) VALUES ('rl_key_1', 1700000000.0)")  # legitimate identical timestamp
        conn.execute("INSERT INTO rate_limits (key, timestamp) VALUES ('rl_key_2', 1700000001.0)")
        conn.commit()

    dest_url = f"file:{dest_db}"

    # First migration run
    res1 = migrate_database(str(src_db), dest_url, turso_token="", dry_run=False)
    assert res1["status"] == "success"

    # Second migration run (idempotency check)
    res2 = migrate_database(str(src_db), dest_url, turso_token="", dry_run=False)
    assert res2["status"] == "success"

    # Verify counts did not double
    client = libsql_client.create_client_sync(dest_url)
    migs = client.execute("SELECT COUNT(*) FROM schema_migrations")
    assert migs.rows[0][0] == 5  # Exactly 5 migration versions

    rl_res = client.execute("SELECT COUNT(*) FROM rate_limits")
    assert rl_res.rows[0][0] == 3  # Exactly 3 records; zero duplicate appending

    client.close()


def test_rate_limits_seven_reconciliation_scenarios(tmp_path):
    """
    Test all 7 rate-limit reconciliation scenarios on disposable databases:
    1. First migration with multiple rows + identical (key, timestamp) pairs
    2. Repeat migration without duplicate rows
    3. Adding new source rows between runs
    4. Removing source row (migration is additive and flags count mismatch)
    5. Interrupted migration retry (missing records inserted without re-duplicating)
    6. Destination has extra rows (detected as count divergence, fails closed)
    7. Equal counts but different contents (detected through content divergence, fails closed)
    """
    src_db = tmp_path / "recon_src.db"
    dest_db = tmp_path / "recon_dest.db"
    dest_url = f"file:{dest_db}"

    # Setup source
    KnowledgeVectorStore(db_path=src_db)
    with sqlite3.connect(src_db) as conn:
        conn.execute("INSERT INTO rate_limits (key, timestamp) VALUES ('ip_1', 100.0)")
        conn.execute("INSERT INTO rate_limits (key, timestamp) VALUES ('ip_1', 100.0)")  # duplicate timestamp
        conn.execute("INSERT INTO rate_limits (key, timestamp) VALUES ('ip_2', 200.0)")
        conn.commit()

    # Scenario 1: First migration of multiple rows with legitimate duplicates
    res1 = migrate_database(str(src_db), dest_url, dry_run=False)
    assert res1["status"] == "success"
    client1 = libsql_client.create_client_sync(dest_url)
    c1 = client1.execute("SELECT COUNT(*) FROM rate_limits").rows[0][0]
    client1.close()
    assert c1 == 3

    # Scenario 2: Repeat migration without duplication
    res2 = migrate_database(str(src_db), dest_url, dry_run=False)
    assert res2["status"] == "success"
    client2 = libsql_client.create_client_sync(dest_url)
    c2 = client2.execute("SELECT COUNT(*) FROM rate_limits").rows[0][0]
    client2.close()
    assert c2 == 3

    # Scenario 3: Adding new source rows between runs
    with sqlite3.connect(src_db) as conn:
        conn.execute("INSERT INTO rate_limits (key, timestamp) VALUES ('ip_3', 300.0)")
        conn.commit()
    res3 = migrate_database(str(src_db), dest_url, dry_run=False)
    assert res3["status"] == "success"
    client3 = libsql_client.create_client_sync(dest_url)
    c3 = client3.execute("SELECT COUNT(*) FROM rate_limits").rows[0][0]
    client3.close()
    assert c3 == 4

    # Scenario 5: Interrupted migration retry
    # Simulate interruption by removing ip_3 and ip_2 from destination
    client_int = libsql_client.create_client_sync(dest_url)
    client_int.execute("DELETE FROM rate_limits WHERE key = 'ip_3'")
    client_int.execute("DELETE FROM rate_limits WHERE key = 'ip_2'")
    interrupted_c = client_int.execute("SELECT COUNT(*) FROM rate_limits").rows[0][0]
    client_int.close()
    assert interrupted_c == 2
    # Rerun migration: should detect delta and reconcile back to 4 rows
    res5 = migrate_database(str(src_db), dest_url, dry_run=False)
    assert res5["status"] == "success"
    client5 = libsql_client.create_client_sync(dest_url)
    c5 = client5.execute("SELECT COUNT(*) FROM rate_limits").rows[0][0]
    client5.close()
    assert c5 == 4

    # Scenario 4 & 6: Destination has rows not in source / source row removed
    # Removing 'ip_3' from source leaves destination with 4 rows while source has 3
    with sqlite3.connect(src_db) as conn:
        conn.execute("DELETE FROM rate_limits WHERE key = 'ip_3'")
        conn.commit()
    # Migration is additive (not a destructive mirror) and fails closed on count/data divergence in preflight
    with pytest.raises(RuntimeError) as exc_info4:
        migrate_database(str(src_db), dest_url, dry_run=False)
    assert "PREFLIGHT SAFETY FAILURE on table 'rate_limits'" in str(exc_info4.value)
    assert "Destination contains 1 divergent or destination-only record(s)" in str(exc_info4.value)

    # Scenario 7: Equal counts but different contents
    src_db7 = tmp_path / "src7.db"
    dest_db7 = tmp_path / "dest7.db"
    dest_url7 = f"file:{dest_db7}"
    KnowledgeVectorStore(db_path=src_db7)
    with sqlite3.connect(src_db7) as conn:
        conn.execute("INSERT INTO rate_limits (key, timestamp) VALUES ('src_key', 500.0)")
        conn.commit()
    # Setup schema on dest7
    migrate_database(str(src_db7), dest_url7, dry_run=False)
    # Manually replace content on dest7 so count is 1, but content differs
    client7 = libsql_client.create_client_sync(dest_url7)
    client7.execute("DELETE FROM rate_limits")
    client7.execute("INSERT INTO rate_limits (key, timestamp) VALUES ('dest_key_only', 600.0)")
    client7.close()
    # Rerun: preflight detects destination-only key 'dest_key_only' before any writes occur!
    with pytest.raises(RuntimeError) as exc_info7:
        migrate_database(str(src_db7), dest_url7, dry_run=False)
    assert "PREFLIGHT SAFETY FAILURE on table 'rate_limits'" in str(exc_info7.value)
    assert "Destination contains 1 divergent or destination-only record(s)" in str(exc_info7.value)


# -----------------------------------------------------------------------------
# 4. Migration Integrity & Count Mismatch Failure Tests
# -----------------------------------------------------------------------------
def test_migration_fails_immediately_on_count_mismatch(tmp_path):
    """Verify that a deliberate row count mismatch raises RuntimeError immediately and produces no success."""
    src_db = tmp_path / "mismatch_src.db"
    dest_db = tmp_path / "mismatch_dest.db"

    KnowledgeVectorStore(db_path=src_db)
    now_iso = "2026-10-26T12:00:00+00:00"
    with sqlite3.connect(src_db) as conn:
        conn.execute("""
            INSERT INTO articles (id, url, title, category, content_hash, raw_text, created_at, updated_at, account_id)
            VALUES ('art_mismatch_1', 'https://example.com/art1', 'Art 1', 'faq', 'h1', 'Text 1', ?, ?, 'acc_default'),
                   ('art_mismatch_2', 'https://example.com/art2', 'Art 2', 'faq', 'h2', 'Text 2', ?, ?, 'acc_default')
        """, (now_iso, now_iso, now_iso, now_iso))
        conn.commit()

    dest_url = f"file:{dest_db}"

    # Intercept batch insert on destination to simulate a dropped row
    orig_batch = libsql_client.sync.ClientSync.batch

    def fake_batch(self, stmts):
        # Drop half the statements for articles table
        filtered = []
        for s in stmts:
            sql_text = s[0] if isinstance(s, tuple) else getattr(s, "sql", str(s))
            if 'INSERT OR REPLACE INTO "articles"' in sql_text and len(filtered) >= 1:
                continue  # drop second article
            filtered.append(s)
        return orig_batch(self, filtered)

    with patch.object(libsql_client.sync.ClientSync, "batch", side_effect=fake_batch, autospec=True):
        with pytest.raises(RuntimeError) as exc_info:
            migrate_database(str(src_db), dest_url, turso_token="", dry_run=False)

        assert "MIGRATION INTEGRITY FAILURE on table 'articles'" in str(exc_info.value)
        assert "expected 2 records from source, but destination has 1" in str(exc_info.value)


def test_migration_fails_on_corrupt_chunk_embedding_dimension(tmp_path):
    """Verify data integrity check detects invalid vector dimensions in destination."""
    src_db = tmp_path / "corrupt_embed_src.db"
    dest_db = tmp_path / "corrupt_embed_dest.db"

    KnowledgeVectorStore(db_path=src_db)
    now_iso = "2026-10-26T12:00:00+00:00"
    with sqlite3.connect(src_db) as conn:
        conn.execute("""
            INSERT INTO articles (id, url, title, category, content_hash, raw_text, created_at, updated_at, account_id)
            VALUES ('art_embed_1', 'https://example.com/art_embed', 'Art Embed', 'faq', 'h1', 'Text 1', ?, ?, 'acc_default')
        """, (now_iso, now_iso))
        # Insert chunk with corrupt 10-dimensional vector instead of 384
        corrupt_vec = json.dumps([0.1] * 10)
        conn.execute("""
            INSERT INTO chunks (id, article_id, url, article_title, section_heading, content, image_urls, image_descriptions, embedding_json, is_active, created_at, account_id)
            VALUES ('chk_corrupt_1', 'art_embed_1', 'https://example.com/art_embed', 'Art Embed', 'Head', 'Content', '[]', '[]', ?, 1, ?, 'acc_default')
        """, (corrupt_vec, now_iso))
        conn.commit()

    dest_url = f"file:{dest_db}"
    with pytest.raises(RuntimeError) as exc_info:
        migrate_database(str(src_db), dest_url, turso_token="", dry_run=False)

    assert "DATA INTEGRITY FAILURE on table 'chunks'" in str(exc_info.value)
    assert "expected 384" in str(exc_info.value)


# -----------------------------------------------------------------------------
# 5. Production Database Configuration Fail-Closed Tests
# -----------------------------------------------------------------------------
def test_production_fails_closed_when_turso_url_is_missing(monkeypatch):
    """Verify KnowledgeVectorStore fails closed when VERCEL/production is set without TURSO_DATABASE_URL."""
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(RuntimeError) as exc_info:
        KnowledgeVectorStore()

    assert "CRITICAL PRODUCTION CONFIGURATION ERROR: TURSO_DATABASE_URL is not set" in str(exc_info.value)


def test_production_fails_closed_on_invalid_turso_url(monkeypatch):
    """Verify KnowledgeVectorStore fails closed when TURSO_DATABASE_URL has an invalid scheme."""
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("TURSO_DATABASE_URL", "unsupported_scheme://db.turso.io")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "valid_secret_token")

    with pytest.raises(ValueError) as exc_info:
        KnowledgeVectorStore()

    assert "Invalid TURSO_DATABASE_URL scheme" in str(exc_info.value)
    # Ensure secrets are not printed
    assert "valid_secret_token" not in str(exc_info.value)


def test_production_fails_closed_when_turso_token_is_missing(monkeypatch):
    """Verify KnowledgeVectorStore fails closed when TURSO_DATABASE_URL is set but TURSO_AUTH_TOKEN is missing."""
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://my-org-db.turso.io")
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)

    with pytest.raises(RuntimeError) as exc_info:
        KnowledgeVectorStore()

    assert "TURSO_AUTH_TOKEN is missing" in str(exc_info.value)


def test_development_uses_local_sqlite(tmp_path, monkeypatch):
    """Verify local development seamlessly uses SQLite without requiring Turso credentials."""
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)

    dev_db = tmp_path / "dev_test.db"
    kvs = KnowledgeVectorStore(db_path=dev_db)
    status = kvs.get_storage_status()
    assert status["status"] == "connected"
    assert status["connection_health"] == "healthy"


def test_explicit_temporary_db_path_honored_in_tests(tmp_path, monkeypatch):
    """Verify test fixtures can explicitly specify temporary SQLite paths without being forced into production Turso mode."""
    monkeypatch.setenv("VERCEL", "1")  # Simulate Vercel environment
    explicit_test_db = tmp_path / "fixture.db"

    # Explicit db_path must be honored
    kvs = KnowledgeVectorStore(db_path=explicit_test_db)
    with kvs._get_connection() as conn:
        res = conn.execute("SELECT 1").fetchone()
        assert res[0] == 1


def test_production_with_valid_turso_configuration_using_mock(monkeypatch):
    """Verify production initializes successfully with mock Turso connection without attempting real network requests."""
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://mocked-cluster.turso.io")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "mocked_jwt_auth_token_value")

    from unittest.mock import MagicMock
    mock_client = MagicMock()
    mock_client.execute.return_value = MagicMock(rows=[[1]])

    with patch("libsql_client.create_client_sync", return_value=mock_client) as mock_create:
        kvs = KnowledgeVectorStore()
        with kvs._get_connection() as conn:
            pass

        assert mock_create.called
        call_args = mock_create.call_args
        assert call_args[0][0] == "libsql://mocked-cluster.turso.io"
        assert call_args[1]["auth_token"] == "mocked_jwt_auth_token_value"


# -----------------------------------------------------------------------------
# 6. Phase 5.5 Read-Only Preflight & Failure/Recovery Simulations
# -----------------------------------------------------------------------------
def test_phase55_clean_first_and_rerun_matching_migration(tmp_path):
    """
    Simulate:
    1. A clean first migration (destination initially EMPTY).
    2. Re-running a matching migration (destination MATCHING).
    Verify that rerun is idempotent and introduces zero duplicates or errors.
    """
    src_db = tmp_path / "p55_clean_src.db"
    dest_db = tmp_path / "p55_clean_dest.db"
    dest_url = f"file:{dest_db}"

    KnowledgeVectorStore(db_path=src_db)
    now_iso = "2026-10-26T12:00:00+00:00"
    with sqlite3.connect(src_db) as conn:
        conn.execute("""
            INSERT INTO articles (id, url, title, category, content_hash, raw_text, created_at, updated_at, account_id)
            VALUES ('art_p55_1', 'https://example.com/p55_1', 'Clean Title 1', 'faq', 'h1', 'Content 1', ?, ?, 'acc_default')
        """, (now_iso, now_iso))
        conn.execute("INSERT INTO rate_limits (key, timestamp) VALUES ('rl_clean', 12345.0)")
        conn.commit()

    # 1. Clean first migration
    res1 = migrate_database(str(src_db), dest_url, dry_run=False)
    assert res1["status"] == "success"
    assert res1["source_counts"]["articles"] == 1
    assert res1["dest_counts"]["articles"] == 1

    # 2. Re-running matching migration
    res2 = migrate_database(str(src_db), dest_url, dry_run=False)
    assert res2["status"] == "success"
    assert res2["dest_counts"]["articles"] == 1
    assert res2["dest_counts"]["rate_limits"] == 1


def test_phase55_preflight_detects_extra_destination_rows_before_writes(tmp_path):
    """
    Simulate destination with extra rows.
    Verify preflight detects destination-only rows and aborts BEFORE any writes or modifications.
    """
    src_db = tmp_path / "p55_extra_src.db"
    dest_db = tmp_path / "p55_extra_dest.db"
    dest_url = f"file:{dest_db}"

    KnowledgeVectorStore(db_path=src_db)
    now_iso = "2026-10-26T12:00:00+00:00"
    with sqlite3.connect(src_db) as conn:
        conn.execute("""
            INSERT INTO articles (id, url, title, category, content_hash, raw_text, created_at, updated_at, account_id)
            VALUES ('art_src_1', 'https://example.com/art1', 'Source Article', 'faq', 'h1', 'Text', ?, ?, 'acc_default')
        """, (now_iso, now_iso))
        conn.commit()

    # Perform initial baseline migration
    migrate_database(str(src_db), dest_url, dry_run=False)

    # Inject an extra destination-only row directly into destination
    client = libsql_client.create_client_sync(dest_url)
    client.execute("""
        INSERT INTO articles (id, url, title, category, content_hash, raw_text, created_at, updated_at, account_id)
        VALUES ('art_dest_extra', 'https://example.com/dest_extra', 'Dest Only Article', 'faq', 'h2', 'Extra Text', '2026-10-26T12:00:00+00:00', '2026-10-26T12:00:00+00:00', 'acc_default')
    """)
    client.close()

    # Re-run migration: preflight must detect extra row and fail before writes
    with pytest.raises(RuntimeError) as exc_info:
        migrate_database(str(src_db), dest_url, dry_run=False)

    err = str(exc_info.value)
    assert "PREFLIGHT SAFETY FAILURE on table 'articles'" in err
    assert "art_dest_extra" in err
    assert "Migration aborted BEFORE any destination modifications" in err

    # Verify destination was NOT modified: extra row still exists
    client_verify = libsql_client.create_client_sync(dest_url)
    cnt = client_verify.execute("SELECT COUNT(*) FROM articles").rows[0][0]
    extra_row = client_verify.execute("SELECT title FROM articles WHERE id = 'art_dest_extra'").rows
    client_verify.close()
    assert cnt == 2
    assert len(extra_row) == 1
    assert extra_row[0][0] == "Dest Only Article"


def test_phase55_preflight_detects_equal_counts_conflicting_records_before_writes(tmp_path):
    """
    Simulate equal row counts between source and destination, but conflicting records (different data).
    Verify preflight does NOT assume equal counts mean equal data and aborts BEFORE any writes.
    """
    src_db = tmp_path / "p55_conflict_src.db"
    dest_db = tmp_path / "p55_conflict_dest.db"
    dest_url = f"file:{dest_db}"

    KnowledgeVectorStore(db_path=src_db)
    now_iso = "2026-10-26T12:00:00+00:00"
    with sqlite3.connect(src_db) as conn:
        conn.execute("""
            INSERT INTO articles (id, url, title, category, content_hash, raw_text, created_at, updated_at, account_id)
            VALUES ('art_conflict_1', 'https://example.com/art_conflict', 'Authorized Canonical Title', 'faq', 'hash_canon', 'Canonical Content', ?, ?, 'acc_default')
        """, (now_iso, now_iso))
        conn.commit()

    # Perform initial baseline migration
    migrate_database(str(src_db), dest_url, dry_run=False)

    # Tamper destination row directly: keep count = 1, but change title and hash
    client = libsql_client.create_client_sync(dest_url)
    client.execute("""
        UPDATE articles SET title = 'Conflicting Divergent Title', content_hash = 'hash_divergent'
        WHERE id = 'art_conflict_1'
    """)
    client.close()

    # Re-run migration: preflight must detect conflict on shared PK ('art_conflict_1',) despite equal counts!
    with pytest.raises(RuntimeError) as exc_info:
        migrate_database(str(src_db), dest_url, dry_run=False)

    err = str(exc_info.value)
    assert "PREFLIGHT SAFETY FAILURE on table 'articles'" in err
    assert "conflicts with source data" in err
    assert "Conflicting Divergent Title" in err
    assert "Authorized Canonical Title" in err
    assert "Migration aborted BEFORE any destination modifications" in err

    # Confirm destination was NOT overwritten: the divergent data is still intact
    client_verify = libsql_client.create_client_sync(dest_url)
    dest_title = client_verify.execute("SELECT title FROM articles WHERE id = 'art_conflict_1'").rows[0][0]
    client_verify.close()
    assert dest_title == "Conflicting Divergent Title"


def test_phase55_preflight_detects_incompatible_tables_and_versions(tmp_path):
    """Verify preflight rejects destinations with foreign/incompatible tables or migration versions."""
    src_db = tmp_path / "p55_incompat_src.db"
    dest_db = tmp_path / "p55_incompat_dest.db"
    dest_url = f"file:{dest_db}"

    KnowledgeVectorStore(db_path=src_db)
    # Prepare destination with an incompatible foreign table
    client = libsql_client.create_client_sync(dest_url)
    client.execute("CREATE TABLE unrecognized_foreign_table (col1 TEXT);")
    client.close()

    with pytest.raises(RuntimeError) as exc_info:
        migrate_database(str(src_db), dest_url, dry_run=False)

    assert "PREFLIGHT SAFETY FAILURE: Destination database contains unrecognized or incompatible tables" in str(exc_info.value)
    assert "unrecognized_foreign_table" in str(exc_info.value)


def test_phase55_batch_failure_and_partial_migration_retry_recovery(tmp_path):
    """
    Simulate:
    1. A failure during a batch insert (e.g. simulated network drop or constraint error).
    2. A retry after partial migration without resetting the destination database.
    Verify that the recovery procedure achieves full synchronization idempotently.
    """
    src_db = tmp_path / "p55_batch_src.db"
    dest_db = tmp_path / "p55_batch_dest.db"
    dest_url = f"file:{dest_db}"

    KnowledgeVectorStore(db_path=src_db)
    now_iso = "2026-10-26T12:00:00+00:00"
    with sqlite3.connect(src_db) as conn:
        conn.execute("""
            INSERT INTO articles (id, url, title, category, content_hash, raw_text, created_at, updated_at, account_id)
            VALUES ('art_batch_1', 'https://example.com/art_batch_1', 'Batch Article 1', 'faq', 'h1', 'Text 1', ?, ?, 'acc_default'),
                   ('art_batch_2', 'https://example.com/art_batch_2', 'Batch Article 2', 'faq', 'h2', 'Text 2', ?, ?, 'acc_default')
        """, (now_iso, now_iso, now_iso, now_iso))
        conn.commit()

    # Simulate batch failure on first run when inserting chunks
    orig_batch = libsql_client.sync.ClientSync.batch
    call_count = [0]

    def failing_batch(self, stmts):
        sql_text = stmts[0][0] if isinstance(stmts[0], tuple) else str(stmts[0])
        if 'INSERT OR REPLACE INTO "articles"' in sql_text:
            call_count[0] += 1
            if call_count[0] == 1:
                # Execute only first article, then raise simulated network interruption
                orig_batch(self, [stmts[0]])
                raise ConnectionResetError("Simulated socket connection reset during batch write")
        return orig_batch(self, stmts)

    with patch.object(libsql_client.sync.ClientSync, "batch", side_effect=failing_batch, autospec=True):
        with pytest.raises(ConnectionResetError, match="Simulated socket connection reset"):
            migrate_database(str(src_db), dest_url, dry_run=False)

    # Inspect partial destination state: only 1 of 2 articles was committed
    client_check = libsql_client.create_client_sync(dest_url)
    partial_cnt = client_check.execute("SELECT COUNT(*) FROM articles").rows[0][0]
    client_check.close()
    assert partial_cnt == 1

    # Retry recovery: run migrate_database normally without resetting destination
    retry_res = migrate_database(str(src_db), dest_url, dry_run=False)
    assert retry_res["status"] == "success"
    assert retry_res["dest_counts"]["articles"] == 2

    # Verify both records are present and correct
    client_final = libsql_client.create_client_sync(dest_url)
    final_pks = set(r[0] for r in client_final.execute("SELECT id FROM articles").rows)
    client_final.close()
    assert final_pks == {"art_batch_1", "art_batch_2"}


def test_phase55_changed_source_database_between_runs(tmp_path):
    """
    Simulate source database changing between migration runs:
    - Case A: Additive source changes (new rows added to source).
              Preflight classifies as PARTIAL_RESUMABLE; retry populates new rows cleanly.
    - Case B: Conflicting source changes (source row modified to conflict with destination).
              Preflight detects conflict and fails closed BEFORE any destination writes.
    """
    src_db = tmp_path / "p55_changed_src.db"
    dest_db = tmp_path / "p55_changed_dest.db"
    dest_url = f"file:{dest_db}"

    KnowledgeVectorStore(db_path=src_db)
    now_iso = "2026-10-26T12:00:00+00:00"
    with sqlite3.connect(src_db) as conn:
        conn.execute("""
            INSERT INTO articles (id, url, title, category, content_hash, raw_text, created_at, updated_at, account_id)
            VALUES ('art_c_1', 'https://example.com/c1', 'Title 1', 'faq', 'h1', 'Text 1', ?, ?, 'acc_default')
        """, (now_iso, now_iso))
        conn.commit()

    # Initial migration
    res1 = migrate_database(str(src_db), dest_url, dry_run=False)
    assert res1["status"] == "success"

    # Case A: Additive source changes
    with sqlite3.connect(src_db) as conn:
        conn.execute("""
            INSERT INTO articles (id, url, title, category, content_hash, raw_text, created_at, updated_at, account_id)
            VALUES ('art_c_2', 'https://example.com/c2', 'Title 2', 'faq', 'h2', 'Text 2', ?, ?, 'acc_default')
        """, (now_iso, now_iso))
        conn.commit()

    # Rerun migrates the new row successfully
    res2 = migrate_database(str(src_db), dest_url, dry_run=False)
    assert res2["status"] == "success"
    assert res2["dest_counts"]["articles"] == 2

    # Case B: Conflicting source modification
    # Suppose source modifies art_c_1's title to 'Conflicting Source Title'
    # but destination still has 'Title 1'. Preflight must detect this conflict!
    with sqlite3.connect(src_db) as conn:
        conn.execute("UPDATE articles SET title = 'Conflicting Source Title' WHERE id = 'art_c_1'")
        conn.commit()

    with pytest.raises(RuntimeError) as exc_info:
        migrate_database(str(src_db), dest_url, dry_run=False)

    err = str(exc_info.value)
    assert "PREFLIGHT SAFETY FAILURE on table 'articles'" in err
    assert "conflicts with source data" in err
    assert "Title 1" in err
    assert "Conflicting Source Title" in err
    assert "Migration aborted BEFORE any destination modifications" in err
