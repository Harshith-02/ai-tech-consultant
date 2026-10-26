#!/usr/bin/env python3
"""
scripts/migrate_to_turso.py
===========================
Idempotent, safe migration tool to replicate Knowledge Brain SQLite data into
a managed persistent Turso / libSQL database.

Features:
- Verifies destination connection and authentication before modifying data.
- Runs versioned schema migrations (001 through 005) on Turso / libSQL.
- Copies all data in topological foreign-key order using batching.
- Populates full-text search (chunks_fts) index on Turso.
- Validates row counts and sample records before and after migration.
- Fully idempotent (INSERT OR REPLACE).
- Safe dry-run mode and local file-backed dry-run testing support.
- Strict fail-closed destination checks; never writes to remote targets without explicit confirmation.
- Never prints secrets, credentials, or sensitive tokens.
"""

import os
import sys
import json
import sqlite3
import argparse
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, List
from collections import Counter

def mask_url(url: str) -> str:
    if not url:
        return ""
    if url.startswith("file:"):
        return url
    parts = url.split("://")
    if len(parts) > 1:
        scheme = parts[0]
        host = parts[1].split("/")[0]
        return f"{scheme}://{host}"
    return url[:15] + "..."

# Order matters for foreign keys
MIGRATION_TABLES = [
    "schema_migrations",
    "user_accounts",
    "users",
    "sitemap_sources",
    "sitemap_urls",
    "sitemap_refresh_runs",
    "articles",
    "chunks",
    "archived_articles",
    "article_version_history",
    "escalations",
    "gmail_accounts",
    "autonomy_settings",
    "autonomy_global_config",
    "feedback_rules",
    "email_folder_state",
    "sent_emails",
    "email_audit_log",
    "revoked_tokens",
    "rate_limits",
]

MIGRATION_NAMES = {
    "001_baseline_schema": "Initial core tables for Knowledge Brain, Inbox and Autonomy",
    "002_multi_tenant_isolation": "Multi-tenant account_id isolation and indexes",
    "003_auth_and_sessions": "User accounts, credential records, and JWT token revocation table",
    "004_secure_password_hashing": "Migrated legacy plaintext/mock password hashes to standard Bcrypt hashes",
    "005_durable_rate_limits": "Durable rate limit timestamps table for multi-instance serverless resilience",
}

MIGRATION_DDL = {
    "001_baseline_schema": [
        """
        CREATE TABLE IF NOT EXISTS articles (
            id TEXT PRIMARY KEY,
            url TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            category TEXT,
            content_hash TEXT,
            raw_text TEXT,
            screenshot_count INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            sitemap_source TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """,
        """
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
        """,
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
            chunk_id UNINDEXED,
            article_title,
            section_heading,
            content,
            image_descriptions,
            tokenize='porter unicode61'
        );
        """,
        """
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
        """,
        """
        CREATE TABLE IF NOT EXISTS archived_articles (
            id TEXT PRIMARY KEY,
            url TEXT NOT NULL,
            title TEXT NOT NULL,
            category TEXT,
            content_hash TEXT,
            raw_text TEXT,
            sitemap_source TEXT,
            consecutive_missing_checks INTEGER DEFAULT 0,
            last_indexed_at TEXT,
            archived_at TEXT NOT NULL,
            reason TEXT,
            metadata_json TEXT,
            version INTEGER DEFAULT 1
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS article_version_history (
            id TEXT PRIMARY KEY,
            article_id TEXT NOT NULL,
            url TEXT NOT NULL,
            version INTEGER NOT NULL,
            content_hash TEXT NOT NULL,
            raw_text TEXT,
            title TEXT,
            metadata_json TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (article_id) REFERENCES articles(id)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS sitemap_sources (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            root_sitemap_url TEXT NOT NULL,
            refresh_interval_days INTEGER DEFAULT 7,
            missing_threshold INTEGER DEFAULT 15,
            is_enabled INTEGER DEFAULT 1,
            refresh_enabled INTEGER DEFAULT 1,
            status TEXT DEFAULT 'active',
            error_summary TEXT,
            last_checked_at TEXT,
            last_successful_refresh_at TEXT,
            next_check_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """,
        """
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
            FOREIGN KEY (source_id) REFERENCES sitemap_sources(id)
        );
        """,
        """
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
        """,
        """
        CREATE TABLE IF NOT EXISTS gmail_accounts (
            id TEXT PRIMARY KEY,
            email_address TEXT UNIQUE NOT NULL,
            connection_status TEXT DEFAULT 'disconnected',
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
        """,
        """
        CREATE TABLE IF NOT EXISTS autonomy_settings (
            category TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            icon TEXT,
            threshold_x INTEGER DEFAULT 3,
            consecutive_streak INTEGER DEFAULT 0,
            is_eligible INTEGER DEFAULT 0,
            is_guarded INTEGER DEFAULT 0,
            is_enabled INTEGER DEFAULT 1,
            total_approved INTEGER DEFAULT 0,
            total_edited INTEGER DEFAULT 0,
            confidence_score REAL DEFAULT 0.85,
            last_approved_at TEXT,
            updated_at TEXT NOT NULL
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS autonomy_global_config (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS feedback_rules (
            id TEXT PRIMARY KEY,
            category TEXT NOT NULL,
            email_id TEXT,
            rule_text TEXT NOT NULL,
            original_draft TEXT,
            final_sent TEXT,
            diff_summary TEXT,
            created_at TEXT NOT NULL
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS email_folder_state (
            email_id TEXT PRIMARY KEY,
            folder TEXT DEFAULT 'inbox',
            is_starred INTEGER DEFAULT 0,
            is_read INTEGER DEFAULT 1,
            setting_label TEXT,
            raw_json TEXT,
            updated_at TEXT NOT NULL
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS sent_emails (
            id TEXT PRIMARY KEY,
            email_id TEXT,
            recipient TEXT NOT NULL,
            subject TEXT NOT NULL,
            body TEXT NOT NULL,
            category TEXT,
            is_autonomous INTEGER DEFAULT 0,
            gmail_message_id TEXT,
            created_at TEXT NOT NULL
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS email_audit_log (
            id TEXT PRIMARY KEY,
            email_id TEXT,
            event_type TEXT NOT NULL,
            actor_type TEXT DEFAULT 'system',
            decision TEXT,
            reason TEXT,
            metadata_json TEXT,
            created_at TEXT NOT NULL
        );
        """
    ],
    "002_multi_tenant_isolation": [
        "ALTER TABLE articles ADD COLUMN account_id TEXT NOT NULL DEFAULT 'acc_default';",
        "ALTER TABLE chunks ADD COLUMN account_id TEXT NOT NULL DEFAULT 'acc_default';",
        "ALTER TABLE escalations ADD COLUMN account_id TEXT NOT NULL DEFAULT 'acc_default';",
        "ALTER TABLE archived_articles ADD COLUMN account_id TEXT NOT NULL DEFAULT 'acc_default';",
        "ALTER TABLE article_version_history ADD COLUMN account_id TEXT NOT NULL DEFAULT 'acc_default';",
        "ALTER TABLE sitemap_urls ADD COLUMN account_id TEXT NOT NULL DEFAULT 'acc_default';",
        "ALTER TABLE sitemap_refresh_runs ADD COLUMN account_id TEXT NOT NULL DEFAULT 'acc_default';",
        "ALTER TABLE gmail_accounts ADD COLUMN account_id TEXT NOT NULL DEFAULT 'acc_default';",
        "ALTER TABLE sent_emails ADD COLUMN account_id TEXT NOT NULL DEFAULT 'acc_default';",
        "ALTER TABLE feedback_rules ADD COLUMN account_id TEXT NOT NULL DEFAULT 'acc_default';",
        "ALTER TABLE email_audit_log ADD COLUMN account_id TEXT NOT NULL DEFAULT 'acc_default';",
        """
        CREATE TABLE IF NOT EXISTS sitemap_sources_mt (
            id TEXT PRIMARY KEY,
            account_id TEXT NOT NULL DEFAULT 'acc_default',
            name TEXT NOT NULL,
            root_sitemap_url TEXT NOT NULL,
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
            updated_at TEXT NOT NULL,
            UNIQUE(account_id, root_sitemap_url)
        );
        """,
        "INSERT OR IGNORE INTO sitemap_sources_mt (id, account_id, name, root_sitemap_url, is_enabled, refresh_enabled, refresh_interval_days, missing_threshold, last_checked_at, last_successful_refresh_at, next_check_at, status, error_summary, created_at, updated_at) SELECT id, 'acc_default', name, root_sitemap_url, is_enabled, refresh_enabled, refresh_interval_days, missing_threshold, last_checked_at, last_successful_refresh_at, next_check_at, status, error_summary, created_at, updated_at FROM sitemap_sources;",
        "DROP TABLE IF EXISTS sitemap_sources;",
        "ALTER TABLE sitemap_sources_mt RENAME TO sitemap_sources;",
        """
        CREATE TABLE IF NOT EXISTS autonomy_settings_mt (
            account_id TEXT NOT NULL DEFAULT 'acc_default',
            category TEXT NOT NULL,
            name TEXT NOT NULL,
            icon TEXT,
            threshold_x INTEGER DEFAULT 3,
            consecutive_streak INTEGER DEFAULT 0,
            is_eligible INTEGER DEFAULT 0,
            is_guarded INTEGER DEFAULT 0,
            is_enabled INTEGER DEFAULT 1,
            total_approved INTEGER DEFAULT 0,
            total_edited INTEGER DEFAULT 0,
            confidence_score REAL DEFAULT 0.85,
            last_approved_at TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (account_id, category)
        );
        """,
        "INSERT OR IGNORE INTO autonomy_settings_mt (account_id, category, name, icon, threshold_x, consecutive_streak, is_eligible, is_guarded, is_enabled, total_approved, total_edited, confidence_score, last_approved_at, updated_at) SELECT 'acc_default', category, name, icon, threshold_x, consecutive_streak, is_eligible, is_guarded, is_enabled, total_approved, total_edited, confidence_score, last_approved_at, updated_at FROM autonomy_settings;",
        "DROP TABLE IF EXISTS autonomy_settings;",
        "ALTER TABLE autonomy_settings_mt RENAME TO autonomy_settings;",
        """
        CREATE TABLE IF NOT EXISTS email_folder_state_mt (
            account_id TEXT NOT NULL DEFAULT 'acc_default',
            email_id TEXT NOT NULL,
            folder TEXT DEFAULT 'inbox',
            is_starred INTEGER DEFAULT 0,
            is_read INTEGER DEFAULT 1,
            setting_label TEXT,
            raw_json TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (account_id, email_id)
        );
        """,
        "INSERT OR IGNORE INTO email_folder_state_mt (account_id, email_id, folder, is_starred, is_read, setting_label, raw_json, updated_at) SELECT 'acc_default', email_id, folder, is_starred, is_read, setting_label, raw_json, updated_at FROM email_folder_state;",
        "DROP TABLE IF EXISTS email_folder_state;",
        "ALTER TABLE email_folder_state_mt RENAME TO email_folder_state;",
        "CREATE INDEX IF NOT EXISTS idx_sitemap_sources_acc ON sitemap_sources(account_id);",
        "CREATE INDEX IF NOT EXISTS idx_sitemap_urls_acc ON sitemap_urls(account_id, source_id);",
        "CREATE INDEX IF NOT EXISTS idx_archived_articles_acc ON archived_articles(account_id);",
        "CREATE INDEX IF NOT EXISTS idx_gmail_accounts_acc ON gmail_accounts(account_id);",
        "CREATE INDEX IF NOT EXISTS idx_sent_emails_acc ON sent_emails(account_id);"
    ],
    "003_auth_and_sessions": [
        """
        CREATE TABLE IF NOT EXISTS user_accounts (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            plan TEXT DEFAULT 'enterprise',
            created_at TEXT NOT NULL
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            account_id TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'consultant',
            created_at TEXT NOT NULL,
            FOREIGN KEY (account_id) REFERENCES user_accounts(id)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS revoked_tokens (
            jti TEXT PRIMARY KEY,
            account_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            revoked_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_revoked_tokens_jti ON revoked_tokens(jti);"
    ],
    "004_secure_password_hashing": [],
    "005_durable_rate_limits": [
        """
        CREATE TABLE IF NOT EXISTS rate_limits (
            key TEXT NOT NULL,
            timestamp REAL NOT NULL
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_rate_limits_key_time ON rate_limits (key, timestamp);"
    ]
}

def preflight_destination_check(src_conn: sqlite3.Connection, dest_client: Any, src_counts: Dict[str, int]) -> str:
    """
    Read-only preflight inspection of destination state BEFORE any writes or DDL.
    Categorizes destination state into:
      - 'EMPTY': Clean destination (no user tables or all user tables empty).
      - 'MATCHING': Fully migrated destination matching source counts, primary keys, and data.
      - 'PARTIAL_RESUMABLE': Partially migrated destination where all existing data is a strict subset of source.
    Raises RuntimeError if destination divergence, conflicts, or foreign rows are detected.
    """
    tables_res = dest_client.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    dest_existing_tables = set(r[0] for r in tables_res.rows)

    # Allow application tables and internal FTS5 auxiliary tables
    app_tables = set(MIGRATION_TABLES) | {
        "schema_migrations", "chunks_fts", "chunks_fts_data", "chunks_fts_idx",
        "chunks_fts_content", "chunks_fts_docsize", "chunks_fts_config"
    }
    foreign_tables = [t for t in dest_existing_tables if t not in app_tables and not t.startswith("chunks_fts_")]
    if foreign_tables:
        raise RuntimeError(
            f"PREFLIGHT SAFETY FAILURE: Destination database contains unrecognized or incompatible tables: {foreign_tables}. "
            f"Migration aborted BEFORE any destination modifications to prevent data corruption."
        )

    if "schema_migrations" in dest_existing_tables:
        mig_res = dest_client.execute("SELECT version FROM schema_migrations")
        dest_migs = set(r[0] for r in mig_res.rows)
        known_migs = set(MIGRATION_DDL.keys())
        foreign_migs = dest_migs - known_migs
        if foreign_migs:
            raise RuntimeError(
                f"PREFLIGHT SAFETY FAILURE: Destination has unrecognized schema migration versions: {foreign_migs}. "
                f"Migration aborted BEFORE any destination modifications."
            )

    has_data = False
    is_all_matching = True

    for table in MIGRATION_TABLES:
        s_cnt = src_counts.get(table, 0)
        if table in dest_existing_tables:
            d_cnt = dest_client.execute(f'SELECT COUNT(*) FROM "{table}"').rows[0][0]
            if d_cnt > 0:
                has_data = True
            if d_cnt != s_cnt:
                is_all_matching = False

            if d_cnt > 0:
                src_cursor = src_conn.cursor()
                src_cursor.execute(f'PRAGMA table_info("{table}")')
                table_info = src_cursor.fetchall()
                cols = [r["name"] for r in table_info]

                if table == "rate_limits":
                    dest_res = dest_client.execute('SELECT "key", "timestamp" FROM "rate_limits"')
                    dest_counter = Counter((r[0], float(r[1])) for r in dest_res.rows)
                    src_cursor.execute('SELECT "key", "timestamp" FROM "rate_limits"')
                    src_counter = Counter((r["key"], float(r["timestamp"])) for r in src_cursor.fetchall())

                    divergent_items = []
                    for item, d_freq in dest_counter.items():
                        s_freq = src_counter.get(item, 0)
                        if d_freq > s_freq:
                            divergent_items.append((item, f"dest={d_freq}, source={s_freq}"))
                    if divergent_items:
                        sample_str = str(divergent_items[:3])
                        raise RuntimeError(
                            f"PREFLIGHT SAFETY FAILURE on table 'rate_limits': Destination contains {len(divergent_items)} "
                            f"divergent or destination-only record(s) not present in source: {sample_str}. "
                            f"Migration aborted BEFORE any destination modifications."
                        )
                else:
                    pk_cols = [r["name"] for r in table_info if r["pk"] > 0]
                    if not pk_cols:
                        for cand in ["id", "jti", "version", "key", "category", "folder_name"]:
                            if cand in cols:
                                pk_cols = [cand]
                                break

                    if pk_cols:
                        dest_cols_res = dest_client.execute(f'PRAGMA table_info("{table}")')
                        dest_col_names = set(r[1] for r in dest_cols_res.rows)
                        common_cols = [c for c in cols if c in dest_col_names]
                        common_cols_str = ", ".join(f'"{c}"' for c in common_cols)

                        dest_rows_res = dest_client.execute(f'SELECT {common_cols_str} FROM "{table}"')
                        src_cursor.execute(f'SELECT {common_cols_str} FROM "{table}"')
                        src_rows = src_cursor.fetchall()

                        pk_indices = [common_cols.index(c) for c in pk_cols]
                        dest_pks = set(tuple(r[i] for i in pk_indices) for r in dest_rows_res.rows)
                        src_pks = set(tuple(r[c] for c in pk_cols) for r in src_rows)
                        src_rows_by_pk = {tuple(r[c] for c in pk_cols): r for r in src_rows}

                        # Check 1: Destination-only rows
                        dest_only_pks = dest_pks - src_pks
                        if dest_only_pks:
                            sample_str = str(list(dest_only_pks)[:3])
                            pk_label = ", ".join(pk_cols)
                            raise RuntimeError(
                                f"PREFLIGHT SAFETY FAILURE on table '{table}': Destination contains {len(dest_only_pks)} "
                                f"destination-only record(s) with ({pk_label}) not present in source: {sample_str}. "
                                f"Migration aborted BEFORE any destination modifications."
                            )

                        # Check 2: Data conflict check on shared records
                        for d_row in dest_rows_res.rows:
                            pk_val = tuple(d_row[i] for i in pk_indices)
                            s_row = src_rows_by_pk.get(pk_val)
                            if s_row is not None:
                                for idx, col_name in enumerate(common_cols):
                                    d_val = d_row[idx]
                                    s_val = s_row[col_name]
                                    is_equal = False
                                    if d_val is None and s_val is None:
                                        is_equal = True
                                    elif isinstance(d_val, (int, float)) and isinstance(s_val, (int, float)):
                                        is_equal = abs(float(d_val) - float(s_val)) < 1e-4
                                    else:
                                        is_equal = (str(d_val) == str(s_val))

                                    if not is_equal:
                                        raise RuntimeError(
                                            f"PREFLIGHT SAFETY FAILURE on table '{table}': Destination record with "
                                            f"primary key {pk_val} conflicts with source data (column '{col_name}' "
                                            f"differs: destination='{d_val}', source='{s_val}'). "
                                            f"Migration aborted BEFORE any destination modifications."
                                        )

    if not has_data:
        classification = "EMPTY"
    elif is_all_matching:
        classification = "MATCHING"
    else:
        classification = "PARTIAL_RESUMABLE"

    return classification

def migrate_database(source_path: str, turso_url: str, turso_token: str = "", dry_run: bool = False) -> Dict[str, Any]:
    print(f"=== KNOWLEDGE BRAIN PERSISTENT MIGRATION ===")
    print(f"Source Database: {source_path}")
    print(f"Destination:     {mask_url(turso_url) if turso_url else '[None - Dry Run Only]'}")
    print(f"Mode:            {'DRY-RUN (No writes)' if dry_run else 'LIVE MIGRATION'}")
    print("---------------------------------------------")

    if not Path(source_path).exists():
        raise FileNotFoundError(f"Source database file not found: {source_path}")

    # 1. Connect to source
    src_conn = sqlite3.connect(source_path)
    src_conn.row_factory = sqlite3.Row
    src_cursor = src_conn.cursor()

    # Collect source counts
    src_counts = {}
    for table in MIGRATION_TABLES:
        try:
            src_cursor.execute(f'SELECT COUNT(*) FROM "{table}"')
            src_counts[table] = src_cursor.fetchone()[0]
        except Exception:
            src_counts[table] = 0

    print("Source database record summary:")
    for t, cnt in src_counts.items():
        if cnt > 0:
            print(f"  • {t:25s}: {cnt:5d} records")

    if dry_run:
        print("\n[DRY RUN COMPLETE] Source records verified. No changes made.")
        src_conn.close()
        return {"status": "dry_run", "source_counts": src_counts}

    # 2. Connect to destination Turso / libSQL
    import libsql_client
    is_local_file = turso_url.startswith("file:")
    if not is_local_file and not (turso_url.startswith("libsql://") or turso_url.startswith("https://") or turso_url.startswith("http://")):
        src_conn.close()
        raise ValueError(f"Invalid destination URL scheme: {turso_url}. Must be file:, libsql://, https://, or http://")

    if not is_local_file and not turso_token:
        src_conn.close()
        raise ValueError("Destination requires TURSO_AUTH_TOKEN for remote authentication.")

    print(f"\nConnecting to destination database at {mask_url(turso_url)}...")
    dest_client = libsql_client.create_client_sync(turso_url, auth_token=turso_token if not is_local_file else None)
    
    # Ping
    dest_client.execute("SELECT 1")
    print("Connected successfully to destination libSQL engine.")

    # 3. Read-only Preflight destination state check (runs before ANY DDL or writes)
    dest_state = preflight_destination_check(src_conn, dest_client, src_counts)
    print(f"Destination preflight status: {dest_state}")

    # 3. Ensure schema_migrations table exists on destination
    dest_client.execute("""
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        applied_at TEXT NOT NULL
    );
    """)

    # 4. Run versioned migrations on destination
    for version, stmts in MIGRATION_DDL.items():
        res = dest_client.execute("SELECT COUNT(*) FROM schema_migrations WHERE version = ?", [version])
        if res.rows[0][0] == 0:
            print(f"Applying migration '{version}' on destination...")
            for sql in stmts:
                try:
                    dest_client.execute(sql.strip())
                except Exception as e:
                    # Ignore duplicate column if table already has it
                    if "duplicate column" not in str(e).lower() and "already exists" not in str(e).lower():
                        print(f"  Warning during DDL: {e}")
            applied_at = datetime.now(timezone.utc).isoformat()
            dest_client.execute(
                "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                [version, MIGRATION_NAMES.get(version, f"Migration {version}"), applied_at]
            )
            print(f"  Migration '{version}' applied.")
        else:
            print(f"Migration '{version}' already applied on destination.")

    # 5. Migrate records table by table
    print("\nMigrating records to destination...")
    dest_counts = {}

    for table in MIGRATION_TABLES:
        cnt = src_counts.get(table, 0)
        if cnt == 0:
            dest_counts[table] = 0
            continue

        src_cursor.execute(f'PRAGMA table_info("{table}")')
        cols = [r["name"] for r in src_cursor.fetchall()]
        cols_str = ", ".join(f'"{c}"' for c in cols)
        placeholders = ", ".join("?" for _ in cols)
        insert_sql = f'INSERT OR REPLACE INTO "{table}" ({cols_str}) VALUES ({placeholders})'

        src_cursor.execute(f'SELECT {cols_str} FROM "{table}"')
        rows = src_cursor.fetchall()

        if table == "rate_limits":
            # Fix 2: Deterministic frequency reconciliation for table without natural primary key
            # Inspect existing destination (key, timestamp) pairs and insert only the missing delta
            dest_res = dest_client.execute('SELECT "key", "timestamp" FROM "rate_limits"')
            dest_counter = Counter((r[0], float(r[1])) for r in dest_res.rows)
            src_counter = Counter((r["key"], float(r["timestamp"])) for r in rows)

            delta_rows = []
            for item, src_freq in src_counter.items():
                dest_freq = dest_counter.get(item, 0)
                needed = src_freq - dest_freq
                for _ in range(needed):
                    delta_rows.append(item)

            if delta_rows:
                batch_size = 50
                for i in range(0, len(delta_rows), batch_size):
                    chunk = delta_rows[i:i + batch_size]
                    batch_stmts = []
                    for k, ts in chunk:
                        batch_stmts.append(('INSERT INTO "rate_limits" ("key", "timestamp") VALUES (?, ?)', [k, ts]))
                    dest_client.batch(batch_stmts)
        else:
            # Batch insert in chunks of 50
            batch_size = 50
            for i in range(0, len(rows), batch_size):
                chunk = rows[i:i + batch_size]
                batch_stmts = []
                for r in chunk:
                    batch_stmts.append((insert_sql, [r[c] for c in cols]))
                dest_client.batch(batch_stmts)

        # Check destination count
        res = dest_client.execute(f'SELECT COUNT(*) FROM "{table}"')
        dest_counts[table] = res.rows[0][0]

        # Fix 1: Strict count equality validation
        if dest_counts[table] != cnt:
            err_msg = (
                f"MIGRATION INTEGRITY FAILURE on table '{table}': "
                f"expected {cnt} records from source, but destination has {dest_counts[table]} records."
            )
            print(f"  • {table:25s}: {cnt:5d} source -> {dest_counts[table]:5d} destination [MISMATCH]")
            raise RuntimeError(err_msg)

        # Fix 1: Primary key coverage validation for tables with primary key
        for pk_candidate in ["id", "jti", "version", "key"]:
            if pk_candidate in cols and len(rows) > 0:
                sample_pks = [rows[0][pk_candidate], rows[len(rows) // 2][pk_candidate], rows[-1][pk_candidate]]
                for pk_val in sample_pks:
                    pk_check = dest_client.execute(f'SELECT COUNT(*) FROM "{table}" WHERE "{pk_candidate}" = ?', [pk_val])
                    if pk_check.rows[0][0] == 0:
                        err_msg = (
                            f"PRIMARY KEY INTEGRITY FAILURE on table '{table}': "
                            f"source record with {pk_candidate}='{pk_val}' was not found in destination."
                        )
                        raise RuntimeError(err_msg)
                break

        # Fix 1: Critical data field validation
        if table == "chunks" and len(rows) > 0:
            chk_sample = dest_client.execute('SELECT id, embedding_json FROM chunks LIMIT 5')
            for r in chk_sample.rows:
                if not r[1]:
                    raise RuntimeError(f"DATA INTEGRITY FAILURE on table 'chunks': chunk '{r[0]}' has empty embedding_json.")
                vec = json.loads(r[1])
                if len(vec) != 384:
                    raise RuntimeError(f"DATA INTEGRITY FAILURE on table 'chunks': chunk '{r[0]}' embedding has length {len(vec)}, expected 384.")

        if table == "users" and len(rows) > 0:
            usr_sample = dest_client.execute('SELECT id, email, password_hash FROM users LIMIT 5')
            for r in usr_sample.rows:
                pw = str(r[2])
                if not (pw.startswith("$2a$") or pw.startswith("$2b$") or pw.startswith("$2y$")):
                    raise RuntimeError(f"SECURITY INTEGRITY FAILURE on table 'users': user '{r[1]}' has invalid password hash prefix.")

        print(f"  • {table:25s}: {cnt:5d} source -> {dest_counts[table]:5d} destination [OK]")

    # 6. Rebuild chunks_fts
    print("\nRebuilding full-text search index (chunks_fts) on destination...")
    dest_client.execute("DELETE FROM chunks_fts;")
    src_cursor.execute("SELECT id AS chunk_id, article_title, section_heading, content, image_descriptions FROM chunks WHERE is_active = 1")
    fts_rows = src_cursor.fetchall()
    fts_sql = "INSERT INTO chunks_fts (chunk_id, article_title, section_heading, content, image_descriptions) VALUES (?, ?, ?, ?, ?)"
    for i in range(0, len(fts_rows), 50):
        chunk = fts_rows[i:i + 50]
        batch = [
            (fts_sql, [r["chunk_id"], r["article_title"], r["section_heading"], r["content"], r["image_descriptions"]])
            for r in chunk
        ]
        dest_client.batch(batch)
    
    fts_res = dest_client.execute("SELECT COUNT(*) FROM chunks_fts")
    fts_count = fts_res.rows[0][0]
    print(f"  • chunks_fts indexed:     {fts_count:5d} chunks in destination")

    # 7. Verification search query
    print("\nRunning verification search on destination...")
    search_res = dest_client.execute("SELECT rowid, rank FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY rank LIMIT 3", ["stripe"])
    print(f"  • FTS5 search query 'stripe' returned {len(search_res.rows)} ranking results.")

    dest_client.close()
    src_conn.close()

    print("\n=============================================")
    print("MIGRATION COMPLETED SUCCESSFULLY WITH ZERO LOSS")
    print("=============================================")
    return {
        "status": "success",
        "source_counts": src_counts,
        "dest_counts": dest_counts,
        "fts_count": fts_count
    }

def main():
    parser = argparse.ArgumentParser(description="Migrate Knowledge Brain SQLite database to Turso / libSQL")
    parser.add_argument("--source", default="task1-knowledge-brain/data/knowledge_brain.db", help="Source SQLite DB path")
    parser.add_argument("--url", default=None, help="Turso database URL (libsql://...) or local file: path")
    parser.add_argument("--token", default=None, help="Turso auth token")
    parser.add_argument("--dry-run", action="store_true", help="Perform verification without writing to destination")
    parser.add_argument("--confirm-remote", action="store_true", help="Explicit confirmation required to write to remote database")
    args = parser.parse_args()

    target_url = args.url or os.environ.get("TURSO_DATABASE_URL")
    target_token = args.token or os.environ.get("TURSO_AUTH_TOKEN")

    if not args.dry_run:
        if not target_url:
            print("ERROR: Destination database URL must be specified via --url or TURSO_DATABASE_URL.")
            print("To inspect the source database safely without connecting or writing, specify --dry-run.")
            sys.exit(1)
        if target_url.startswith("libsql://") or target_url.startswith("https://") or target_url.startswith("http://"):
            if not target_token:
                print("ERROR: Remote Turso database destination requires --token or TURSO_AUTH_TOKEN.")
                sys.exit(1)
            if not args.confirm_remote:
                print("SAFETY LOCK: Writing to a remote Turso database requires explicit --confirm-remote flag.")
                print("Aborting to prevent unintended remote writes.")
                sys.exit(1)

    try:
        migrate_database(args.source, target_url or "", target_token or "", dry_run=args.dry_run)
    except Exception as e:
        print(f"\nFATAL MIGRATION ERROR: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
