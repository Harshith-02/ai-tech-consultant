# IMPLEMENTATION PLAN — AI TECH CONSULTANT UPGRADE & SECURITY HARDENING
**Author:** AI Tech Consultant Core Team  
**Status:** In Progress / Active Implementation  
**Version:** 2.1.0  
**Target Environments:** Local Multi-Service Development (`localhost:5000` / `:8000`, `:3001`, `:8002`) & Vercel Serverless Production ([https://ai-tech-consultant-mu.vercel.app/](https://ai-tech-consultant-mu.vercel.app/))

---

## 1. Executive Summary & Existing Architecture

The **AI Tech Consultant** is a unified multi-agent web platform designed to streamline technology consulting for directory and marketplace platforms (specifically Brilliant Directories):
* **Task 1: Knowledge Brain (`:8000`)**: Python FastAPI service providing hybrid FTS5 keyword + dense semantic vector search over help documentation and UI screenshots, with strict grounding and hallucination abstention.
* **Task 2: Inbox Agent (`:3001` & `/api/inbox`)**: Email triage and response agent with intent classification, grounding against Task 1 Brain, safety guardrails, and autonomy streak policies.
* **Task 3: Meeting to Scope (`:8002` & `/api/scope`)**: Multi-agent transcript analysis system (Analyst, Feasibility, Scope, and Estimation Agents) with scope diff engine and governance approval controls.
* **Unified Gateway (`api/index.py`)**: Central FastAPI application orchestrating all services under `/api/kb`, `/api/inbox`, and `/api/scope`, supporting both local execution and Vercel serverless deployment.
* **Frontend (`public/` and `dashboard/public/`)**: Modern, high-performance vanilla JS/CSS glassmorphic dashboard with authentic Gmail 3-pane layout, interactive RAG parameter sliders, multimodal vision inspection, and proposal approval flows.

### Baseline Audit & Test Verification Results
* **Task 1 Knowledge Brain Evaluation**: 22/22 Test Cases Passed (100.0%) | 54.15ms Median Latency.
* **Task 2 Inbox Agent Evaluation**: 50/50 Emails Classified (100.0%) | 0 Safety Violations | 0.02ms Latency.
* **Task 3 Meeting to Scope Evaluation**: 22/22 Test Cases Passed (100.0%) | Net Delta & Scope Diff Engine Verified.
* **Pytest Baseline**: 8/8 Passed (100.0%).

---

## 2. Confirmed Implementation Gaps (from Audit)

1. **Security & Cryptography**:
   * Fallback to static plaintext passphrase `"ai-tech-consultant-oauth-secret-key-2026"` in `GMAIL_ENCRYPTION_KEY`.
   * Custom HMAC-SHA256 keystream XOR cipher instead of standard authenticated encryption (`AES-256-GCM`).
   * Potential SSRF on HTTP 301/302 redirects in `crawler.py` (destination not re-checked against private/loopback/cloud-metadata blocks).
   * Missing authentication & authorization middleware on protected `/api/kb/*` and `/api/inbox/*` management endpoints.
2. **Persistence & Autonomy Engine**:
   * Volatile in-memory dictionaries in `api/index.py` (`AUTONOMY_CONFIG`, `AUTONOMY_DATA`, `FEEDBACK_RULES`, `STARRED_EMAIL_IDS`, `TRASH_EMAIL_IDS`) that vanish on process restarts or serverless execution.
   * Autonomy streak prematurely incremented before `client.post(".../messages/send")` and not rolled back on Gmail API failure.
   * Autonomy streak not reset when drafts are edited during review.
   * `billing` category was not permanently guarded against autonomous sending.
3. **Category Taxonomy**:
   * Prompt requires 9 user-configurable topic labels: `Filters`, `Home Page`, `Domain Management`, `Header`, `Main Menu`, `Footer`, `General Settings`, `Design Settings`, `Managers`.
   * Existing implementation collapsed Header/Menu/Footer into `header_footer` and omitted `Managers`.
4. **Sitemap Throughput & Scheduling**:
   * Static throughput constants (`50 pages / 5 min`, `0.5s per article`) rather than rolling measured download + chunk + embed latencies.
   * Absence of an active background loop or scheduled cron triggering refreshes for `next_check_at`.
   * Missing UI indicators for Spam folder and duplicate URL source cross-references.

---

## 3. Phased Implementation Roadmap

### Phase 1 — Security Hardening
* **AES-256-GCM Cryptographic Engine**:
  * Replace custom cipher with `cryptography.hazmat.primitives.ciphers.aead.AESGCM` (using 256-bit derived key from `GMAIL_ENCRYPTION_KEY`, versioned format `v1:<base64(nonce+ciphertext+tag)>`, safe rejection and backward-compatibility decryption helper).
  * Require valid encryption key in production; fail safely without silent fallback.
* **SSRF Redirect Interceptor**:
  * Implement `safe_fetch_url()` in `crawler.py` with manual redirect loop following up to 5 hops, re-validating every redirect target against `is_safe_external_url()` before connecting.
  * Re-validate schemes, ports, and private/loopback/cloud-metadata IPs.
* **Authentication & Authorization**:
  * Implement authentication middleware on `/api/kb/*` (except `/health`) and `/api/inbox/*` (except `/health`).
  * Support session/API token authentication (`Authorization: Bearer <token>` or `X-API-Key`).
  * Return HTTP 401 Unauthorized for missing/invalid credentials and HTTP 403 Forbidden for unauthorized actions.
* **Security Test Suite**:
  * Add unit tests in `tests/test_security_hardening.py` verifying key validation, AES-256-GCM tampering detection, redirect SSRF blocking, and authentication enforcement.

### Phase 2 — Durable Email State & Autonomy Correctness
* **SQLite Persistence for Autonomy & Feedback**:
  * Migrate `AUTONOMY_DATA`, `AUTONOMY_CONFIG`, `FEEDBACK_RULES`, `STARRED_EMAIL_IDS`, `TRASH_EMAIL_IDS`, and `SPAM_EMAIL_IDS` into SQLite tables in `vector_store.py`:
    * `autonomy_settings`
    * `feedback_rules`
    * `email_folder_state`
    * `autonomy_global_config`
* **Atomic Autonomy Streak Machine**:
  * Only increment consecutive approval streak *after* Gmail API send is successfully confirmed.
  * Roll back or do not increment on send exception.
  * Reset streak to 0 upon human draft edit.
  * Permanently guard `billing` (`is_guarded = 1`).

### Phase 3 — Reliable Sitemap Scheduler
* **Active Refresh Scheduling**:
  * Background worker / timer polling `sitemap_sources` where `next_check_at <= now()`.
  * Compute and update `next_check_at` based on `refresh_interval_days` (1, 7, 15, or 30 days).
  * Handle worker concurrency locks and safe retries without incrementing missing URL counters on incomplete/failed runs.

### Phase 4 — Dynamic Ingestion Metrics
* **Measured Pipeline Throughput**:
  * Track actual rolling latencies for HTTP page fetch, text extraction, chunking, and embedding generation.
  * Compute dynamic `pages_per_5_min`, `pages_per_hour`, and estimated completion timestamp (`expected_completion_datetime`).
  * Return provisional estimate with uncertainty bounds when historical sample size is small.

### Phase 5 — Sitemap Lifecycle Completeness
* **HTTP 301 & 404 Lifecycle Handling**:
  * Record 301 canonical URL targets and redirect history.
  * Record 404 status codes and apply configurable retention thresholds (1, 2, 15, or 30 checks).
  * Ensure shared URLs referenced in another enabled sitemap source are never deleted while needed.
  * Dedicated archive search and content restoration validation.

### Phase 6 — Email UI & Classification Completeness
* **9 Configurable Categories Alignment**:
  * Split `header_footer` into `Header`, `Main Menu`, and `Footer`.
  * Add `Managers` category.
  * Support `Spam` folder in backend and frontend.
  * Update UI in `public/index.html`, `public/app.js`, and sync to `dashboard/public/`.

### Phase 7 — Feedback & Safe Self-Improvement
* **Controlled Supervisor Feedback**:
  * Record structured diffs between AI draft and sent email into SQLite `feedback_rules`.
  * Retrieve relevant category rules during draft generation.
  * Separate AI confidence score (0.00 - 1.00) from approval streak counter ($N / X$).
  * Enforce safety blockades for high-risk categories (`refund_cancellation`, `complaint`, `project_request`, `quote_request`, `billing`).

### Phase 8 — Full Regression & Acceptance Testing
* **Test Suite Verification**:
  * Execute all pytest suites, Task 1 evals, Task 2 evals, Task 3 evals.
  * Update `IMPLEMENTATION_AUDIT.md` with verified evidence and updated statuses.

---

## 4. Database Schema Changes & Migrations

```sql
-- Autonomy Settings Table
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

-- Feedback Rules Table
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

-- Email Folder & Flag State
CREATE TABLE IF NOT EXISTS email_folder_state (
    email_id TEXT PRIMARY KEY,
    folder TEXT DEFAULT 'inbox',
    is_starred INTEGER DEFAULT 0,
    is_read INTEGER DEFAULT 1,
    setting_label TEXT,
    raw_json TEXT,
    updated_at TEXT NOT NULL
);

-- Global Autonomy Configuration
CREATE TABLE IF NOT EXISTS autonomy_global_config (
    key TEXT PRIMARY KEY,
    value TEXT
);
```

---

## 5. Security Architecture
* **Encryption**: AES-256-GCM authenticated cipher with 96-bit unique nonces and 128-bit authentication tags.
* **SSRF Prevention**: Scheme validation (`http`, `https`), DNS resolution, IP range check (filtering private, loopback, link-local, multicast, metadata ranges), and strict redirect re-validation per hop.
* **Authentication**: Token-based authentication verifying incoming `Authorization: Bearer <token>` or `X-API-Key` headers on all sensitive administrative and data endpoints.
