# DECISION 001: Database Schema Design

## ARCHITECT proposes:

### Primary Key Strategy
Use UUID v4 (`uuid.uuid4()`) for all primary keys via PostgreSQL `gen_random_uuid()`.

**Rationale:** UUIDs prevent enumeration attacks on user-facing resources (videos, clips, exports).
Sequential IDs leak information (total user count, upload rate). UUIDs are safe to expose in URLs
and API responses without an additional public-ID layer.

### Schema

**users**
| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | `gen_random_uuid()` |
| email | VARCHAR(255) UNIQUE NOT NULL | Indexed |
| hashed_password | VARCHAR(255) NOT NULL | bcrypt |
| is_active | BOOLEAN DEFAULT TRUE | Soft disable |
| email_verified | BOOLEAN DEFAULT FALSE | |
| email_verification_token | VARCHAR(255) | Nullable, cleared after verification |
| password_reset_token | VARCHAR(255) | Nullable, cleared after reset |
| password_reset_expires | TIMESTAMPTZ | Nullable |
| tos_accepted_at | TIMESTAMPTZ NOT NULL | Required at registration |
| created_at | TIMESTAMPTZ DEFAULT now() | |
| updated_at | TIMESTAMPTZ DEFAULT now() | |

**videos**
| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| user_id | UUID FK→users NOT NULL | Indexed |
| original_filename | VARCHAR(255) NOT NULL | User's filename |
| s3_key | VARCHAR(512) NOT NULL | `uploads/{user_id}/{uuid}.{ext}` |
| file_size | BIGINT NOT NULL | Bytes |
| duration | FLOAT | Seconds, from ffprobe |
| mime_type | VARCHAR(100) | From magic bytes |
| status | VARCHAR(20) NOT NULL DEFAULT 'uploaded' | uploaded/processing/ready/failed/deleted |
| uploaded_at | TIMESTAMPTZ DEFAULT now() | |
| deleted_at | TIMESTAMPTZ | Soft delete |
| created_at | TIMESTAMPTZ DEFAULT now() | |

Index: `(user_id, created_at DESC)` for listing user's videos.
Index: `(user_id, status)` for filtering active videos.

**transcripts**
| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| video_id | UUID FK→videos UNIQUE NOT NULL | One transcript per video |
| content | TEXT NOT NULL | Full transcript text |
| word_timestamps | JSONB NOT NULL | `[{"word": "...", "start": 0.0, "end": 0.5}, ...]` |
| whisper_model | VARCHAR(50) DEFAULT 'whisper-1' | |
| language | VARCHAR(10) | Detected by Whisper |
| created_at | TIMESTAMPTZ DEFAULT now() | |

**Decision: JSONB for word_timestamps.** A normalized `words` table would create millions of rows
for long videos (3hrs × ~150 wpm = 27,000 words). JSONB keeps this as a single read, which is
the dominant access pattern (load all timestamps for caption rendering). We never query individual
words — we always load the full array.

**clips**
| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| video_id | UUID FK→videos NOT NULL | |
| transcript_id | UUID FK→transcripts | Nullable until transcript exists |
| start_time | FLOAT NOT NULL | Seconds |
| end_time | FLOAT NOT NULL | Seconds |
| duration | FLOAT NOT NULL | Computed: end - start |
| virality_score | INTEGER | 0-100 |
| hook | TEXT | Opening line |
| reasoning | TEXT | Why this clip scores high |
| clip_type | VARCHAR(30) | insight/story/controversy/how-to/emotion/humor |
| suggested_title | VARCHAR(100) | |
| platform_fit | JSONB | `["shorts", "tiktok", "reels"]` |
| status | VARCHAR(20) NOT NULL DEFAULT 'candidate' | candidate/selected/rendering/rendered/failed |
| rendered_s3_key | VARCHAR(512) | Populated after render |
| created_at | TIMESTAMPTZ DEFAULT now() | |

Index: `(video_id, virality_score DESC)` for sorted clip listing.

**Decision: JSONB for platform_fit.** It's a simple string array, rarely queried independently.
A junction table would add complexity for no benefit.

**jobs**
| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| user_id | UUID FK→users NOT NULL | |
| video_id | UUID FK→videos NOT NULL | |
| job_type | VARCHAR(20) NOT NULL | transcribe/detect_clips/render |
| status | VARCHAR(20) NOT NULL DEFAULT 'pending' | pending/running/completed/failed |
| error_message | TEXT | Nullable |
| started_at | TIMESTAMPTZ | |
| completed_at | TIMESTAMPTZ | |
| created_at | TIMESTAMPTZ DEFAULT now() | |

Index: `(user_id, created_at DESC)` for job history.
Index: `(video_id, job_type)` for finding jobs by video.

**exports**
| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| clip_id | UUID FK→clips NOT NULL | |
| user_id | UUID FK→users NOT NULL | |
| platform | VARCHAR(30) NOT NULL | shorts/tiktok/reels/square/x |
| aspect_ratio | VARCHAR(10) NOT NULL | 9:16/1:1/16:9 |
| resolution | VARCHAR(20) NOT NULL | 1080x1920, 1080x1080, 1280x720 |
| s3_key | VARCHAR(512) | |
| download_url | TEXT | Signed URL |
| expires_at | TIMESTAMPTZ | URL expiry |
| created_at | TIMESTAMPTZ DEFAULT now() | |

Index: `(user_id, created_at DESC)` for export history.

### Transcript Storage Decision
Store transcripts in plaintext in the DB (not encrypted, not deleted after clip detection).

**Rationale:** Transcripts are needed multiple times — for clip detection, for caption rendering,
for user review, and for re-running clip detection if the prompt improves. Deleting after first
use would force re-transcription ($0.006/min). Encryption at rest is handled by PostgreSQL's
disk-level encryption (or RDS encryption) — column-level encryption adds complexity with no
security benefit when the application server has the decryption key anyway.

## ADVERSARY attacks:

### Attack 1: UUID v4 index performance degradation
UUIDs are random, which means B-tree index insertions are scattered across the entire index space.
On a table with millions of rows, this causes index bloat and page splits. For a video processing
app where `jobs` could accumulate quickly (3-5 jobs per video × thousands of videos), the `jobs`
table will see significant write amplification.

**Failure scenario:** After 6 months with 10,000 users, the `jobs` table has 500K+ rows. Index
scans on `(user_id, created_at)` slow from 2ms to 50ms+ because the UUID PK index is fragmented.
Background autovacuum can't keep up during peak hours when many render jobs complete simultaneously.

### Attack 2: No `CHECK` constraints on status fields
Using VARCHAR for status fields (instead of PostgreSQL `ENUM` or `CHECK` constraints) means the
application code is the only thing preventing `status = 'banana'` from being written. If a bug
in the job worker sets an invalid status, the system enters an undefined state. The dashboard
shows "banana" as the video status.

**Failure scenario:** A developer adds a new job type but typos the status string in one code path.
Videos get stuck in a status that no query matches. The user sees "processing" forever. The cleanup
cron doesn't catch it because it only queries known statuses.

### Attack 3: Soft delete without exclusion index
The `videos` table uses `deleted_at` for soft delete, but every query must remember to add
`WHERE deleted_at IS NULL`. One missed filter and deleted videos appear in user listings.
This is an IDOR risk — a soft-deleted video still has its S3 key, and if exposed, the signed
URL generation could serve a "deleted" file.

**Failure scenario:** A new endpoint is added to serve video metadata. The developer forgets
the `deleted_at IS NULL` filter. A user who deleted their video discovers it's still accessible
through the API. They file a privacy complaint.

### Attack 4: JSONB word_timestamps with no size guard
A 3-hour video at 150 wpm produces ~27,000 word entries. As JSONB, this is a single column value
that must be fully loaded into memory. If Whisper returns anomalous output (e.g., a hallucinated
transcript with 500,000 entries for a noisy audio track), the JSONB field could be several MB,
causing OOM on deserialization.

**Failure scenario:** A user uploads a 3-hour ambient music video. Whisper hallucinates repeated
words for the entire duration. The `word_timestamps` JSONB field is 15MB. When the clip detection
service loads it, the API worker's memory spikes, causing the container to be OOM-killed.

## JUDGE decides:

**Verdict: ARCHITECT's schema is approved with required modifications.**

1. **UUIDs stay.** The performance concern is valid at extreme scale, but ClipForge will not
   reach millions of rows in the jobs table during MVP. UUID v7 (time-ordered) would be ideal
   but requires PostgreSQL extension or application-level generation. **Accepted tradeoff:**
   Random UUID v4 with standard B-tree indexes. Revisit if query latency degrades measurably
   post-launch.

2. **Add CHECK constraints on all status fields.** ADVERSARY is right — VARCHAR without constraints
   is a data integrity risk. Use `CHECK (status IN ('uploaded', 'processing', ...))` on each
   table. This gives DB-level validation without the migration pain of PostgreSQL ENUMs (which
   require `ALTER TYPE` to add values).

3. **Add a partial index for soft delete.** Create `CREATE INDEX idx_videos_active ON videos (user_id, created_at DESC) WHERE deleted_at IS NULL`. This makes the common query (list active videos) fast and explicit. Application code should still filter, but the index makes the intent visible.

4. **Add a size guard on word_timestamps.** Application code must validate `len(word_timestamps) <= 50000` before DB insert. If Whisper returns more, truncate with a warning logged. This prevents the OOM scenario.

## Implementation notes:
- All PKs: UUID v4 via `gen_random_uuid()`
- All status fields: VARCHAR with CHECK constraints (not ENUM)
- `videos.deleted_at`: partial index on `(user_id, created_at) WHERE deleted_at IS NULL`
- `transcripts.word_timestamps`: application-level size guard at 50,000 entries
- Indexes on `(user_id, created_at DESC)` for all user-scoped tables
- `transcripts.video_id` is UNIQUE (one transcript per video)
- Transcript stored in plaintext, not encrypted or deleted after use
