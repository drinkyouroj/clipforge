# DECISION 003: File Storage Design

## ARCHITECT proposes:

### Storage Backend: Cloudflare R2 (S3-compatible)
R2 eliminates egress fees — critical for a video app where users download rendered clips.
AWS S3 egress at $0.09/GB would make per-export costs unpredictable.
R2 is S3-compatible, so we use boto3 with a custom endpoint.

### Local Development: MinIO
For local dev and testing, use MinIO as an S3-compatible local store.
Tests mock the S3 client to avoid requiring MinIO to be running for unit tests.
Integration tests can optionally use MinIO.

### Upload Path Structure
```
uploads/{user_id}/{uuid}.{ext}     — original uploads
rendered/{user_id}/{clip_id}/{platform}.mp4  — rendered clips
```
User-scoped paths prevent cross-user access even if bucket policies are misconfigured.

### Signed URLs
- Download links: 1 hour expiry (user downloads rendered clip)
- Preview links: 15 minutes expiry (in-browser video preview)
- Never expose raw bucket URLs or S3 keys to the frontend

### Lifecycle & Cleanup
- Auto-delete uploaded videos 30 days after upload (S3 lifecycle policy on `uploads/` prefix)
- Rendered clips: 30 days after creation
- On user-initiated delete: immediately remove S3 object, update DB `deleted_at`
- On account deletion: queue background job to delete all S3 objects for user

### Partial Upload Handling
- Upload flow: receive multipart → save to temp file → validate → upload to S3
- `tempfile.NamedTemporaryFile` with `delete=False`, cleanup in `finally` block
- If upload is interrupted: temp file is cleaned up, no S3 object created, no DB record
- If S3 upload fails after validation: temp file cleaned up, no DB record
- DB record is only created after successful S3 upload

## ADVERSARY attacks:

### Attack 1: Temp file accumulation on crash
If the FastAPI worker process crashes mid-upload (OOM, SIGKILL), the temp file cleanup
in the `finally` block never runs. Over time, the `/tmp` directory fills up.

**Failure scenario:** Worker handles 10 concurrent 500MB uploads. System runs low on memory.
OOM killer terminates the worker. 5GB of temp files are orphaned in `/tmp`. The next worker
starts, `/tmp` is nearly full, and new uploads fail.

### Attack 2: S3 object created but DB insert fails
If the S3 upload succeeds but the DB insert fails (connection timeout, constraint violation),
the S3 object exists without a corresponding DB record. It's never cleaned up, accumulating
storage costs.

**Failure scenario:** Network blip causes DB connection to drop during `commit()`. S3 now has
the file, but the videos table has no row. The user sees "upload failed" and retries. After
a year, orphaned S3 objects cost $50/month.

## JUDGE decides:

**Verdict: Approved with required modifications.**

1. **Temp file cleanup:** Add a periodic cleanup cron that deletes temp files older than
   1 hour from the upload temp directory. Use a dedicated temp directory (`/tmp/clipforge/`)
   instead of system `/tmp`. **Accepted tradeoff:** crash-orphaned files persist up to 1 hour.

2. **S3-DB consistency:** Wrap S3 upload + DB insert in a try/except. If DB insert fails,
   immediately delete the S3 object. Log the orphan attempt for monitoring. This is not
   transactional, so there's a small window where the object exists without a row, but the
   cleanup is immediate. **Accepted tradeoff:** brief inconsistency window on DB failure.

## Implementation notes:
- Use boto3 with custom endpoint for R2
- Mock S3 client in unit tests, no MinIO required
- User-scoped paths: `uploads/{user_id}/{uuid}.{ext}`
- Signed URLs: 1 hour download, 15 minutes preview
- Temp files in `/tmp/clipforge/` with `finally` cleanup
- On DB failure after S3 upload: delete S3 object immediately
- S3 lifecycle: 30 days on `uploads/` and `rendered/` prefixes
