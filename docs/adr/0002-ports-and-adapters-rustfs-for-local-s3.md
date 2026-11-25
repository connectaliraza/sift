# 0002: Ports-and-adapters; RustFS for local S3

- **Status:** Accepted
- **Date:** 2026-11-25

## Context
The project must run at **$0** today (local OCR, local LLM, self-hosted storage) and move to paid
services later (AWS S3, Textract, hosted LLMs) without rewrites.

The original plan used MinIO for local S3. MinIO stopped publishing community Docker images in
October 2025 and archived the community repository in 2026, so `docker pull minio/minio` no longer
works and the last images carry unpatched CVEs.

## Decision
1. Services depend only on **ports** (`typing.Protocol`s in `sift.ports`): `ObjectStorage`,
   `DocumentRepository`, `DocumentInspector`, `TaskQueue` (OCR and LLM ports arrive in week 2).
   **Adapters** implement them. Only the composition roots (`api/deps.py`, `main.py`, `workers/`)
   choose adapters. `import-linter` enforces this in CI.
2. Local object storage is **RustFS** (Apache-2.0, S3-compatible). The app talks to it through
   `boto3` with a configurable endpoint, so production uses AWS S3 by unsetting `S3_ENDPOINT_URL`.
   Bucket creation is done by our own `storage-init` job, not a vendor CLI.

## Alternatives considered
- **Garage:** solid and lightweight, but needs a layout/config step before first use. More setup friction.
- **SeaweedFS:** mature, but heavier to configure for a single-node dev setup.
- **Community MinIO mirrors:** unofficial builds of archived software; a supply-chain risk.
- **No abstraction, call boto3 from services:** fewer files, but ties business logic to one vendor
  and makes unit tests need a fake S3.

## Consequences
- Unit tests use in-memory fakes; the test suite runs in about 2 seconds.
- Integration tests use moto's S3 server, so CI needs no storage container at all.
- The MinIO withdrawal required changing **zero lines of application code**, a concrete payoff of
  this decision.
- RustFS is younger than MinIO. Acceptable for local dev; production targets AWS S3.
