# DECISION 007: Render Pipeline and FFmpeg Command Design

## ARCHITECT proposes:

### Three-Step Chained Pipeline
Render jobs use three chained ARQ tasks for granular retry:
1. `prepare_render` — download video from S3, run mediapipe face detection (cached on Clip), generate ASS captions
2. `execute_render` — assemble FFmpeg command per platform specs, run render
3. `upload_output` — upload to S3, generate presigned URL, update Export record

Steps share state via `/tmp/clipforge/render/{job_id}/` temp directory and `Job.render_context` JSONB.

### Export-Centric Model
One Export record per clip-platform combination. Export.status tracks render lifecycle (pending → rendering → rendered → failed). Clip.status remains `selected` throughout — no per-export mutation of clip state.

### Face Detection + Smart Crop
- mediapipe face detection on keyframes every 0.5s
- Smoothed face position track (moving average, window=15) stored as JSONB on Clip.face_track
- Reusable across multiple exports of same clip
- Fallback: center crop if no face detected
- Crop formulas: 9:16 = `crop=ih*(9/16):ih:smooth_x:0`, 1:1 = `crop=ih:ih:smooth_x:0`, 16:9 = scale only

### ASS Captions with Word Highlighting
- ASS/SSA format (not SRT) for per-word color timing
- Active word: yellow (\c&H0000FFFF&), inactive: white (\c&H00FFFFFF&)
- ~3-4 words per display line, split at pauses >0.5s
- Timestamps relative to 0 (not original video time) since FFmpeg -ss before -i resets timeline

### FFmpeg Command
```
ffmpeg -ss {start} -i {input} -t {duration} \
  -vf "crop=...,scale=...,ass={captions}" \
  -c:v libx264 -preset fast -crf 23 \
  -c:a aac -b:a 192k -ac 2 \
  -af loudnorm=I=-14:LRA=11:TP=-1.5 \
  -r 30 -movflags +faststart -y {output}
```

### Platform Specs
| Platform | Aspect | Resolution | FPS | Max Duration |
|----------|--------|------------|-----|-------------|
| shorts | 9:16 | 1080x1920 | 30 | 60s |
| tiktok | 9:16 | 1080x1920 | 30 | 60s |
| reels | 9:16 | 1080x1920 | 30 | 90s |
| square | 1:1 | 1080x1080 | 30 | 60s |
| twitter | 16:9 | 1280x720 | 30 | 140s |

All: MP4 H.264, AAC 192kbps stereo, -14 LUFS loudness normalization, faststart.

## ADVERSARY attacks:

1. **FFmpeg crash leaves orphan temp files consuming disk.** If `execute_render` crashes mid-render, the partial output file (potentially GBs) sits in `/tmp/clipforge/render/{job_id}/` until someone notices. The existing cleanup only sweeps top-level files in `/tmp/clipforge/`, not subdirectories.

2. **Concurrent exports for same clip create face detection race condition.** If two exports are triggered simultaneously for the same clip and both see `face_track IS NULL`, they'll both run mediapipe. This wastes compute and could produce conflicting writes to the same JSONB column.

3. **Output file larger than input.** FFmpeg misconfiguration (wrong codec, no compression) could produce an output larger than the input segment. This silently wastes S3 storage and user bandwidth. No validation catches it.

4. **ASS subtitle non-ASCII corruption.** Word timestamps may contain em dashes, curly quotes, or non-Latin characters. ASS format uses backslash escape sequences that could collide with special characters, producing garbled captions.

5. **mediapipe not available in CI/production.** mediapipe has heavy native dependencies (OpenCV, TFLite). It may fail to install on Alpine-based Docker images or ARM architectures. No fallback if import fails.

## JUDGE decides:

**Green light with required changes:**

1. **Temp file cleanup — fix required.** Update `_cleanup_old_temp_files()` to recursively sweep subdirectories. Each pipeline step must also clean up on failure via `shutil.rmtree`. Both defenses.

2. **Face detection race — accept for MVP.** Concurrent exports for the same clip are an edge case (user would have to click two platforms within seconds). The duplicate work is harmless — both writes produce the same face track. If this becomes a problem post-launch, add a per-clip lock. Not worth the complexity now.

3. **Output size check — required.** `execute_render` must verify `output_size < 2 * input_segment_size`. If exceeded, fail with descriptive error. Simple to implement, catches real misconfiguration.

4. **ASS non-ASCII — handle in implementation.** Escape backslashes and braces in word text before inserting into ASS tags. Test with em dashes and curly quotes specifically.

5. **mediapipe availability — accept with fallback.** If mediapipe import fails, fall back to center crop. Log a warning. This lets the pipeline work in environments without mediapipe (dev, CI) while still producing usable output.

## Implementation notes:
- Export.status tracks render lifecycle, NOT Clip.status
- Export.job_id FK links to the render Job
- Clip.rendered_s3_key is NOT used by this pipeline (per-export keys on Export.s3_key)
- Caption timestamps rebased to 0 due to -ss input seeking
- Rate limit: 10 exports/day rolling window (abuse prevention, not billing)
