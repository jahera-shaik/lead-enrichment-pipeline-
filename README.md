# Alfaleus Lead Intelligence
### Lead Enrichment & Qualification Pipeline

A sales-intelligence tool that takes a raw lead (name / company / website), autonomously enriches it from public sources, scores it against a configurable Ideal Customer Profile using **semantic reasoning from a local LLM**, detects buying signals, generates two personalized outreach drafts, and syncs everything to a Notion CRM. Ships with a web dashboard and a Chrome extension.

> **Key constraint honored:** all ML inference runs **locally and CPU-bound** via `llama-cpp-python` — no external inference APIs (no Groq / OpenAI / Gemini).

---

## Table of Contents
- [Architecture](#architecture)
- [Features](#features)
- [Model Choice & Memory Footprint](#model-choice--memory-footprint)
- [ICP Scoring Formula](#icp-scoring-formula)
- [Scraping Approach & Known Failure Modes](#scraping-approach--known-failure-modes)
- [Deduplication](#deduplication)
- [Tech Stack](#tech-stack)
- [Setup & Installation](#setup--installation)
- [Running the App](#running-the-app)
- [Chrome Extension](#chrome-extension)
- [API Endpoints](#api-endpoints)
- [Project Structure](#project-structure)
- [Implementation Notes](#implementation-notes)

---

## Architecture

```
   CSV Upload        Web Dashboard        Chrome Extension
        \                  |                    /
         \                 |                   /
          -----------------+------------------
                           |
                    FastAPI Backend
        (hosts ONE local GGUF model instance, CPU-bound)
                           |
        +---------+--------+--------+-----------+
        |         |        |        |           |
     scraper  enrichment  icp    outreach     crm
    (website  (profile +  (sem.  (2 email   (Notion +
    + news +  confidence) fit +   variants)  dedup +
    LinkedIn)             signals)           status)
                           |
                           v
              SQLite (local state, dedup, status)
                           |
                           v
                Notion CRM (dedup, per-lead status)
```

The backend hosts a single local model instance shared by the dashboard and the Chrome extension, so the model is loaded into memory only once.

---

## Features

| Section | Status |
|---|---|
| Multi-source enrichment (website + Google News + LinkedIn best-effort) | Implemented |
| Per-field confidence levels (high / medium / low) | Implemented |
| Graceful degradation on source failure | Implemented |
| Semantic ICP scoring (LLM reasoning, not keyword match) | Implemented |
| Buying-signal detection with source + strength | Implemented |
| Configurable scoring weights & threshold (no code change) | Implemented |
| 2 personalized outreach drafts (direct + consultative) | Implemented |
| Notion CRM sync with deduplication + per-lead status | Implemented |
| Web dashboard (5 screens) | Implemented |
| Chrome extension (DOM extraction → backend) | Implemented |
| CSV upload with client-side preview | Implemented |

---

## Model Choice & Memory Footprint

- **Model:** Qwen2.5-0.5B-Instruct, quantized **Q4_K_M** (GGUF).
- **Runtime:** `llama-cpp-python` on CPU (`n_gpu_layers=0`), `n_ctx=2048`.
- **Disk:** ~470 MB. **Context window:** 2048 tokens (kept small to limit RAM).

**Why 0.5B:** It fits comfortably within free-tier memory limits and satisfies the CPU-bound requirement while keeping inference fast (~1-3s per call locally).

**Trade-offs & how they're mitigated.** A 0.5B model is weak at complex structured generation, so the pipeline is engineered around that:

- **Simplest-possible output, structured in Python.** For buying signals the model only returns a flat map like `{"1":"high","2":"none"}`; Python attaches the headline text. This avoids nested JSON that small models break on (headlines contain quotes/colons).
- **Never-fail JSON parser.** `generate_json()` strips code fences, extracts the first JSON block, repairs trailing commas, and falls back to `{"_parse_error": ...}` — it never raises, protecting every downstream call.
- **Retry on flaky scoring.** ICP scoring retries once if the first parse fails (squares the success rate).
- **Few-shot signal classification.** Examples in the prompt flip the model from misclassifying scandal/politics as buying signals to correctly favoring partnerships/funding/expansion.
- **Repetition guard.** `repeat_penalty=1.3` plus a Python de-duplication guard prevents degenerate "word word word…" loops in email openers.
- **Bounded generation for emails.** The model writes only the grounded opener; greeting, pitch, CTA, subject, and sign-off are templated in Python for reliability.

A larger model (e.g. Qwen2.5-1.5B) improves quality and is a one-line swap (`MODEL_PATH`), at higher memory cost.

---

## ICP Scoring Formula

Configured entirely in `config/settings.json` — **no code changes required.**

```
combined_score = (weight_icp_fit       * icp_fit_score)
               + (weight_buying_signals * buying_signal_score)
```

- **`icp_fit_score`** (0-100): the average of five criteria — industry, company size, tech indicators, contact seniority, geography — each scored by the LLM using **genuine semantic reasoning**. Examples it handles: "boutique consultancy with 40 engineers" satisfies "20-100 employees"; "Head of Platform Engineering" maps to VP-equivalent seniority. Missing data scores a neutral 50 rather than guessing.
- **`buying_signal_score`** (0-100): weighted sum of detected signals (high = 30, medium = 18, low = 8), capped at 100.
- **Disqualifiers** (excluded industries, competitor names) are checked **deterministically in Python**, not by the LLM. This is a hard business rule and keeps the small model from confusing "target" vs "exclude" industries.

**Defaults:** weights `0.7 / 0.3`, qualification threshold `50`. All editable in config.

---

## Scraping Approach & Known Failure Modes

- **Company website** — static fetch + BeautifulSoup. Extracts page title, meta description, visible text, tech-stack signatures (React, WordPress, Shopify, HubSpot, etc.), and up to 2 internal pages (about / pricing / careers).
  - *Failure mode:* JavaScript-rendered sites return little text. Handled by graceful degradation — title/meta are still captured and the pipeline continues.
- **Google News** — RSS feed (no API key) for recent company mentions, used as the buying-signal source.
- **LinkedIn** — **best-effort, via the Chrome extension only.** Server-side LinkedIn scraping is **not attempted** (auth wall, anti-scraping); it is marked `blocked / low confidence` and never aborts the pipeline.
  - *Failure mode:* LinkedIn's obfuscated, lazy-loaded DOM means name/company auto-fill in the extension may miss or grab the wrong company link. **All popup fields are editable**, so the user corrects before enriching — graceful degradation by design.
- Every enriched field carries a **confidence level** (high / medium / low) based on whether it was directly stated or inferred.
- All network calls have **hard timeouts** so a slow or dead source fails fast instead of hanging the pipeline.

---

## Deduplication

Enforced in **two independent layers**, both verified on repeated runs:

- **SQLite:** upsert keyed on `(company_domain, email)` — existing rows are updated, never duplicated.
- **Notion CRM:** queries for an existing record by domain/email before writing; updates in place and reports per-lead status: `synced` / `updated` / `pending` / `failed`.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend / API | FastAPI + Uvicorn |
| Local LLM | Qwen2.5-0.5B-Instruct (GGUF) via llama-cpp-python |
| Scraping | requests, BeautifulSoup4, feedparser |
| Storage | SQLite (stdlib `sqlite3`) |
| CRM | Notion API (`notion-client==2.2.1`) |
| Frontend | Vanilla HTML / CSS / JS (single file) |
| Extension | Chrome Manifest V3 |

---

## Setup & Installation

```bash
# 1. Create and activate a virtual environment (Python 3.11)
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS / Linux

# 2. Install dependencies
pip install -r requirements.txt
```

> **llama-cpp-python note:** if the pinned version fails to build, install the prebuilt CPU wheel:
> ```bash
> pip install llama-cpp-python==0.2.90 --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
> ```
> For older CPUs without AVX support, use the basic wheel index or the direct release wheel.

```bash
# 3. Download the model (~470 MB) into models/
python dl.py

# 4. Create a .env file in the project root:
#    NOTION_API_KEY=your_notion_integration_token
#    NOTION_DB_ID=your_notion_database_id
```

**Notion setup:** create an internal integration, build a database with columns
`Name, Company, Domain, Email, ICP Score, Combined Score, Buying Signals, Status, Email Draft 1, Email Draft 2`,
then connect the integration to the database (`•••` → Connections).

---

## Running the App

```bash
uvicorn backend.main:app --reload
```

Then open **http://127.0.0.1:8000/app** for the dashboard.
Interactive API docs are at **http://127.0.0.1:8000/docs**.

---

## Chrome Extension

1. Go to `chrome://extensions` and enable **Developer mode**.
2. Click **Load unpacked** and select the `extension/` folder.
3. With the backend running, open any company website or LinkedIn profile, click the
   extension icon, review the auto-filled fields, and click **Enrich Lead**.
4. Results (ICP score, buying signal, qualification) appear in the popup and the lead is
   saved to the dashboard.

---

## API Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/` | Health check |
| GET | `/app` | Serves the dashboard |
| POST | `/enrich` | Run the full pipeline on one lead |
| POST | `/upload-csv` | Enrich a CSV batch |
| GET | `/leads` | List all stored leads |
| GET | `/lead/{id}` | Full detail for one lead |
| POST | `/sync/{id}` | Push a lead to Notion (deduped) |
| GET | `/icp` | Return the current ICP config |

---

## Project Structure

```
lead-pipeline/
├── backend/
│   └── main.py            FastAPI app + endpoints + pipeline orchestration
├── services/
│   ├── llm.py             GGUF model singleton + never-fail JSON helpers
│   ├── scraper.py         website + Google News + LinkedIn (best-effort)
│   ├── enrichment.py      builds profile + confidence levels
│   ├── icp.py             semantic ICP scoring + buying signals
│   ├── outreach.py        2 grounded email variants
│   └── crm.py             Notion sync + dedup + status
├── database/
│   └── db.py              SQLite schema + upsert/dedup + queries
├── frontend/
│   └── index.html         dashboard (5 screens), served by FastAPI
├── extension/             Chrome extension (Manifest V3)
│   ├── manifest.json
│   ├── popup.html
│   ├── popup.js
│   └── content.js
├── config/
│   └── settings.json      ICP, scoring weights, product (editable, no code)
├── models/                GGUF model (gitignored)
├── dl.py                  model downloader
├── requirements.txt
└── README.md
```

---

## Implementation Notes

- **Local inference only.** No external LLM APIs are used anywhere — the constraint is honored end-to-end.
- **`notion-client` pinned to 2.2.1.** Version 3.x migrated to a data-source API incompatible with the classic database calls used here; 2.2.1 resolves database IDs correctly.
- **Python 3.11** is required — `llama-cpp-python` prebuilt wheels are most reliable there.
- **Secrets** live in `.env` (gitignored); the model and database files are gitignored as well.