# DECISION 006: Clip Selection Data Model

## ARCHITECT proposes:

### Clip Status Flow
Clips follow this status progression (already defined in DECISION_001 CHECK constraint):
```
candidate → selected → rendering → rendered → failed
```

- **candidate**: AI-generated clip suggestion from detect_clips job
- **selected**: User has chosen this clip for rendering (via PATCH /clips/{id})
- **rendering**: Render job is in progress
- **rendered**: Output file exists on S3, ready for download/export
- **failed**: Render failed (user can retry)

### Selection Rules
- Users can select multiple clips from the same video
- No limit on selections in MVP (render rate limit handles abuse: 10/day free tier)
- Users can adjust clip boundaries (start_time, end_time) before selecting
- Adjusted clips retain their original virality_score and metadata
- Users can deselect by setting status back to "candidate"

### Frontend Flow
1. User views clip candidates sorted by virality score
2. User optionally adjusts boundaries with range sliders
3. User clicks "Select for Export" → status changes to "selected"
4. Selected clips appear in an export queue
5. User triggers render (Week 3 scope)

### API
- `PATCH /clips/{id}` with `{"status": "selected"}` — mark for export
- `PATCH /clips/{id}` with `{"status": "candidate"}` — deselect
- `GET /clips/video/{video_id}?status=selected` — get only selected clips (filter param)
- Boundary adjustments use same PATCH endpoint with `start_time` / `end_time`

### No Separate "Selection" Table
The clip status field handles selection state. No need for a join table or separate selection model — it would add complexity without benefit for MVP where each clip belongs to exactly one video and one user.

## ADVERSARY attacks:

1. **No audit trail for boundary changes.** When a user adjusts start_time/end_time, the original AI-suggested boundaries are overwritten. If the user messes up and wants to revert, the original values are lost. This is a data loss scenario that will generate support tickets.

2. **Status transitions are unconstrained.** The PATCH endpoint accepts any status string. A user (or buggy frontend) could set status to "rendered" or "rendering" directly, bypassing the actual render pipeline. This breaks the invariant that "rendered" means an output file exists.

## JUDGE decides:

**Green light with one required change:**

1. **Original boundaries — accept the loss for MVP.** Adding an `original_start_time` / `original_end_time` column pair is clean but increases schema complexity for a low-frequency scenario. For MVP, the user can re-run clip detection to get fresh candidates. Document as a known limitation. Revisit post-launch if support tickets materialize.

2. **Constrain status transitions in the API.** The PATCH endpoint must validate transitions:
   - `candidate` → `selected` (allowed)
   - `selected` → `candidate` (allowed, deselect)
   - Other transitions blocked at the API level (render pipeline sets `rendering`/`rendered`/`failed` internally)
   - Return 400 for invalid transitions

**Tradeoff accepted:** Users cannot undo boundary adjustments to original AI suggestions. Re-running detection is the recovery path.

## Implementation notes:
- Add status filter query param to GET /clips/video/{video_id}
- Validate status transitions in PATCH /clips/{id}: only candidate↔selected allowed via API
- Render pipeline (Week 3) will handle selected→rendering→rendered/failed transitions
- No new tables or columns needed — existing Clip model is sufficient
