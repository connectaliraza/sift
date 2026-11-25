# 0001: Celery + Redis for background work

- **Status:** Accepted
- **Date:** 2026-11-25

## Context
Processing an invoice takes 10–90 s (OCR + local LLM). It cannot run inside the HTTP request.
We need retries with backoff, per-task time limits, separate worker pools for CPU-bound OCR and
I/O-bound LLM calls, and safe re-delivery if a worker dies mid-task.

## Decision
Use **Celery 5** with **Redis** as the broker. Postgres, not the Celery result backend, holds job state.

Key settings (TRD §8.2): `acks_late`, `reject_on_worker_lost`, `prefetch_multiplier=1`, a Redis
`visibility_timeout` longer than the longest task, JSON-only serialization, routing to `ocr` / `llm` /
`default` queues.

## Alternatives considered
- **FastAPI `BackgroundTasks`:** runs in the API process; work is lost on restart; no retries or routing.
- **Arq / Dramatiq / Taskiq:** lighter and more async-friendly, but smaller ecosystems; Celery's
  routing, canvas (chains/chords), beat scheduler and Flower cover every need here.
- **RabbitMQ broker:** stronger delivery guarantees, but one more service on an 8 GB laptop. Redis is
  already needed and is acceptable with AOF + `noeviction`, given Postgres is the source of truth.

## Consequences
- Tasks **must be idempotent**: with `acks_late`, a task can run twice. State changes use
  compare-and-set updates; writes are upserts.
- Celery workers are synchronous, so workers use a sync SQLAlchemy engine while the API uses async.
  Models are shared.
- If Redis loses messages, a periodic sweeper (week 3) re-enqueues stuck documents from Postgres.
