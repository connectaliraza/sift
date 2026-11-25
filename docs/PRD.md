# Sift — Product Requirements Document (PRD)

| | |
|---|---|
| **Status** | Draft v0.2 |
| **Owner** | _Ali Raza_ |
| **Last updated** | 2026-11-25 |
| **Related** | [TRD](./TRD.md) · [ADRs](./adr/) |

---

## 1. Problem

Small and mid-sized businesses still re-type invoices into accounting systems by hand. This is slow (minutes per invoice), error-prone, and boring. Existing AI extraction services solve it but:

- cost money per page, which adds up quickly at volume;
- require sending sensitive financial documents to a third party, which many companies cannot do for compliance reasons;
- are black boxes: when they get a field wrong, there is no confidence signal and no built-in review step.

## 2. Solution

**Sift** is a self-hostable service that turns invoice files (PDF/PNG/JPG) into validated, structured JSON. It runs entirely on free, open-source components by default (local OCR + local LLM), flags uncertain results for human review, and notifies downstream systems through webhooks.

One command (`docker compose up`) gives a working system.

## 3. Target users

| User | Need |
|---|---|
| **Integrating developer** (primary) | A simple API: send a file, get reliable JSON back or a webhook when it's ready. |
| **Reviewer / bookkeeper** | A way to see and correct low-confidence extractions before they reach the books. |
| **Operator / self-hoster** | Easy to run, observe and debug on a single machine with no paid services. |

## 4. Goals and non-goals

### Goals (MVP)
1. Extract a fixed invoice schema from PDF and image files.
2. Process documents asynchronously and reliably (no lost or duplicated jobs).
3. Route low-confidence results to a human review step via the API.
4. Notify clients through signed webhooks with retries.
5. Run 100% on free/open-source tooling, with a clear path to paid providers via configuration only.
6. Prove quality with a reproducible evaluation set and published accuracy score.

### Non-goals (explicitly out of scope for MVP)
- Document types other than invoices.
- User-defined/custom schemas.
- A web UI (review happens through the API).
- Multi-tenancy, user accounts, billing.
- Kubernetes/Helm, cloud deployment.
- Handwriting recognition.
- Languages other than English.
- MCP server / agent integration (listed as a post-MVP stretch goal).

## 5. User stories

| ID | As a… | I want to… | So that… |
|---|---|---|---|
| US-1 | developer | upload an invoice and immediately get a job ID | my request doesn't block on slow processing |
| US-2 | developer | safely retry an upload with the same idempotency key | network retries never create duplicate jobs |
| US-3 | developer | poll a document's status and get the extracted JSON | I can integrate without webhooks if I prefer |
| US-4 | developer | receive a signed webhook when processing finishes | I can react to results without polling |
| US-5 | developer | see a confidence score and source evidence per field | I can decide how much to trust each value |
| US-6 | reviewer | list documents that need review | I know what to check |
| US-7 | reviewer | submit corrected data and approve a document | wrong values never reach downstream systems |
| US-8 | developer | retry a failed document | transient failures don't need a re-upload |
| US-9 | operator | start everything with one command and see worker activity | I can run and debug it without cloud accounts |
| US-10 | operator | switch the LLM/OCR provider through configuration | I can move to paid providers without code changes |

## 6. Functional requirements

| ID | Requirement | Priority |
|---|---|---|
| FR-1 | Accept PDF, PNG, JPEG uploads up to 10 MB and 10 pages. Reject others with a clear error. | Must |
| FR-2 | Support an `Idempotency-Key` header on upload. | Must |
| FR-3 | Store original files in S3-compatible object storage. | Must |
| FR-4 | Run OCR on each page, keeping page-level text and confidence. | Must |
| FR-5 | Extract the invoice schema (vendor, invoice number, dates, currency, subtotal, tax, total, line items) using an LLM with structured output. | Must |
| FR-6 | Validate results with business rules (e.g. line items sum to subtotal, subtotal + tax = total, valid dates). | Must |
| FR-7 | Compute a per-field and per-document confidence score. | Must |
| FR-8 | Mark a document `completed` or `needs_review` based on a configurable confidence threshold and validation result. | Must |
| FR-9 | Provide endpoints to get a document, list documents by status, review/approve, and retry. | Must |
| FR-10 | Deliver webhooks for terminal states, signed with HMAC-SHA256, retried with exponential backoff. | Must |
| FR-11 | Keep the history of every extraction (LLM and human) with model and prompt version. | Should |
| FR-12 | Provide an evaluation script that reports field-level accuracy on a labelled dataset. | Must |
| FR-13 | Protect the API with an API key. | Must |

## 7. Non-functional requirements

| Area | Requirement |
|---|---|
| **Reliability** | No job is lost if a worker crashes mid-task; every task is safe to run twice. |
| **Performance** | p95 end-to-end ≤ 90 s for a 2-page invoice on an 8 GB Apple Silicon (M2) laptop with a local 3B model. Upload response ≤ 300 ms. |
| **Portability** | Runs with `docker compose up` on Linux/macOS/Windows (WSL2) with 8 GB RAM (lean profile). No GPU required; Apple Silicon GPU used when Ollama runs natively. |
| **Cost** | $0 to run in default configuration. |
| **Observability** | Every log line is structured JSON with a correlation ID traceable from API request to the final task. |
| **Security** | Non-root containers, secrets only via environment variables, signed webhooks, no documents leave the host in default config. |
| **Maintainability** | Business logic independent of FastAPI/Celery; typed (mypy strict on core), linted, ≥ 80% test coverage on domain/services. |

## 8. Success metrics

| Metric | Target |
|---|---|
| Field-level accuracy on eval set (20+ invoices) | ≥ 85% with default local model |
| Documents auto-completed without review | ≥ 60% |
| Wrong values that pass as `completed` (false confidence) | ≤ 3% of fields |
| Time from `git clone` to first extracted invoice | ≤ 10 minutes (incl. model download) |
| Duplicate jobs from retried uploads | 0 |

## 9. Milestones

| Week | Milestone | Exit criteria |
|---|---|---|
| 1 | Foundation | Compose stack up; upload stores file + DB row; health/ready endpoints; CI runs lint + tests. |
| 2 | Pipeline | OCR → extract → validate chain runs end to end; status endpoint returns JSON; retries and time limits configured. |
| 3 | Reliability & review | Review + retry endpoints; outbox-based webhooks; correlation IDs; integration tests with real Postgres/Redis. |
| 4 | Proof & polish | Eval script in CI with published score; README, architecture diagram, demo GIF, 3 ADRs. **Feature freeze.** |

## 10. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Local LLM too slow on CPU | Poor demo experience | Default to a small model; document GPU and hosted-provider options; set clear expectations in README. |
| Local LLM accuracy too low | Weak eval score | Grounding check against OCR text, validation rules, and review routing; fallback model configurable. |
| LLM self-reported confidence is unreliable | False confidence | Confidence computed from objective signals (grounding, OCR quality, validation), not just the model's opinion. |
| Scope creep | Project never finishes | Non-goals list above; feature freeze at end of week 4. |
| Sample invoices with real personal data | Privacy issue in public repo | Use synthetic/generated or public-domain sample invoices only. |

## 11. Post-MVP ideas (not committed)
- MCP server so AI agents can submit documents and fetch results.
- Custom user-defined schemas.
- Minimal review UI (HTMX).
- Paid provider adapters (OpenAI/Anthropic, Textract) and model routing (cheap → strong on failure).
- Presigned direct-to-storage uploads.
- OpenTelemetry tracing + Grafana dashboards.

## 12. Open questions
1. Which exact local model gives the best accuracy/speed trade-off on CPU? → decide via eval in week 2.
2. Default confidence threshold for review? → start at 0.80, tune against eval set.
3. Tesseract or Docling as default OCR? → benchmark both on the eval set in week 2; record in an ADR.
