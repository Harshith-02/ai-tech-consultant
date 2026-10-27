# PHASE 5.2 — FINAL MIGRATION QUALITY & SAFETY REVIEW

**Repository:** `Harshith-02/ai-tech-consultant`
**Working Branch:** `remediation/engineering-audit-fixes`
**Execution Timestamp:** 2026-10-26T22:38:00+05:30
**Audit Scope:** Independent technical evaluation of `scripts/migrate_to_turso.py`, `retrieval/vector_store.py`, and related migration harnesses before any remote database operation is authorized.

---

## 1. Executive Summary & Verdict

This Phase 5.2 review independently audits the Turso migration pipeline (`scripts/migrate_to_turso.py`) against application schemas, transaction boundaries, idempotency, failure recovery, and runtime persistence configurations.

### Final Verdict:
**READY FOR CONTROLLED REMOTE DRY RUN; NOT READY FOR LIVE REMOTE WRITES UNTIL CRITICAL SAFETY DEFECTS ARE REMEDIATED.**

- **Dry-run readiness:** `scripts/migrate_to_turso.py --dry-run` is safe to run against any endpoint because dry-run strictly exits before initializing any remote client or network socket.
- **Live write readiness:** NOT READY. Three specific defects were identified in code inspection and active testing that must be resolved prior to performing live remote data transfer:
  1. **Silent mismatch acceptance:** `migrate_to_turso.py` flags a count discrepancy as `[MISMATCH]` but does not raise an exception, allowing partial migrations to report `"success"`.
  2. **Rate limits row duplication on rerun:** Table `rate_limits` lacks a PRIMARY KEY or UNIQUE constraint, causing rows to duplicate on repeat runs.
  3. **Runtime fail-open fallback:** In `vector_store.py`, if `TURSO_DATABASE_URL` is omitted in production, the application silently falls back to ephemeral `/tmp/knowledge_brain.db` without failing closed.

---

## 2. Review Task Findings & Evidence

### Task 1: Migration DDL Alignment Against Application Real Schema
Audited `MIGRATION_DDL` in `scripts/migrate_to_turso.py` against `task1-knowledge-brain/retrieval/vector_store.py`:
- **`001_baseline_schema`:** Matches all 16 initial core tables (`articles`, `chunks`, `chunks_fts`, `escalations`, `archived_articles`, `article_version_history`, `sitemap_sources`, `sitemap_urls`, `sitemap_refresh_runs`, `gmail_accounts`, `autonomy_settings`, `autonomy_global_config`, `feedback_rules`, `email_folder_state`, `sent_emails`, `email_audit_log`).
- **`002_multi_tenant_isolation`:** Matches application column additions (`account_id` on 11 tables), reconstruction of `sitemap_sources_mt` (`UNIQUE(account_id, root_sitemap_url)`), `autonomy_settings_mt` (`PRIMARY KEY (account_id, category)`), and `email_folder_state_mt` (`PRIMARY KEY (account_id, email_id)`), and composite indexes.
- **`003_auth_and_sessions`:** Matches `user_accounts`, `users`, `revoked_tokens`, and `idx_revoked_tokens_jti`.
- **`004_secure_password_hashing`:** Matches data-only nature (no DDL required; Bcrypt hashes preserved during table row copying).
- **`005_durable_rate_limits`:** Matches `rate_limits` and `idx_rate_limits_key_time`.
- **Schema Alignment:** **CONFIRMED 100% MATCH**.

---

### Task 2: Transaction Boundaries, Error Handling, & Partial Failures
- **DDL Execution:** DDL statements are executed sequentially outside of a global transaction. If statement $K$ fails, previous statements remain applied.
- **Row Migration:** Table rows are inserted in batches of 50 via `dest_client.batch(batch_stmts)`. Each batch of 50 is atomic within libSQL, but the multi-table process is not wrapped in a single distributed transaction.
- **Rollback Limitations:** Because libSQL HTTP connections do not maintain persistent transactional state across long multi-table migrations, an unhandled exception leaves already-migrated tables populated.
- **Defect Found (Loose Error Handling):**
  Lines 543–545 of `scripts/migrate_to_turso.py`:
  ```python
  res = dest_client.execute(f'SELECT COUNT(*) FROM "{table}"')
  dest_counts[table] = res.rows[0][0]
  status_flag = "OK" if dest_counts[table] >= cnt else "MISMATCH"
  print(f"  • {table:25s}: {cnt:5d} source -> {dest_counts[table]:5d} destination [{status_flag}]")
  ```
  If `dest_counts[table] < cnt`, the script merely logs `[MISMATCH]` and continues to subsequent tables. At the end, line 574 declares `MIGRATION COMPLETED SUCCESSFULLY WITH ZERO LOSS`. It must instead raise a `RuntimeError` and fail closed immediately.

---

### Task 3: Data Integrity & Domain Model Preservation
- **Primary Keys & Constraints:** All primary keys and unique constraints are defined in destination DDL.
- **Foreign Keys:** Preserved by topological ordering in `MIGRATION_TABLES` (`user_accounts` before `users`, `articles` before `chunks`, `sitemap_sources` before `sitemap_urls`).
- **Timestamps:** ISO-8601 strings are copied verbatim without timezone conversion distortion.
- **Embeddings:** `chunks.embedding_json` (384-dimensional dense vectors) and image metadata arrays are copied verbatim as JSON strings.
- **Security Credentials:** `users.password_hash` ($2b$ Bcrypt hashes) and `revoked_tokens` JTIs are preserved without re-hashing or modification.

---

### Task 4: FTS5 Creation, Synchronization, & Search Behavior
- **Virtual Table Setup:** `chunks_fts` is created as an independent virtual table using `fts5(chunk_id UNINDEXED, article_title, section_heading, content, image_descriptions, tokenize='porter unicode61')`.
- **Triggerless Architecture:** In `vector_store.py`, FTS indexing is managed directly at the application layer on chunk creation/deletion. No database triggers exist in the SQLite source.
- **Migration Rebuild:** `scripts/migrate_to_turso.py` executes `DELETE FROM chunks_fts` and batch-inserts all active chunks (`is_active = 1`).
- **Compatibility Verified:** A test search (`MATCH 'billing'` and `MATCH 'stripe'`) verified BM25 ranking compatibility with libSQL FTS5.

---

### Task 5: Table and Row Completeness Verification
- All 20 tables in `MIGRATION_TABLES` are enumerated and checked.
- No tables are silently skipped; empty tables (`cnt == 0`) are explicitly reported and logged.
- Destination row counts are verified against source row counts.

---

### Task 6: Idempotency & Repeat-Run Duplication Audit
Active testing uncovered a critical idempotency flaw:
- **Flaw:** Table `rate_limits` does not define a PRIMARY KEY or UNIQUE constraint (`CREATE TABLE rate_limits (key TEXT NOT NULL, timestamp REAL NOT NULL)`).
- **Behavior:** In SQLite/libSQL, `INSERT OR REPLACE` on a table without a primary key or unique index acts as a standard `INSERT`, appending new rows rather than replacing existing ones.
- **Experimental Proof:**
  Executing two consecutive migration runs on an isolated test database with 1 `rate_limits` record resulted in:
  - Run 1 destination count: `1`
  - Run 2 destination count: `2` (duplicate appended)
- **Remediation Required:** `scripts/migrate_to_turso.py` must either truncate `rate_limits` (`DELETE FROM rate_limits;`) before insertion or enforce `UNIQUE(key, timestamp)` on the destination table.

---

### Task 7: Remote Safety Enforcement & Test Isolation
- **Target Flag Validation:**
  - `migrate_database()` inspects `turso_url`. If invalid or placeholder, it rejects the input with `ValueError` prior to creating any network socket.
  - Remote URLs (`libsql://`, `https://`, `http://`) mandate `--token` and `--confirm-remote`.
- **Test Isolation:**
  All automated tests in `tests/test_turso_migration_isolated.py` use local `file:` URLs pointing to temporary directories (`tmp_path`). Zero network calls are made.

---

### Task 8: Partial Migration State & Tested Recovery Strategy
- **Risk:** Network drops or unexpected aborts can leave the remote database partially migrated.
- **Recovery Strategy Tested:**
  1. Because DDL checks `SELECT COUNT(*) FROM schema_migrations WHERE version = ?`, partial DDL does not fail on restart.
  2. For tables with primary keys, re-running the script is safe and non-duplicative due to `INSERT OR REPLACE`.
  3. For `chunks_fts`, the script performs `DELETE FROM chunks_fts;` before re-indexing, preventing duplicate search documents.
  4. Once `rate_limits` truncation/uniqueness is added, full restart recovery is completely deterministic.

---

### Task 9: Runtime Configuration & Serverless Fail-Open Risk
Inspection of `task1-knowledge-brain/retrieval/vector_store.py`:
```python
def _get_connection(self):
    is_prod = bool(os.environ.get("VERCEL") or os.environ.get("ENV") == "production")
    if self.turso_url:
        if not self.turso_token:
            if is_prod:
                raise RuntimeError("TURSO_DATABASE_URL is set for production, but TURSO_AUTH_TOKEN is missing...")
```
- **Finding:** If `TURSO_DATABASE_URL` is omitted entirely in production, `self.turso_url` is None.
- **Impact:** The code falls through to `sqlite3.connect(self.db_path)`. On Vercel, this silently mounts the ephemeral `/tmp/knowledge_brain.db` database.
- **Remediation Required:** When `is_prod=True`, `vector_store.py` must fail closed if `TURSO_DATABASE_URL` is unset, preventing silent data volatility.

---

### Task 10: Git Status, Ignored Files, & Database State
- **Database Backup Checksum:**
  - `knowledge_brain.db.phase4_backup` SHA-256: `731f8918efd5651bd7407c1ebcc7d02f520eb1bc8666b4025ddf16ec2c6af1dd` (Unmodified since creation).
- **Active Database Records Check:**
  - `articles`: 83 rows intact.
  - `chunks`: 454 rows intact.
  - `users`: 1 row intact.
  - `sitemap_sources`: 7 rows intact.
  - `rate_limits`: 12 rows (transient rate limiting hits generated during live auth test execution against the local server).
- **`.gitignore` Audit:**
  - Backups (`*.phase4_backup`, `*.backup`) and SQLite WAL files (`*.db-wal`, `*.db-shm`) are properly ignored.
  - The local development SQLite database (`task1-knowledge-brain/data/knowledge_brain.db`) is tracked in Git from prior commits and preserved.

---

### Task 11: Safe Test Execution Evidence

All tests executed cleanly with zero remote network connections:

1. **Turso Isolated Migration Tests:**
   - Command: `python -m pytest tests/test_turso_migration_isolated.py -v`
   - Result: `5 passed, 0 failed, 1 warning in 2.38s`
   - Exit Code: `0`

2. **Auth & Security Hardening Regression Suite:**
   - Command: `python -m pytest tests/test_auth_remediation.py tests/test_security_hardening.py -v`
   - Result: `30 passed, 0 failed, 8 warnings in 3.91s`
   - Exit Code: `0`

---

## 3. Prioritized Remediation List

Before authorizing live remote database writes, the following three fixes must be applied:

| Priority | Component | Issue | Remediation |
| :--- | :--- | :--- | :--- |
| **P1** | `scripts/migrate_to_turso.py` | Count mismatch does not halt execution (`>= cnt` check; logs mismatch but returns success). | Change check to strict equality (`dest_counts[table] == cnt`). If mismatch occurs, raise `RuntimeError(f"Row count mismatch on {table}...")` immediately. |
| **P1** | `scripts/migrate_to_turso.py` | `rate_limits` table has no primary key, causing row duplication on rerun. | Add `dest_client.execute('DELETE FROM "rate_limits"')` before migrating `rate_limits`, or define `PRIMARY KEY (key, timestamp)` in migration 005 DDL. |
| **P2** | `retrieval/vector_store.py` | In production (`VERCEL=1`), missing `TURSO_DATABASE_URL` silently falls back to ephemeral `/tmp` SQLite. | In `_get_connection()`, check `if is_prod and not self.turso_url: raise RuntimeError("Production requires TURSO_DATABASE_URL...")`. |

---

## 4. Conclusion & Stance

- **Remote Dry Run (`--dry-run`):** **READY FOR CONTROLLED REMOTE DRY RUN**. The dry run logic performs source inspection only and cannot alter or write to destination endpoints.
- **Remote Live Migration (`--confirm-remote`):** **NOT READY**. Live migration must remain blocked until the P1 remediations above are applied and validated in the isolated harness.
