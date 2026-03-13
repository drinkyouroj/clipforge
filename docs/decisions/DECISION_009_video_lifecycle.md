# DECISION 009: Video Lifecycle & Cleanup

## ARCHITECT proposes:
- Enhanced user-initiated delete: immediate S3 cleanup (source + all export S3 objects), soft-delete DB records, cancel in-progress ARQ jobs via `Job.abort()`
- DB records retained 7 days after soft-delete for potential undo
- Daily ARQ cron task (`cleanup_expired_content`) with two responsibilities:
  1. Hard-delete DB rows for videos with `deleted_at` > 7 days (cascade: transcript, clips, exports, jobs). Safety-net S3 delete for any remaining objects.
  2. Auto-expire videos with `created_at` > 30 days and `deleted_at IS NULL`: run same S3 cleanup flow, set status=deleted, set deleted_at=now.
- Also resets `period_exports_used` for users where `current_period_end < now()` (free-tier reset + webhook miss safety net)
- No S3 lifecycle policy — application-level cleanup for full visibility

## ADVERSARY attacks:
1. **Cleanup task fails midway:** If the cron crashes after deleting S3 objects for 25 of 50 expired videos but before marking them as deleted in DB, those 25 videos have no S3 data but DB still shows them as active. User tries to view/export and gets S3 404 errors.
2. **Concurrent render + auto-expire race:** A render job downloads a video from S3 at T=0. At T=1, the cleanup cron deletes that video's S3 object (30 days old). The render job continues with the local copy and succeeds, uploading a rendered clip. But the video is now soft-deleted — the rendered export is orphaned and will be cleaned up in 7 days. The user gets a confusing experience: export appears to succeed but the source video is gone.
3. **ARQ job abort timing:** `Job.abort()` is best-effort. If a worker has already dequeued the job and started processing, abort won't stop it. The worker checks job status at the start, but there's a window between dequeue and status check where the delete and the job run concurrently.
4. **Hard-delete cascade failures:** If `DELETE FROM videos WHERE id = X` cascades through 4 tables with foreign keys, a single constraint violation (e.g., an export FK to a job that was already deleted) could fail the entire batch. The cron processes multiple videos — does one failure stop the whole run?

## JUDGE decides:
Green light with mitigations:
1. **Midway crash:** Process videos one at a time in a transaction. For each video: begin txn → delete S3 → update DB → commit. If S3 delete succeeds but DB update fails, the next cron run will retry (S3 delete of a non-existent object is a no-op). If DB update succeeds but S3 delete fails, the safety-net S3 delete on hard-delete catches it. Acceptable.
2. **Render + expire race:** The 30-day window makes this extremely unlikely for legitimate use. Add a guard: skip auto-expire for videos that have any job with `status = 'running'`. If a render is in progress, wait until next cron cycle.
3. **ARQ abort timing:** Acceptable. The render pipeline checks export/job status at each stage transition (prepare → execute → upload). If the video was deleted mid-render, the next stage will find the export status is `failed` and bail. Add a status check at the start of each pipeline stage.
4. **Cascade failures:** Use per-video transactions. Delete in dependency order: exports → clips → transcript → jobs → video. If one video fails, log the error and continue to the next. Never let one failure stop the entire batch.

## Implementation notes:
- Process one video per transaction in cleanup task
- Skip auto-expire for videos with running jobs
- Delete in dependency order: exports → clips → transcript → jobs → video
- Each render pipeline stage should check if export is still valid before proceeding
- S3 delete failures are logged but don't block DB cleanup
