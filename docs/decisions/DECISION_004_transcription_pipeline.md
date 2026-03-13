# DECISION 004: Transcription Pipeline

## ARCHITECT proposes:

### Audio Extraction
- Extract audio from uploaded video using FFmpeg: `ffmpeg -i input.mp4 -vn -ac 1 -ar 16000 -b:a 64k output.mp3`
- Mono, 16kHz, 64kbps MP3 — optimized for speech, minimizes file size
- At 64kbps mono, a 3-hour video produces ~86MB of audio
- Store extracted audio temporarily in /tmp/clipforge/ (cleaned up after transcription)

### Whisper API Integration
- Use OpenAI Whisper API (`whisper-1` model) — pre-decided in tech stack
- Request word-level timestamps: `timestamp_granularities=["word", "segment"]`
- Response format: `verbose_json` for full timestamp data

### Chunking Strategy for Long Audio
- Whisper API has a **25MB file size limit** per request
- At 64kbps mono MP3, 25MB ≈ 52 minutes of audio
- **Strategy: Split audio into ≤24MB chunks with 5-second overlap**
  - Use FFmpeg to split: `ffmpeg -i audio.mp3 -ss {start} -t {chunk_duration} -c copy chunk_N.mp3`
  - Send each chunk to Whisper API sequentially
  - Merge transcripts: offset timestamps in chunk N by cumulative duration of chunks 0..N-1
  - Handle overlap: deduplicate words in the 5-second overlap window by matching word text and proximity
- For videos under 52 minutes (most uploads), no chunking needed — single API call

### Transcript Storage
- Store full transcript text in `transcripts.full_text` (plaintext, not encrypted)
- Store word-level timestamps in `transcripts.word_timestamps` (JSONB array)
- Format: `[{"word": "hello", "start": 0.0, "end": 0.5}, ...]`
- Size guard: reject word_timestamps JSONB > 50,000 entries (from DECISION_001)
- Transcripts persist for the life of the video (needed for clip re-detection and caption generation)

### Error Handling
- If Whisper returns an error: retry up to 3 times with exponential backoff (2s, 4s, 8s)
- If a single chunk fails after retries: mark job as failed, store error message, clean up temp files
- If Whisper returns empty/partial transcript: accept it (some videos have silent segments)
- Job status transitions: pending → running → completed|failed

### Cost
- ~$0.006/minute — a 3-hour video costs ~$1.08
- No cost optimization in MVP (will add caching/dedup later if needed)

## ADVERSARY attacks:

1. **Chunking overlap deduplication is fragile.** If Whisper transcribes the same 5-second overlap differently in two chunks (different word boundaries, slightly different text), the merge produces duplicate or garbled text at chunk boundaries. Real-world example: chunk 1 ends with "and so I think—" and chunk 2 starts with "I think that—" — naive dedup produces "and so I think— I think that—" or drops words.

2. **Sequential chunk processing is slow and non-resumable.** A 3-hour video produces ~4 chunks. If chunk 3 fails after chunks 1-2 succeeded (each taking 30-60s), the entire job restarts from scratch. At $0.36/chunk, that's wasted money and time. No checkpoint mechanism means the user waits 2+ minutes, sees a failure, and has to wait another 2+ minutes on retry.

3. **Temp file cleanup on worker crash.** If the ARQ worker process dies mid-transcription (OOM, deploy, crash), the temp audio files in /tmp/clipforge/ are orphaned. Over time, a busy server accumulates GB of dead audio files. The "clean up in finally block" pattern doesn't survive process death.

4. **Word timestamp array can be massive for 3-hour videos.** At ~150 words/minute for fast speech, a 3-hour video produces ~27,000 word entries. Each entry is ~50 bytes of JSON. That's ~1.35MB in a single JSONB column. Postgres handles this, but querying/updating becomes slow, and every `SELECT` on the transcript loads the full blob.

## JUDGE decides:

**Green light with required changes:**

1. **Overlap handling — accept imperfection for MVP.** Use a simple strategy: trim 2.5s from the end of each chunk's transcript and 2.5s from the start of the next chunk's transcript (discard overlap region from both sides, keep the "inner" parts). This loses ~5 seconds of transcript per chunk boundary but avoids dedup complexity. For a 3-hour video with 3 chunk boundaries, we lose ~15 seconds of transcript — acceptable for MVP. Document as known limitation.

2. **Sequential processing is fine for MVP.** Parallel chunk processing adds complexity (rate limits, ordering). Accept sequential. Do NOT add checkpoint/resume for individual chunks — if a chunk fails after retries, fail the whole job. The retry-from-scratch cost ($1-2) is acceptable at MVP scale.

3. **Temp file cleanup — add a startup sweep.** On ARQ worker startup, scan /tmp/clipforge/ and delete files older than 1 hour. This handles orphaned files from crashes. Not perfect but sufficient for MVP.

4. **Word timestamps size — accepted.** 27K entries at ~1.35MB is within Postgres JSONB comfort zone. The 50K entry guard from DECISION_001 protects against pathological cases. No lazy loading needed for MVP.

**Tradeoff accepted:** We lose ~5 seconds of transcript per chunk boundary. At MVP scale with mostly <1hr videos, most uploads won't chunk at all.

## Implementation notes:
- Audio extraction: mono, 16kHz, 64kbps MP3 via FFmpeg
- Chunk at 24MB (not 25MB) to leave headroom
- Overlap: discard 2.5s from each side of chunk boundary (no dedup logic)
- Sequential chunk processing, no checkpointing
- 3 retries with exponential backoff per chunk
- Worker startup: sweep /tmp/clipforge/ for files > 1 hour old
- Store word timestamps as JSONB array in transcripts table
- Job status: pending → running → completed|failed
