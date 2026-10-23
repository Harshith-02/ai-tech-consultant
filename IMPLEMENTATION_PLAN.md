# IMPLEMENTATION PLAN — AI TECH CONSULTANT UPGRADE
**Author:** AI Tech Consultant Core Team  
**Status:** In Progress / Active Implementation  
**Version:** 2.0.0  
**Target Environments:** Local Multi-Service Development & Vercel Serverless Production ([https://ai-tech-consultant-mu.vercel.app/](https://ai-tech-consultant-mu.vercel.app/))

---

## 1. Executive Summary & Existing Architecture

The **AI Tech Consultant** is a unified multi-agent web platform designed to streamline technology consulting for directory and marketplace platforms (specifically Brilliant Directories):
* **Task 1: Knowledge Brain (`:8000`)**: Python FastAPI service providing hybrid FTS5 keyword + dense semantic vector search over help documentation and UI screenshots, with strict grounding and hallucination abstention.
* **Task 2: Inbox Agent (`:3001` & `/api/inbox`)**: Email triage and response agent with intent classification, grounding against Task 1 Brain, safety guardrails, and autonomy streak policies.
* **Task 3: Meeting to Scope (`:8002` & `/api/scope`)**: Multi-agent transcript analysis system (Analyst, Feasibility, Scope, and Estimation Agents) with scope diff engine and governance approval controls.
* **Unified Gateway (`api/index.py`)**: Central FastAPI application orchestrating all services under `/api/kb`, `/api/inbox`, and `/api/scope`, supporting both local execution and Vercel serverless deployment.
* **Frontend (`public/` and `dashboard/public/`)**: Modern, high-performance vanilla JS/CSS glassmorphic dashboard with authentic Gmail 3-pane layout, interactive RAG parameter sliders, multimodal vision inspection, and proposal approval flows.

### Baseline Audit & Test Results
* **Task 1 Knowledge Brain Evaluation**: 22/22 Test Cases Passed (100.0%) | 58.9ms Median Latency.
* **Task 2 Inbox Agent Evaluation**: 50/50 Emails Classified (100.0%) | 0 Safety Violations | 0.03ms Latency.
* **Task 3 Meeting to Scope Evaluation**: 22/22 Test Cases Passed (100.0%) | Net Delta & Scope Diff Engine Verified.
* **Pytest Baseline**: 4/4 Passed (100.0%).

---

## 2. Existing Functionality to Preserve

1. **Task 1 Hybrid Search & Multimodal Retrieval**: FTS5 full-text + dense cosine vector similarity, multimodal screenshot query analysis, and escalation ticket center.
2. **Task 2 Safety Guardrails & Business Intent Risk**: Classification into technical categories and business intents (`refund_cancellation`, `complaint`, `project_request`, `quote_request`), keeping high-risk categories permanently locked from autonomous sending.
3. **Task 3 Meeting-to-Scope Orchestration**: Multi-agent pipeline processing Meetings A, B, and C with 3-point hour estimates, milestone costings, and SOW diff reports.
4. **Unified API Gateway & Frontend Parity**: All endpoints exposed via `api/index.py` and synchronized between `public/` and `dashboard/public/`.

---

## 3. Upgrade A: Advanced Sitemap Discovery, Ingestion & Incremental Refresh

### 3.1 Multiple Sitemap Sources & Schema
* Support multiple independent sitemap sources (e.g. documentation, blog, help center, developer docs).
* Database tables:
  * `sitemap_sources`: Stores root sitemap URL, name, refresh schedule, missing URL threshold, status, and metrics.
  * `sitemap_urls`: Stores URL, source relation, `lastmod`, ETag, content hash, consecutive missing checks count, and status (`active`, `pending`, `archived`).
  * `sitemap_refresh_runs`: Audit trail of discovery and refresh runs (started, completed, discovered, new, changed, missing, archived, errors).
  * `url_archive` / `archived_articles`: Historical archive preserving removed URLs, removal reason, missing checks count, and content hash (Table #2).

### 3.2 Recursive Sitemap Discovery & SSRF Protection
* Traverses `<sitemapindex>` and child `<sitemap>` documents recursively up to 3 levels deep.
* **SSRF Defense**: Validates every URL and redirect destination against private IP blocks (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `127.0.0.0/8`, `localhost`, link-local `169.254.0.0/16`).
* Handles `.xml` and `.xml.gz` sitemaps, duplicate URLs, cycle loops, and malformed XML.

### 3.3 Discovery Preview & Manual Confirmation
* UI Card shows:
  * Total sub-sitemaps found & total page URLs found.
  * First URL & Last URL.
  * Sample URL list with links.
  * Measured ingestion throughput and ETA.
  * Confirmation required before full crawl commences.

### 3.4 Measured Ingestion Throughput & Realistic ETA
* Instead of hardcoded arbitrary numbers, throughput is derived from rolling execution measurements:
  * `pages_per_5_min` (default baseline: 50 pages)
  * `pages_per_hour` (default baseline: 600 pages)
  * `pages_per_24_hours` (default baseline: 14,400 pages)
* Formats ETA dynamically: `X hours Y mins (±1 day)` or `Z days (±1 day)`.

### 3.5 Incremental 3-Case Change Detection & 15-Check Policy
* **Case 1 (New URL)**: Discovered URL not in database $\to$ added and queued for ingestion.
* **Case 2 (Changed URL)**: `lastmod` updated or content hash changed $\to$ page re-fetched and chunks/embeddings refreshed atomically.
* **Case 3 (Missing URL)**:
  * Incomplete / failed crawls never trigger deletion.
  * When a full successful refresh is completed and a registered URL is absent, increment `consecutive_missing_checks`.
  * URL remains active until reaching the configured threshold (default: **15 consecutive successful checks**).
  * Upon reaching threshold, URL is deactivated from Knowledge Base #1 and archived into **Table #2 (`archived_articles`)** for historical compliance.
  * Shared URLs active in another sitemap source remain active in knowledge retrieval.

---

## 4. Upgrade B: Real Gmail Integration & Intelligent Email Assistant

### 4.1 Gmail OAuth 2.0 & Token Security
* Integrates Google OAuth 2.0 flow:
  * `GET /api/inbox/oauth/authorize`: Generates state and returns Google consent URL.
  * `GET /api/inbox/oauth/callback`: Exchanges authorization code for access and refresh tokens.
  * `GET /api/inbox/oauth/status`: Returns connected email, status, and last sync timestamp without exposing tokens.
  * `POST /api/inbox/oauth/disconnect`: Revokes and wipes tokens.
* Scopes: Minimum required scopes (`gmail.readonly`, `gmail.compose`, `gmail.modify`, `gmail.send`).
* Encrypted token storage: Refresh tokens and access tokens encrypted using Fernet (symmetric AES-128-CBC) with `GMAIL_ENCRYPTION_KEY`.

### 4.2 Inbox Synchronization & Familiar UI
* **Synchronization**: Uses Gmail Messages API (`users.messages.list`) and History API (`users.history.list`) with pagination and persistent cursor.
* **Familiar Gmail UI**:
  * Top-right profile avatar (`Harshith - Solutions Architect`) opening Account & Autonomy Settings.
  * Left sidebar: ➕ **Compose**, **Inbox**, **Starred**, **Drafts**, **Sent**, **Trash**, plus **8 Setting Labels**.
  * Center pane: Selection checkbox, star toggle, sender, subject/body snippet, date.
  * Right pane: Original email, classification badges, streak meter, grounded draft response, action buttons.

### 4.3 Eight Setting Classification Labels & Real Drafts in Gmail
* **Setting Labels**:
  1. `filters` (Search & Filters)
  2. `home_page` (Home Page & Hero)
  3. `domain_management` (Domain & DNS)
  4. `header_footer` (Header & Footer)
  5. `billing` (Billing & Plans)
  6. `staging` (Staging & Dev)
  7. `general_settings` (General Settings)
  8. `design_settings` (Design & CSS)
* **Real Gmail Draft Creation**: When an email arrives, after Knowledge Brain grounding, the assistant creates a genuine Gmail draft via `users.drafts.create` with appropriate RFC 2822 headers (`In-Reply-To`, `References`, `Subject`, `To`).

### 4.4 Configurable Per-Category Autonomy ($X$) & Learning Engine
* Configurable threshold $X$ (default: `3` unedited sends).
* **Unedited Approval**: If approved and sent without modification, streak increments by 1. When streak reaches $X$, `isEligibleForAutonomy` becomes `True`.
* **Autonomous Sending**: Next email in that category is automatically sent via `users.drafts.send`, recorded in **Sent**, and tagged with `⚡ Autonomous Auto-Sent`.
* **Human Edit & AI Learning Engine**:
  * If edited before sending, the exact diff is extracted and saved to `FEEDBACK_RULES[category]`.
  * Streak resets to `0/X`.
  * The very next draft in that category immediately incorporates the learned supervisor rule.
* **Permanent Restrictions**: High-risk categories (`refund_cancellation`, `complaint`, `project_request`, `quote_request`) are permanently restricted from autonomous sending regardless of streak.
* **Emergency Stop**: Global master toggle (`auto_send_enabled`) instantly halts all autonomous dispatches.

---

## 5. Implementation Milestones

| Milestone | Deliverables | Status |
| :--- | :--- | :--- |
| **M1: Baseline Audit & Foundations** | Code inspection, evaluation baseline, `IMPLEMENTATION_PLAN.md` | **COMPLETED** |
| **M2: Advanced Sitemap Discovery** | Recursive `<sitemapindex>` parsing, SSRF defense, discovery preview | **COMPLETED** |
| **M3: Measured Throughput & ETA** | Rolling throughput calculation (5m, 1h, 24h), dynamic ETA formatting | **COMPLETED** |
| **M4: Incremental Refresh & Archival** | 3-case change detection, 15-check missing URL threshold, Table #2 archival | **COMPLETED** |
| **M5: Gmail OAuth & Real Sync Engine** | OAuth flow, encrypted token store, real Gmail draft creation, sync cursor | **COMPLETED** |
| **M6: Gmail Familiar UI & Classification** | 3-pane Gmail layout, 8 setting labels, top-right profile avatar | **COMPLETED** |
| **M7: Autonomy Threshold & Feedback Store** | Configurable $X$, draft vs sent diff learning, streak reset, safety locks | **COMPLETED** |
| **M8: End-to-End Validation & Acceptance** | Automated test suite, live test personas, Google Cloud setup docs | **COMPLETED** |
| **M9: Persistent Historical Archive** | Full content preservation, Knowledge Base Archive UI, restore, version history, cross-source safety, explicit purge | **COMPLETED** |

---

## 6. Testing Strategy

* **Unit & Integration Tests**:
  * `tests/test_crawler_change_detection.py`: Verifies Case 1 (new), Case 2 (updated lastmod), Case 3 (missing 15 checks $\to$ Table #2 archival).
  * `tests/test_sitemap_and_gmail_engine.py`: 
    * Test 1: Sitemap inspection & rolling ETA calculation.
    * Test 2: Interactive chat AI reasoning engine & prompt engineering.
    * Test 3: Authentic Gmail engine, 8 setting labels, autonomy streak unlock at $X=3$, streak reset on edit, and feedback rule injection.
    * Test 4: Multi-source sitemap management and scheduling.
    * Test 5: OAuth token encryption, HMAC authentication, and sync endpoints.
    * Test 6: Email audit logging.
    * Test 7: Persistent historical sitemap archive, full content preservation, exclusion from ordinary retrieval, dedicated historical search, cross-source protection, restoration, and authorized permanent deletion.
* **Evaluation Benchmarks**:
  * Task 1: 22 cases (`run_evals.py` $\to$ 100% pass rate).
  * Task 2: 50 emails (`run-evals.js` $\to$ 100% pass rate).
  * Task 3: 22 cases (`run_evals.py` $\to$ 100% pass rate).
* **Live Acceptance Testing**:
  * Knowledge Base $\to$ 🏛️ Historical Archive modal with live search, inspection preview, restoration, and permanent delete.
  * Quick-fill personas for Fiona, Alex, David, Elena.
  * Real Gmail OAuth connection with live incoming message verification.
