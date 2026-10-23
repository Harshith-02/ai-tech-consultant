import os
import sqlite3
import json
import uuid
import re
import hashlib
from datetime import datetime, timezone, timedelta
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

class DatabaseRow:
    """Provides complete API equivalence with sqlite3.Row for both index and key access."""
    def __init__(self, cols: List[str], values: List[Any]):
        self._cols = list(cols)
        self._values = list(values)
        self._map = dict(zip(self._cols, self._values))

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, int):
            return self._values[key]
        return self._map[key]

    def keys(self):
        return self._map.keys()

    def values(self):
        return self._map.values()

    def items(self):
        return self._map.items()

    def __iter__(self):
        return iter(self._cols)

    def __len__(self) -> int:
        return len(self._values)

    def get(self, key: str, default: Any = None) -> Any:
        return self._map.get(key, default)

    def __repr__(self) -> str:
        return f"<DatabaseRow {self._map}>"


class LibsqlCursorAdapter:
    def __init__(self, client):
        self.client = client
        self._last_result = None
        self._row_idx = 0

    def execute(self, sql: str, params: Any = None):
        if params is None:
            p = []
        elif isinstance(params, (list, tuple)):
            p = list(params)
        elif isinstance(params, dict):
            p = params
        else:
            p = [params]
        self._last_result = self.client.execute(sql, p)
        self._row_idx = 0
        return self

    def fetchone(self):
        if not self._last_result or self._row_idx >= len(self._last_result.rows):
            return None
        raw_row = self._last_result.rows[self._row_idx]
        self._row_idx += 1
        return DatabaseRow(self._last_result.columns, list(raw_row))

    def fetchall(self):
        if not self._last_result:
            return []
        cols = self._last_result.columns
        rows = [
            DatabaseRow(cols, list(r))
            for r in self._last_result.rows[self._row_idx:]
        ]
        self._row_idx = len(self._last_result.rows)
        return rows


class LibsqlConnectionAdapter:
    def __init__(self, client):
        self.client = client

    def cursor(self):
        return LibsqlCursorAdapter(self.client)

    def execute(self, sql: str, params: Any = None):
        c = self.cursor()
        c.execute(sql, params)
        return c

    def commit(self):
        pass

    def rollback(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


class KnowledgeVectorStore:
    def __init__(self, db_path: Optional[Path] = None):
        self.turso_url = os.environ.get("TURSO_DATABASE_URL") or os.environ.get("DATABASE_URL")
        self.turso_token = os.environ.get("TURSO_AUTH_TOKEN")
        env_db = os.environ.get("DB_PATH")
        self.db_path = str(env_db or db_path or settings.DB_PATH)
        try:
            self._init_db()
        except Exception:
            pass

    def _get_connection(self):
        if self.turso_url:
            if not self.turso_token:
                is_prod = bool(os.environ.get("VERCEL") or os.environ.get("ENV") == "production")
                if is_prod:
                    raise RuntimeError("TURSO_DATABASE_URL is set for production, but TURSO_AUTH_TOKEN is missing. Production requires valid authentication token.")
            else:
                try:
                    import libsql_client
                    client = libsql_client.create_client_sync(self.turso_url, auth_token=self.turso_token)
                    is_prod = bool(os.environ.get("VERCEL") or os.environ.get("ENV") == "production")
                    if is_prod:
                        client.execute("SELECT 1")
                    return LibsqlConnectionAdapter(client)
                except Exception as e:
                    is_prod = bool(os.environ.get("VERCEL") or os.environ.get("ENV") == "production")
                    if is_prod:
                        raise RuntimeError(f"Failed to connect to persistent Turso database: {str(e)}")
        
        try:
            conn = sqlite3.connect(self.db_path, timeout=10.0)
        except Exception:
            conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True, timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA busy_timeout = 5000;")
            conn.execute("PRAGMA foreign_keys = ON;")
        except Exception:
            pass
        return conn

    def get_storage_status(self) -> Dict[str, Any]:
        has_turso = bool(self.turso_url and self.turso_token)
        clean_path = self.db_path.replace("\\", "/").lower()
        is_tmp = "/tmp" in clean_path or "temp" in clean_path
        is_prod = bool(os.environ.get("VERCEL") or os.environ.get("ENV") == "production")
        
        status = "connected"
        connection_health = "healthy"
        journal_mode = "unknown"
        applied_migrations = []
        error_msg = None
        
        try:
            with self._get_connection() as conn:
                c = conn.cursor()
                if not has_turso:
                    try:
                        c.execute("PRAGMA journal_mode;")
                        r = c.fetchone()
                        if r:
                            journal_mode = str(r[0])
                    except Exception:
                        pass
                else:
                    journal_mode = "remote_libsql"
                
                c.execute("SELECT version, name, applied_at FROM schema_migrations ORDER BY applied_at ASC;")
                applied_migrations = [dict(m) for m in c.fetchall()]
        except Exception as e:
            status = "error"
            connection_health = f"unhealthy: {type(e).__name__}"
            error_msg = str(e)
            
        is_durable = (has_turso and status == "connected") or (not is_tmp and Path(self.db_path).exists() and not is_prod)
        
        recs = []
        if has_turso and status != "connected":
            recs.append("CRITICAL: Turso connection configured but health check failed. Inspect credentials and network connectivity.")
        elif not is_durable:
            recs.append("CRITICAL: Active database is stored on an ephemeral path (/tmp) on serverless microVMs. State will reset on container recycling.")
            recs.append("Configure TURSO_DATABASE_URL and TURSO_AUTH_TOKEN in Vercel environment variables for managed persistent edge storage.")
            recs.append("Alternatively, deploy on persistent container hosting (Railway/Render/AWS) with a persistent volume.")
            
        engine = "turso_libsql" if has_turso else ("sqlite_local" if not is_tmp else "sqlite_ephemeral")
        masked_path = self.db_path
        if has_turso:
            host = self.turso_url.split("://")[-1].split("/")[0]
            masked_path = f"libsql://{host}"

        res = {
            "status": status,
            "engine": engine,
            "is_durable": is_durable,
            "database_path": masked_path,
            "journal_mode": journal_mode,
            "migrations_count": len(applied_migrations),
            "migrations": applied_migrations,
            "connection_health": connection_health,
            "recommendations": recs
        }
        if error_msg:
            res["error"] = error_msg
        return res

    def list_active_articles(self, limit: int = 50, account_id: str = "acc_default") -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            c = conn.cursor()
            c.execute(
                "SELECT id, url, title, category, screenshot_count, is_active, updated_at "
                "FROM articles WHERE is_active = 1 AND (account_id = ? OR account_id = 'acc_default') "
                "ORDER BY updated_at DESC LIMIT ?",
                (account_id, limit)
            )
            return [dict(row) for row in c.fetchall()]

    def list_escalations(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT * FROM escalations ORDER BY created_at DESC LIMIT ?", (limit,))
            return [dict(row) for row in c.fetchall()]

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Baseline migration tracker table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL
            );
            """)

            # -----------------------------------------------------------------
            # Migration 001: Baseline schema
            # -----------------------------------------------------------------
            cursor.execute("SELECT COUNT(*) FROM schema_migrations WHERE version = '001_baseline_schema'")
            if cursor.fetchone()[0] == 0:
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
                    sitemap_source TEXT,
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
                    last_indexed_at TEXT,
                    archived_at TEXT NOT NULL,
                    reason TEXT,
                    metadata_json TEXT,
                    version INTEGER DEFAULT 1
                );
                """)
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS article_version_history (
                    id TEXT PRIMARY KEY,
                    article_id TEXT NOT NULL,
                    url TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    content_hash TEXT NOT NULL,
                    raw_text TEXT,
                    title TEXT,
                    metadata_json TEXT,
                    created_at TEXT NOT NULL
                );
                """)
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS sitemap_sources (
                    id TEXT PRIMARY KEY,
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
                    FOREIGN KEY (source_id) REFERENCES sitemap_sources(id)
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
                cursor.execute("""
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
                """)
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS feedback_rules (
                    id TEXT PRIMARY KEY,
                    category TEXT NOT NULL,
                    email_id TEXT,
                    rule_text TEXT NOT NULL,
                    original_draft TEXT,
                    final_sent TEXT,
                    diff_summary TEXT,
                    account_id TEXT,
                    created_at TEXT NOT NULL
                );
                """)
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS email_folder_state (
                    email_id TEXT PRIMARY KEY,
                    folder TEXT DEFAULT 'inbox',
                    is_starred INTEGER DEFAULT 0,
                    is_read INTEGER DEFAULT 1,
                    setting_label TEXT,
                    raw_json TEXT,
                    updated_at TEXT NOT NULL
                );
                """)
                cursor.execute("""
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
                """)
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS autonomy_global_config (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );
                """)
                now_str = datetime.now(timezone.utc).isoformat()
                cursor.execute("INSERT OR REPLACE INTO schema_migrations (version, name, applied_at) VALUES ('001_baseline_schema', 'Initial core tables for Knowledge Brain, Inbox and Autonomy', ?)", (now_str,))
                conn.commit()

            # -----------------------------------------------------------------
            # Migration 002: Multi-tenant account isolation
            # -----------------------------------------------------------------
            cursor.execute("SELECT COUNT(*) FROM schema_migrations WHERE version = '002_multi_tenant_isolation'")
            if cursor.fetchone()[0] == 0:
                tenant_tables = [
                    "articles", "chunks", "escalations", "archived_articles",
                    "article_version_history", "sitemap_urls", "sitemap_refresh_runs",
                    "gmail_accounts", "sent_emails", "feedback_rules", "email_audit_log"
                ]
                for tbl in tenant_tables:
                    try:
                        cursor.execute(f"PRAGMA table_info({tbl})")
                        cols = [r[1] for r in cursor.fetchall()]
                        if "account_id" not in cols:
                            cursor.execute(f"ALTER TABLE {tbl} ADD COLUMN account_id TEXT NOT NULL DEFAULT 'acc_default'")
                    except Exception:
                        pass

                # Convert sitemap_sources to UNIQUE(account_id, root_sitemap_url)
                try:
                    cursor.execute("PRAGMA table_info(sitemap_sources)")
                    sm_cols = [r[1] for r in cursor.fetchall()]
                    if "account_id" not in sm_cols:
                        cursor.execute("""
                        CREATE TABLE sitemap_sources_mt (
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
                        """)
                        cursor.execute("""
                        INSERT INTO sitemap_sources_mt (id, account_id, name, root_sitemap_url, is_enabled, refresh_enabled, refresh_interval_days, missing_threshold, last_checked_at, last_successful_refresh_at, next_check_at, status, error_summary, created_at, updated_at)
                        SELECT id, 'acc_default', name, root_sitemap_url, is_enabled, refresh_enabled, refresh_interval_days, missing_threshold, last_checked_at, last_successful_refresh_at, next_check_at, status, error_summary, created_at, updated_at
                        FROM sitemap_sources;
                        """)
                        cursor.execute("DROP TABLE sitemap_sources;")
                        cursor.execute("ALTER TABLE sitemap_sources_mt RENAME TO sitemap_sources;")
                except Exception:
                    pass

                # Convert autonomy_settings to PRIMARY KEY(account_id, category)
                try:
                    cursor.execute("PRAGMA table_info(autonomy_settings)")
                    auto_cols = [r[1] for r in cursor.fetchall()]
                    if "account_id" not in auto_cols:
                        cursor.execute("""
                        CREATE TABLE autonomy_settings_mt (
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
                        """)
                        cursor.execute("""
                        INSERT INTO autonomy_settings_mt (account_id, category, name, icon, threshold_x, consecutive_streak, is_eligible, is_guarded, is_enabled, total_approved, total_edited, confidence_score, last_approved_at, updated_at)
                        SELECT 'acc_default', category, name, icon, threshold_x, consecutive_streak, is_eligible, is_guarded, is_enabled, total_approved, total_edited, confidence_score, last_approved_at, updated_at
                        FROM autonomy_settings;
                        """)
                        cursor.execute("DROP TABLE autonomy_settings;")
                        cursor.execute("ALTER TABLE autonomy_settings_mt RENAME TO autonomy_settings;")
                except Exception:
                    pass

                # Convert email_folder_state to PRIMARY KEY(account_id, email_id)
                try:
                    cursor.execute("PRAGMA table_info(email_folder_state)")
                    ef_cols = [r[1] for r in cursor.fetchall()]
                    if "account_id" not in ef_cols:
                        cursor.execute("""
                        CREATE TABLE email_folder_state_mt (
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
                        """)
                        cursor.execute("""
                        INSERT INTO email_folder_state_mt (account_id, email_id, folder, is_starred, is_read, setting_label, raw_json, updated_at)
                        SELECT 'acc_default', email_id, folder, is_starred, is_read, setting_label, raw_json, updated_at
                        FROM email_folder_state;
                        """)
                        cursor.execute("DROP TABLE email_folder_state;")
                        cursor.execute("ALTER TABLE email_folder_state_mt RENAME TO email_folder_state;")
                except Exception:
                    pass

                # Create multi-tenant indexes
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_sitemap_sources_acc ON sitemap_sources(account_id);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_sitemap_urls_acc ON sitemap_urls(account_id, source_id);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_archived_articles_acc ON archived_articles(account_id);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_gmail_accounts_acc ON gmail_accounts(account_id);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_sent_emails_acc ON sent_emails(account_id);")

                now_str = datetime.now(timezone.utc).isoformat()
                cursor.execute("INSERT OR REPLACE INTO schema_migrations (version, name, applied_at) VALUES ('002_multi_tenant_isolation', 'Multi-tenant account_id isolation and indexes', ?)", (now_str,))
                conn.commit()

            # -----------------------------------------------------------------
            # Migration 003: Auth, user identities, and token revocation
            # -----------------------------------------------------------------
            cursor.execute("SELECT COUNT(*) FROM schema_migrations WHERE version = '003_auth_and_sessions'")
            if cursor.fetchone()[0] == 0:
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_accounts (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    plan TEXT DEFAULT 'enterprise',
                    created_at TEXT NOT NULL
                );
                """)
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'consultant',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (account_id) REFERENCES user_accounts(id)
                );
                """)
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS revoked_tokens (
                    jti TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    revoked_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );
                """)
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_revoked_tokens_jti ON revoked_tokens(jti);")
                now_str = datetime.now(timezone.utc).isoformat()
                cursor.execute("INSERT OR IGNORE INTO user_accounts (id, name, created_at) VALUES ('acc_default', 'Default Organization', ?);", (now_str,))
                cursor.execute("INSERT OR IGNORE INTO users (id, account_id, email, password_hash, role, created_at) VALUES ('consultant_lead_01', 'acc_default', 'consultant@apex.io', 'demo_hash_consultant', 'Lead AI Consultant', ?);", (now_str,))
                cursor.execute("INSERT OR REPLACE INTO schema_migrations (version, name, applied_at) VALUES ('003_auth_and_sessions', 'User accounts, credential records, and JWT token revocation table', ?)", (now_str,))
                conn.commit()

            # Seed default documentation source for acc_default if empty
            cursor.execute("SELECT COUNT(*) FROM sitemap_sources WHERE account_id = 'acc_default'")
            if cursor.fetchone()[0] == 0:
                now_str = datetime.now(timezone.utc).isoformat()
                cursor.execute("""
                INSERT INTO sitemap_sources (id, account_id, name, root_sitemap_url, is_enabled, refresh_enabled, refresh_interval_days, missing_threshold, status, created_at, updated_at)
                VALUES ('src_default_bd', 'acc_default', 'Brilliant Directories Documentation', 'https://support.brilliantdirectories.com/support/sitemap.xml', 1, 1, 7, 15, 'active', ?, ?)
                """, (now_str, now_str))

            # Seed default autonomy categories for acc_default if empty
            cursor.execute("SELECT COUNT(*) FROM autonomy_settings WHERE account_id = 'acc_default'")
            if cursor.fetchone()[0] == 0:
                now_str = datetime.now(timezone.utc).isoformat()
                initial_cats = [
                    ("filters", "Filters & Facets", "🔍", 3, 0, 0, 0.88),
                    ("home_page", "Home Page Layout", "🏠", 3, 0, 0, 0.85),
                    ("domain_management", "Domain & DNS Management", "🌐", 3, 0, 0, 0.90),
                    ("header", "Header Layout & Logo", "📑", 3, 0, 0, 0.87),
                    ("main_menu", "Main Menu & Navigation", "🧭", 3, 0, 0, 0.86),
                    ("footer", "Footer Layout & Links", "🦶", 3, 0, 0, 0.85),
                    ("general_settings", "General Settings", "⚙️", 3, 0, 0, 0.82),
                    ("design_settings", "Design & CSS Settings", "🎨", 3, 0, 0, 0.84),
                    ("managers", "Managers & Admin Roles", "👥", 3, 0, 0, 0.89),
                    ("billing", "Billing & Subscriptions", "💳", 3, 0, 1, 0.95),
                    ("staging", "Staging & Development", "🧪", 3, 0, 0, 0.80),
                ]
                for cat_id, cat_name, cat_icon, th_x, el, gd, conf in initial_cats:
                    cursor.execute("""
                    INSERT OR IGNORE INTO autonomy_settings 
                    (account_id, category, name, icon, threshold_x, consecutive_streak, is_eligible, is_guarded, is_enabled, confidence_score, updated_at)
                    VALUES ('acc_default', ?, ?, ?, ?, 0, ?, ?, 1, ?, ?)
                    """, (cat_id, cat_name, cat_icon, th_x, el, gd, conf, now_str))

            conn.commit()

    # =========================================================================
    # USER ACCOUNTS & TOKEN REVOCATION (PHASE 2 & 3)
    # =========================================================================
    def is_token_revoked(self, jti: str) -> bool:
        if not jti:
            return False
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM revoked_tokens WHERE jti = ?", (jti,))
            return cursor.fetchone() is not None

    def revoke_token(self, jti: str, account_id: str, user_id: str, expires_at: Optional[str] = None) -> bool:
        now_str = datetime.now(timezone.utc).isoformat()
        exp_str = expires_at or (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT OR REPLACE INTO revoked_tokens (jti, account_id, user_id, revoked_at, expires_at)
            VALUES (?, ?, ?, ?, ?)
            """, (jti, account_id, user_id, now_str, exp_str))
            conn.commit()
            return True

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE email = ?", (email.strip().lower(),))
            row = cursor.fetchone()
            return dict(row) if row else None

    def create_user_account(self, account_id: str, account_name: str) -> Dict[str, Any]:
        now_str = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO user_accounts (id, name, created_at) VALUES (?, ?, ?)", (account_id, account_name, now_str))
            conn.commit()
            return {"id": account_id, "name": account_name, "created_at": now_str}

    # =========================================================================
    # ARTICLE INGESTION & VERSIONING
    # =========================================================================
    def upsert_article(
        self,
        article_id: str,
        url: str,
        title: str,
        category: str,
        content_hash: str,
        raw_text: str,
        screenshot_count: int,
        chunks_data: List[Dict[str, Any]],
        sitemap_source: Optional[str] = None,
        account_id: str = "acc_default"
    ):
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT id, content_hash, raw_text, title, updated_at FROM articles WHERE url = ? OR id = ?", (url, article_id))
            existing = cursor.fetchone()
            if existing:
                article_id = existing["id"]

            if existing and existing["content_hash"] and existing["content_hash"] != content_hash:
                cursor.execute("SELECT COUNT(*) FROM article_version_history WHERE article_id = ? OR url = ?", (article_id, url))
                ver_count = cursor.fetchone()[0] + 1
                cursor.execute("""
                INSERT INTO article_version_history (id, account_id, article_id, url, version, content_hash, raw_text, title, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    f"ver_{uuid.uuid4().hex[:8]}",
                    account_id,
                    article_id,
                    url,
                    ver_count,
                    existing["content_hash"],
                    existing["raw_text"],
                    existing["title"],
                    json.dumps({"reason": "content_change_detected"}),
                    existing["updated_at"] or now
                ))

            cursor.execute("""
            INSERT INTO articles (id, account_id, url, title, category, content_hash, raw_text, screenshot_count, sitemap_source, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title=excluded.title,
                category=excluded.category,
                content_hash=excluded.content_hash,
                raw_text=excluded.raw_text,
                screenshot_count=excluded.screenshot_count,
                sitemap_source=COALESCE(excluded.sitemap_source, articles.sitemap_source),
                is_active=1,
                updated_at=excluded.updated_at;
            """, (article_id, account_id, url, title, category, content_hash, raw_text, screenshot_count, sitemap_source, now, now))

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
                INSERT INTO chunks (id, account_id, article_id, url, article_title, section_heading, content, image_urls, image_descriptions, embedding_json, is_active, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                """, (cid, account_id, article_id, url, title, section, content, img_urls, img_descs, emb_json, now))

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

    def archive_article(
        self,
        url: str,
        reason: str = "Missing from sitemap across configured consecutive checks",
        checks_count: int = 15,
        source_url: Optional[str] = None,
        account_id: str = "acc_default"
    ) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()

            if source_url:
                cursor.execute("""
                SELECT COUNT(*) FROM sitemap_urls
                WHERE url = ? AND source_id != ? AND status = 'active'
                """, (url, source_url))
                shared_urls = cursor.fetchone()[0]

                cursor.execute("""
                SELECT COUNT(*) FROM articles 
                WHERE url = ? AND sitemap_source IS NOT NULL AND sitemap_source != ? AND is_active = 1
                """, (url, source_url))
                shared_active = cursor.fetchone()[0]
                if shared_active > 0 or shared_urls > 0:
                    return False

            cursor.execute("""
            SELECT id, url, title, category, content_hash, raw_text, sitemap_source, updated_at 
            FROM articles WHERE url = ?
            """, (url,))
            row = cursor.fetchone()

            article_id = row["id"] if row else f"archived_{uuid.uuid4().hex[:8]}"
            title = row["title"] if row else url.split("/")[-1].replace("-", " ").title()
            cat = row["category"] if row else "General"
            chash = row["content_hash"] if row else hashlib.sha256(url.encode()).hexdigest()[:16]
            rtext = row["raw_text"] if row else ""
            src_val = row["sitemap_source"] if row and row["sitemap_source"] else (source_url or "sitemap")
            last_indexed = row["updated_at"] if row else datetime.now(timezone.utc).isoformat()
            now = datetime.now(timezone.utc).isoformat()

            cursor.execute("""
            SELECT id, section_heading, content, image_urls, image_descriptions 
            FROM chunks WHERE article_id = ? OR url = ?
            """, (article_id, url))
            chunks_rows = [dict(cr) for cr in cursor.fetchall()]
            meta_json = json.dumps({
                "chunks": chunks_rows,
                "chunks_count": len(chunks_rows),
                "original_article_id": article_id,
                "archived_by": "automated_sitemap_refresh"
            })

            cursor.execute("SELECT COUNT(*) FROM article_version_history WHERE url = ?", (url,))
            ver_count = cursor.fetchone()[0] + 1

            cursor.execute("""
            INSERT OR REPLACE INTO archived_articles (
                id, account_id, url, title, category, content_hash, raw_text, sitemap_source,
                consecutive_missing_checks, last_indexed_at, archived_at, reason, metadata_json, version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                article_id, account_id, url, title, cat, chash, rtext, src_val,
                checks_count, last_indexed, now, reason, meta_json, ver_count
            ))

            ver_id = f"ver_{uuid.uuid4().hex[:8]}"
            cursor.execute("""
            INSERT INTO article_version_history (
                id, account_id, article_id, url, version, content_hash, raw_text, title, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (ver_id, account_id, article_id, url, ver_count, chash, rtext, title, meta_json, now))

            cursor.execute("UPDATE articles SET is_active = 0, updated_at = ? WHERE id = ?", (now, article_id))
            cursor.execute("UPDATE chunks SET is_active = 0 WHERE article_id = ?", (article_id,))

            cursor.execute("SELECT id FROM chunks WHERE article_id = ?", (article_id,))
            for r in cursor.fetchall():
                cursor.execute("DELETE FROM chunks_fts WHERE chunk_id = ?", (r["id"],))

            conn.commit()
            return True

    def get_archived_articles(self, search_query: Optional[str] = None, limit: int = 50, account_id: str = "acc_default") -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if search_query and search_query.strip():
                pattern = f"%{search_query.strip()}%"
                cursor.execute("""
                SELECT id, account_id, url, title, category, content_hash, sitemap_source, 
                       consecutive_missing_checks, last_indexed_at, archived_at, reason, version,
                       LENGTH(COALESCE(raw_text, '')) as content_length,
                       SUBSTR(COALESCE(raw_text, ''), 1, 240) as content_snippet
                FROM archived_articles
                WHERE account_id = ? AND (title LIKE ? OR url LIKE ? OR raw_text LIKE ? OR reason LIKE ?)
                ORDER BY archived_at DESC LIMIT ?
                """, (account_id, pattern, pattern, pattern, pattern, limit))
            else:
                cursor.execute("""
                SELECT id, account_id, url, title, category, content_hash, sitemap_source, 
                       consecutive_missing_checks, last_indexed_at, archived_at, reason, version,
                       LENGTH(COALESCE(raw_text, '')) as content_length,
                       SUBSTR(COALESCE(raw_text, ''), 1, 240) as content_snippet
                FROM archived_articles
                WHERE account_id = ?
                ORDER BY archived_at DESC LIMIT ?
                """, (account_id, limit))
            return [dict(r) for r in cursor.fetchall()]

    def get_archived_article_details(self, identifier: str, account_id: str = "acc_default") -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM archived_articles WHERE (id = ? OR url = ?) AND account_id = ?", (identifier, identifier, account_id))
            row = cursor.fetchone()
            if not row:
                return None
            res = dict(row)
            chunks = []
            if res.get("metadata_json"):
                try:
                    meta = json.loads(res["metadata_json"])
                    chunks = meta.get("chunks", [])
                except Exception:
                    chunks = []
            res["chunks"] = chunks

            cursor.execute("SELECT * FROM article_version_history WHERE url = ? AND account_id = ? ORDER BY version ASC", (res["url"], account_id))
            res["versions"] = [dict(v) for v in cursor.fetchall()]
            return res

    def restore_archived_article(self, identifier: str, account_id: str = "acc_default") -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM archived_articles WHERE (id = ? OR url = ?) AND account_id = ?", (identifier, identifier, account_id))
            row = cursor.fetchone()
            if not row:
                return False

            article_id = row["id"]
            url = row["url"]
            title = row["title"]
            now = datetime.now(timezone.utc).isoformat()

            cursor.execute("UPDATE articles SET is_active = 1, updated_at = ? WHERE id = ? OR url = ?", (now, article_id, url))
            if cursor.rowcount == 0:
                cursor.execute("""
                INSERT OR REPLACE INTO articles (id, account_id, url, title, category, content_hash, raw_text, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """, (article_id, account_id, url, title, row["category"], row["content_hash"], row["raw_text"], now, now))

            cursor.execute("UPDATE chunks SET is_active = 1 WHERE article_id = ? OR url = ?", (article_id, url))
            cursor.execute("SELECT id, section_heading, content, image_descriptions FROM chunks WHERE article_id = ? OR url = ?", (article_id, url))
            existing_chunks = cursor.fetchall()

            if existing_chunks:
                for c in existing_chunks:
                    cursor.execute("DELETE FROM chunks_fts WHERE chunk_id = ?", (c["id"],))
                    cursor.execute("""
                    INSERT INTO chunks_fts (chunk_id, article_title, section_heading, content, image_descriptions)
                    VALUES (?, ?, ?, ?, ?)
                    """, (c["id"], title, c["section_heading"], c["content"], c["image_descriptions"]))
            elif row["metadata_json"]:
                try:
                    meta = json.loads(row["metadata_json"])
                    for c in meta.get("chunks", []):
                        cid = c.get("id", f"chk_{uuid.uuid4().hex[:8]}")
                        s_heading = c.get("section_heading", "Overview")
                        c_text = c.get("content", "")
                        imgs_str = json.dumps(c.get("image_urls", []))
                        descs_str = json.dumps(c.get("image_descriptions", []))
                        cursor.execute("""
                        INSERT OR REPLACE INTO chunks (id, account_id, article_id, url, article_title, section_heading, content, image_urls, image_descriptions, is_active, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                        """, (cid, account_id, article_id, url, title, s_heading, c_text, imgs_str, descs_str, now))
                        cursor.execute("""
                        INSERT INTO chunks_fts (chunk_id, article_title, section_heading, content, image_descriptions)
                        VALUES (?, ?, ?, ?, ?)
                        """, (cid, title, s_heading, c_text, descs_str))
                except Exception:
                    pass

            cursor.execute("DELETE FROM archived_articles WHERE (id = ? OR url = ?) AND account_id = ?", (article_id, url, account_id))
            conn.commit()
            return True

    def permanent_delete_archived_article(self, identifier: str, account_id: str = "acc_default") -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, url FROM archived_articles WHERE (id = ? OR url = ?) AND account_id = ?", (identifier, identifier, account_id))
            row = cursor.fetchone()
            if not row:
                return False
            art_id = row["id"]
            url = row["url"]

            cursor.execute("SELECT id FROM chunks WHERE article_id = ? OR url = ?", (art_id, url))
            for r in cursor.fetchall():
                cursor.execute("DELETE FROM chunks_fts WHERE chunk_id = ?", (r["id"],))

            cursor.execute("DELETE FROM chunks WHERE article_id = ? OR url = ?", (art_id, url))
            cursor.execute("DELETE FROM articles WHERE (id = ? OR url = ?) AND account_id = ?", (art_id, url, account_id))
            cursor.execute("DELETE FROM article_version_history WHERE url = ? AND account_id = ?", (url, account_id))
            cursor.execute("DELETE FROM archived_articles WHERE (id = ? OR url = ?) AND account_id = ?", (art_id, url, account_id))
            conn.commit()
            return True

    def search_archived_articles(self, query: str, limit: int = 10, account_id: str = "acc_default") -> List[Dict[str, Any]]:
        pattern = f"%{query.strip()}%"
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT id, account_id, url, title, category, content_hash, sitemap_source, archived_at, reason,
                   LENGTH(COALESCE(raw_text, '')) as content_length,
                   SUBSTR(COALESCE(raw_text, ''), 1, 300) as matched_snippet
            FROM archived_articles
            WHERE account_id = ? AND (title LIKE ? OR raw_text LIKE ? OR reason LIKE ?)
            ORDER BY archived_at DESC LIMIT ?
            """, (account_id, pattern, pattern, pattern, limit))
            return [dict(r) for r in cursor.fetchall()]

    # =========================================================================
    # SITEMAP SOURCES & REFRESH RUNS (MULTI-TENANT ENFORCED)
    # =========================================================================
    def create_sitemap_source(
        self,
        name: str,
        root_url: str,
        refresh_interval_days: int = 7,
        missing_threshold: int = 15,
        account_id: str = "acc_default"
    ) -> Dict[str, Any]:
        src_id = f"src_{uuid.uuid4().hex[:8]}"
        now_dt = datetime.now(timezone.utc)
        now_str = now_dt.isoformat()
        next_check = (now_dt + timedelta(days=refresh_interval_days)).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO sitemap_sources (id, account_id, name, root_sitemap_url, is_enabled, refresh_enabled, refresh_interval_days, missing_threshold, next_check_at, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, 1, 1, ?, ?, ?, 'active', ?, ?)
            """, (src_id, account_id, name, root_url, refresh_interval_days, missing_threshold, next_check, now_str, now_str))
            conn.commit()
        return self.get_sitemap_source(src_id, account_id=account_id)

    def list_sitemap_sources(self, account_id: str = "acc_default") -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM sitemap_sources WHERE account_id = ? ORDER BY created_at ASC", (account_id,))
            sources = [dict(r) for r in cursor.fetchall()]
            for s in sources:
                try:
                    cursor.execute("SELECT COUNT(*) FROM articles WHERE sitemap_source = ? AND is_active = 1", (s["root_sitemap_url"],))
                    s["active_articles_count"] = cursor.fetchone()[0]
                except Exception:
                    s["active_articles_count"] = 0
            return sources

    def get_sitemap_source(self, source_id: str, account_id: str = "acc_default") -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM sitemap_sources WHERE (id = ? OR root_sitemap_url = ?) AND account_id = ?", (source_id, source_id, account_id))
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

    def link_url_to_source(self, source_url: str, page_url: str, account_id: str = "acc_default") -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM sitemap_sources WHERE (id = ? OR root_sitemap_url = ?) AND account_id = ?", (source_url, source_url, account_id))
            row = cursor.fetchone()
            if row:
                real_src_id = row["id"]
            else:
                real_src_id = f"src_{uuid.uuid4().hex[:8]}"
                cursor.execute("""
                INSERT OR IGNORE INTO sitemap_sources (id, account_id, name, root_sitemap_url, is_enabled, refresh_enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, 1, 1, ?, ?)
                """, (real_src_id, account_id, source_url.split("/")[-1] or "Secondary Source", source_url, now, now))

            cursor.execute("""
            INSERT OR REPLACE INTO sitemap_urls (id, account_id, source_id, url, normalized_url, status, last_seen_at, last_checked_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)
            """, (f"su_{uuid.uuid4().hex[:8]}", account_id, real_src_id, page_url, page_url.strip().lower(), now, now, now, now))
            conn.commit()

    def update_sitemap_source(self, source_id: str, account_id: str = "acc_default", **kwargs) -> Optional[Dict[str, Any]]:
        valid_keys = {"name", "is_enabled", "refresh_enabled", "refresh_interval_days", "missing_threshold", "status", "last_checked_at", "last_successful_refresh_at", "next_check_at", "error_summary"}
        updates = {k: v for k, v in kwargs.items() if k in valid_keys}
        if not updates:
            return self.get_sitemap_source(source_id, account_id=account_id)
        if "refresh_interval_days" in updates and "next_check_at" not in updates:
            try:
                days = int(updates["refresh_interval_days"])
                updates["next_check_at"] = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
            except Exception:
                pass
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
        values = list(updates.values()) + [source_id, account_id]
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"UPDATE sitemap_sources SET {set_clause} WHERE id = ? AND account_id = ?", values)
            conn.commit()
        return self.get_sitemap_source(source_id, account_id=account_id)

    def delete_sitemap_source(self, source_id: str, account_id: str = "acc_default", purge_content: bool = False) -> bool:
        src = self.get_sitemap_source(source_id, account_id=account_id)
        if not src:
            return False
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if purge_content:
                try:
                    cursor.execute("SELECT url FROM articles WHERE sitemap_source = ? AND account_id = ?", (src["root_sitemap_url"], account_id))
                    urls = [r[0] for r in cursor.fetchall()]
                    for u in urls:
                        cursor.execute("SELECT COUNT(*) FROM articles WHERE url = ? AND sitemap_source != ? AND is_active = 1", (u, src["root_sitemap_url"]))
                        shared_count = cursor.fetchone()[0]
                        if shared_count == 0:
                            self.archive_article(u, reason=f"Sitemap source '{src['name']}' deleted by user", account_id=account_id)
                except Exception:
                    pass
            cursor.execute("DELETE FROM sitemap_sources WHERE id = ? AND account_id = ?", (source_id, account_id))
            conn.commit()
            return True

    def record_refresh_run(self, source_id: str, account_id: str = "acc_default", **kwargs) -> str:
        run_id = f"run_{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc).isoformat()
        cols = ["id", "account_id", "source_id", "started_at", "status"]
        vals = [run_id, account_id, source_id, kwargs.get("started_at", now), kwargs.get("status", "completed")]
        for k, v in kwargs.items():
            if k not in ["id", "account_id", "source_id", "started_at", "status"] and k in [
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

    def list_refresh_runs(self, source_id: Optional[str] = None, account_id: str = "acc_default", limit: int = 20) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if source_id:
                cursor.execute("SELECT * FROM sitemap_refresh_runs WHERE source_id = ? AND account_id = ? ORDER BY started_at DESC LIMIT ?", (source_id, account_id, limit))
            else:
                cursor.execute("SELECT * FROM sitemap_refresh_runs WHERE account_id = ? ORDER BY started_at DESC LIMIT ?", (account_id, limit))
            return [dict(r) for r in cursor.fetchall()]

    # =========================================================================
    # SEARCH & RETRIEVAL
    # =========================================================================
    def hybrid_search(self, query: str, top_k: int = 5, limit: Optional[int] = None, account_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if limit is not None:
            top_k = limit
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

            if account_id:
                cursor.execute("""
                SELECT id, article_id, url, article_title, section_heading, content,
                       image_urls, image_descriptions, embedding_json
                FROM chunks
                WHERE is_active = 1 AND (account_id = ? OR account_id = 'acc_default')
                """, (account_id,))
            else:
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

    def create_escalation(self, question: str, user_email: Optional[str] = None, reason: str = "Insufficient evidence", account_id: str = "acc_default") -> str:
        esc_id = f"ESC-{uuid.uuid4().hex[:8].upper()}"
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO escalations (id, account_id, question, status, user_email, reason, created_at)
            VALUES (?, ?, ?, 'pending', ?, ?, ?)
            """, (esc_id, account_id, question, user_email, reason, now))
            conn.commit()
        return esc_id

    def list_escalations(self, status: Optional[str] = None, account_id: str = "acc_default") -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if status:
                cursor.execute("SELECT * FROM escalations WHERE status = ? AND account_id = ? ORDER BY created_at DESC", (status, account_id))
            else:
                cursor.execute("SELECT * FROM escalations WHERE account_id = ? ORDER BY created_at DESC", (account_id,))
            return [dict(row) for row in cursor.fetchall()]

    def resolve_escalation(self, esc_id: str, expert_answer: str, supporting_notes: Optional[str], approved_by: str, account_id: str = "acc_default") -> bool:
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM escalations WHERE id = ? AND account_id = ?", (esc_id, account_id))
            row = cursor.fetchone()
            if not row:
                return False

            cursor.execute("""
            UPDATE escalations
            SET status = 'resolved', expert_answer = ?, supporting_notes = ?, approved_by = ?, resolved_at = ?
            WHERE id = ? AND account_id = ?
            """, (expert_answer, supporting_notes, approved_by, now, esc_id, account_id))
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
            chunks_data=[expert_chunk],
            account_id=account_id
        )
        return True

    def get_stats(self, account_id: str = "acc_default") -> Dict[str, Any]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM articles WHERE is_active = 1")
            active_articles = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM chunks WHERE is_active = 1")
            active_chunks = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM escalations WHERE status = 'pending' AND account_id = ?", (account_id,))
            pending_escalations = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM escalations WHERE status = 'resolved' AND account_id = ?", (account_id,))
            resolved_escalations = cursor.fetchone()[0]
            return {
                "active_articles": active_articles,
                "active_chunks": active_chunks,
                "pending_escalations": pending_escalations,
                "resolved_escalations": resolved_escalations
            }

    # =========================================================================
    # GMAIL ACCOUNTS & AUDIT LOGGING (UPGRADE B & PHASE 2 MULTI-TENANT)
    # =========================================================================
    def save_gmail_account(
        self,
        email_address: str,
        encrypted_access_token: str,
        encrypted_refresh_token: str,
        token_expiry: Optional[str] = None,
        scopes: Optional[str] = None,
        account_id: str = "acc_default"
    ) -> Dict[str, Any]:
        acc_id = f"acc_{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM gmail_accounts WHERE email_address = ? AND account_id = ?", (email_address, account_id))
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
                WHERE id = ? AND account_id = ?
                """, (encrypted_access_token, encrypted_refresh_token, token_expiry, scopes, now, acc_id, account_id))
            else:
                cursor.execute("""
                INSERT INTO gmail_accounts (
                    id, account_id, email_address, connection_status, scopes,
                    encrypted_access_token, encrypted_refresh_token,
                    token_expiry, created_at, updated_at
                ) VALUES (?, ?, ?, 'connected', ?, ?, ?, ?, ?, ?)
                """, (acc_id, account_id, email_address, scopes, encrypted_access_token, encrypted_refresh_token, token_expiry, now, now))
            conn.commit()
        return self.get_gmail_account(acc_id, account_id=account_id)

    def get_gmail_account(self, account_id_or_email: str, account_id: str = "acc_default") -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM gmail_accounts WHERE (id = ? OR email_address = ?) AND account_id = ?", (account_id_or_email, account_id_or_email, account_id))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_active_gmail_account(self, account_id: str = "acc_default") -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM gmail_accounts WHERE connection_status = 'connected' AND account_id = ? ORDER BY updated_at DESC LIMIT 1", (account_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def disconnect_gmail_account(self, account_id_or_email: str, account_id: str = "acc_default") -> bool:
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            UPDATE gmail_accounts
            SET connection_status = 'disconnected',
                encrypted_access_token = NULL,
                updated_at = ?
            WHERE (id = ? OR email_address = ?) AND account_id = ?
            """, (now, account_id_or_email, account_id_or_email, account_id))
            conn.commit()
            return cursor.rowcount > 0

    def update_gmail_sync(self, account_id_val: str, history_id: Optional[str] = None, error: Optional[str] = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            UPDATE gmail_accounts
            SET last_sync_at = ?, history_id = COALESCE(?, history_id), last_sync_error = ?, updated_at = ?
            WHERE id = ?
            """, (now, history_id, error, now, account_id_val))
            conn.commit()

    def record_email_audit(
        self,
        event_type: str,
        actor_type: str = "system",
        decision: Optional[str] = None,
        reason: Optional[str] = None,
        email_id: Optional[str] = None,
        account_id: str = "acc_default",
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

    # =========================================================================
    # AUTONOMY SETTINGS & FEEDBACK RULES (MULTI-TENANT ENFORCED)
    # =========================================================================
    def get_autonomy_settings(self, category: Optional[str] = None, account_id: str = "acc_default") -> Dict[str, Any]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if category:
                cursor.execute("SELECT * FROM autonomy_settings WHERE category = ? AND account_id = ?", (category, account_id))
                row = cursor.fetchone()
                return dict(row) if row else {}
            cursor.execute("SELECT * FROM autonomy_settings WHERE account_id = ? ORDER BY name ASC", (account_id,))
            rows = cursor.fetchall()
            return {r["category"]: dict(r) for r in rows}

    def save_autonomy_setting(self, category: str, account_id: str = "acc_default", **kwargs) -> Dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        current = self.get_autonomy_settings(category, account_id=account_id)
        if not current:
            current = {
                "account_id": account_id,
                "category": category,
                "name": kwargs.get("name", category.replace("_", " ").title()),
                "icon": kwargs.get("icon", "⚙️"),
                "threshold_x": 3,
                "consecutive_streak": 0,
                "is_eligible": 0,
                "is_guarded": 1 if category == "billing" else 0,
                "is_enabled": 1,
                "total_approved": 0,
                "total_edited": 0,
                "confidence_score": 0.85,
                "last_approved_at": None,
                "updated_at": now
            }
        current.update(kwargs)
        current["updated_at"] = now
        
        if category == "billing":
            current["is_guarded"] = 1
            current["is_eligible"] = 0

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO autonomy_settings 
            (account_id, category, name, icon, threshold_x, consecutive_streak, is_eligible, is_guarded, is_enabled, total_approved, total_edited, confidence_score, last_approved_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(account_id, category) DO UPDATE SET
                name = excluded.name,
                icon = excluded.icon,
                threshold_x = excluded.threshold_x,
                consecutive_streak = excluded.consecutive_streak,
                is_eligible = excluded.is_eligible,
                is_guarded = excluded.is_guarded,
                is_enabled = excluded.is_enabled,
                total_approved = excluded.total_approved,
                total_edited = excluded.total_edited,
                confidence_score = excluded.confidence_score,
                last_approved_at = excluded.last_approved_at,
                updated_at = excluded.updated_at
            """, (
                account_id, current["category"], current["name"], current["icon"], current["threshold_x"],
                current["consecutive_streak"], current["is_eligible"], current["is_guarded"],
                current["is_enabled"], current["total_approved"], current["total_edited"],
                current["confidence_score"], current.get("last_approved_at"), current["updated_at"]
            ))
            conn.commit()
        return current

    def get_global_config(self, key: str, default: Any = None) -> Any:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM autonomy_global_config WHERE key = ?", (key,))
            row = cursor.fetchone()
            if not row:
                return default
            try:
                return json.loads(row["value"])
            except Exception:
                return row["value"]

    def set_global_config(self, key: str, value: Any) -> None:
        val_str = json.dumps(value) if not isinstance(value, str) else value
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO autonomy_global_config (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """, (key, val_str))
            conn.commit()

    def add_feedback_rule(
        self,
        category: str,
        email_id: str,
        rule_text: str,
        original_draft: str = "",
        final_sent: str = "",
        diff_summary: str = "",
        account_id: str = "acc_default"
    ) -> str:
        rule_id = f"fb_{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO feedback_rules (id, account_id, category, email_id, rule_text, original_draft, final_sent, diff_summary, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (rule_id, account_id, category, email_id, rule_text, original_draft, final_sent, diff_summary, now))
            conn.commit()
        return rule_id

    def get_feedback_rules(self, category: Optional[str] = None, account_id: str = "acc_default") -> Dict[str, List[Dict[str, Any]]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if category:
                cursor.execute("SELECT * FROM feedback_rules WHERE category = ? AND account_id = ? ORDER BY created_at DESC", (category, account_id))
            else:
                cursor.execute("SELECT * FROM feedback_rules WHERE account_id = ? ORDER BY created_at DESC", (account_id,))
            rows = cursor.fetchall()
            out: Dict[str, List[Dict[str, Any]]] = {}
            for r in rows:
                c = r["category"]
                d = dict(r)
                d["rule"] = d.get("rule_text", "")
                out.setdefault(c, []).append(d)
            return out

    def save_email_folder_state(
        self,
        email_id: str,
        account_id: str = "acc_default",
        folder: Optional[str] = None,
        is_starred: Optional[int] = None,
        is_read: Optional[int] = None,
        setting_label: Optional[str] = None,
        raw_json: Optional[str] = None
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM email_folder_state WHERE email_id = ? AND account_id = ?", (email_id, account_id))
            existing = cursor.fetchone()
            if existing:
                f_val = folder if folder is not None else existing["folder"]
                s_val = is_starred if is_starred is not None else existing["is_starred"]
                r_val = is_read if is_read is not None else existing["is_read"]
                l_val = setting_label if setting_label is not None else existing["setting_label"]
                j_val = raw_json if raw_json is not None else existing["raw_json"]
                cursor.execute("""
                UPDATE email_folder_state 
                SET folder = ?, is_starred = ?, is_read = ?, setting_label = ?, raw_json = ?, updated_at = ?
                WHERE email_id = ? AND account_id = ?
                """, (f_val, s_val, r_val, l_val, j_val, now, email_id, account_id))
            else:
                cursor.execute("""
                INSERT INTO email_folder_state (account_id, email_id, folder, is_starred, is_read, setting_label, raw_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (account_id, email_id, folder or 'inbox', is_starred or 0, is_read if is_read is not None else 1, setting_label, raw_json, now))
            conn.commit()

    def get_email_folder_states(self, account_id: str = "acc_default") -> Dict[str, Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM email_folder_state WHERE account_id = ?", (account_id,))
            rows = cursor.fetchall()
            return {r["email_id"]: dict(r) for r in rows}

    def save_sent_email_record(
        self,
        email_id: str,
        recipient: str,
        subject: str,
        body: str,
        category: str,
        is_autonomous: bool = False,
        gmail_message_id: Optional[str] = None,
        account_id: str = "acc_default"
    ) -> str:
        record_id = f"sent_{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO sent_emails (id, account_id, email_id, recipient, subject, body, category, is_autonomous, gmail_message_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (record_id, account_id, email_id, recipient, subject, body, category, 1 if is_autonomous else 0, gmail_message_id, now))
            conn.commit()
        return record_id

    def list_sent_email_records(self, limit: int = 100, account_id: str = "acc_default") -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM sent_emails WHERE account_id = ? ORDER BY created_at DESC LIMIT ?", (account_id, limit))
            return [dict(r) for r in cursor.fetchall()]

    def get_email_audit_logs(self, limit: int = 50, account_id: str = "acc_default") -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM email_audit_log WHERE account_id = ? ORDER BY created_at DESC LIMIT ?", (account_id, limit))
            return [dict(r) for r in cursor.fetchall()]

vector_store = KnowledgeVectorStore()
