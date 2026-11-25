# Error reference

Every error response is `application/problem+json` (RFC 9457) and includes `correlation_id`.
Quote it when reporting a problem; it appears in every API and worker log line.

| `code` | HTTP | Meaning |
|---|---|---|
| `validation_error` | 422 | Request parameters failed validation. See `errors`. |
| `empty_file` | 422 | The uploaded file has no content. |
| `file_too_large` | 413 | File exceeds `MAX_UPLOAD_MB`. |
| `unsupported_file_type` | 415 | Not a PDF, PNG or JPEG (checked from file content). |
| `too_many_pages` | 422 | PDF exceeds `MAX_PAGES`. |
| `unreadable_document` | 422 | Corrupt or encrypted PDF. |
| `document_not_found` | 404 | No document with that ID. |
| `idempotency_key_conflict` | 409 | `Idempotency-Key` already used with a different file. |
| `transient_error` | 503 | A dependency is temporarily unavailable. Retry with backoff. |
