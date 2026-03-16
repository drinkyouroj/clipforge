"""Face detection, track smoothing, and crop calculation for smart reframing."""

import logging
import os
import subprocess
import tempfile

logger = logging.getLogger(__name__)

# Aspect ratio to width/height multiplier (relative to video height)
ASPECT_RATIOS = {
    "9:16": 9 / 16,
    "1:1": 1.0,
    "16:9": 16 / 9,
}


def smooth_face_track(track: list[dict], window: int = 15) -> list[dict]:
    """Apply moving average smoothing to face position track.

    Args:
        track: List of {"t": float, "x": int, "y": int}
        window: Smoothing window size

    Returns:
        Smoothed track with same structure
    """
    if len(track) <= 1:
        return track

    smoothed = []
    half = window // 2
    for i in range(len(track)):
        start = max(0, i - half)
        end = min(len(track), i + half + 1)
        avg_x = int(sum(t["x"] for t in track[start:end]) / (end - start))
        avg_y = int(sum(t["y"] for t in track[start:end]) / (end - start))
        smoothed.append({"t": track[i]["t"], "x": avg_x, "y": avg_y})

    return smoothed


def calculate_crop(
    video_width: int, video_height: int,
    face_x: int, aspect_ratio: str,
) -> dict:
    """Calculate crop parameters for a given aspect ratio centered on face_x.

    Args:
        video_width: Source video width in pixels
        video_height: Source video height in pixels
        face_x: Horizontal center of face in pixels
        aspect_ratio: Target aspect ratio ('9:16', '1:1', '16:9')

    Returns:
        Dict with crop_w, crop_h, crop_x, crop_y
    """
    if aspect_ratio == "16:9":
        return {
            "crop_w": video_width,
            "crop_h": video_height,
            "crop_x": 0,
            "crop_y": 0,
        }

    ratio = ASPECT_RATIOS[aspect_ratio]
    crop_h = video_height
    crop_w = int(video_height * ratio)

    # Clamp crop width to video width
    crop_w = min(crop_w, video_width)

    # Center crop on face_x
    crop_x = face_x - crop_w // 2

    # Clamp to frame bounds
    crop_x = max(0, crop_x)
    crop_x = min(crop_x, video_width - crop_w)

    return {
        "crop_w": crop_w,
        "crop_h": crop_h,
        "crop_x": crop_x,
        "crop_y": 0,
    }


def compute_crop_params(
    face_track: dict | None,
    video_width: int, video_height: int,
    aspect_ratio: str,
) -> dict:
    """Compute crop parameters from face track or center fallback.

    Args:
        face_track: {"frames": [...], "smoothed": bool} or None
        video_width: Source width
        video_height: Source height
        aspect_ratio: Target aspect ratio

    Returns:
        Dict with crop_w, crop_h, crop_x, crop_y (using median face position)
    """
    if face_track and face_track.get("frames"):
        frames = face_track["frames"]
        median_x = sorted(f["x"] for f in frames)[len(frames) // 2]
        return calculate_crop(video_width, video_height, median_x, aspect_ratio)

    # Center fallback: compute true center crop without face_x rounding error
    if aspect_ratio == "16:9":
        return {"crop_w": video_width, "crop_h": video_height, "crop_x": 0, "crop_y": 0}

    ratio = ASPECT_RATIOS[aspect_ratio]
    crop_h = video_height
    crop_w = min(int(video_height * ratio), video_width)
    crop_x = (video_width - crop_w) // 2
    return {"crop_w": crop_w, "crop_h": crop_h, "crop_x": crop_x, "crop_y": 0}


def extract_keyframes(video_path: str, start_time: float, duration: float, interval: float = 0.5) -> list[str]:
    """Extract keyframes from video segment using FFmpeg.

    Args:
        video_path: Path to video file
        start_time: Start time in seconds
        duration: Duration in seconds
        interval: Seconds between keyframes

    Returns:
        List of paths to extracted frame images
    """
    output_dir = tempfile.mkdtemp(prefix="clipforge_frames_")
    output_pattern = os.path.join(output_dir, "frame_%04d.jpg")

    subprocess.run(
        [
            "ffmpeg", "-ss", str(start_time),
            "-i", video_path,
            "-t", str(duration),
            "-vf", f"fps=1/{interval}",
            "-q:v", "2",
            "-y", output_pattern,
        ],
        capture_output=True, check=True, timeout=120,
    )

    frames = sorted(
        os.path.join(output_dir, f)
        for f in os.listdir(output_dir)
        if f.endswith(".jpg")
    )
    return frames


def detect_faces_in_frames(frame_paths: list[str], interval: float = 0.5) -> list[dict]:
    """Run face detection on extracted frames.

    Uses mediapipe if available, otherwise returns empty list (center crop fallback).

    Args:
        frame_paths: Paths to frame images
        interval: Time between frames in seconds

    Returns:
        List of {"t": float, "x": int, "y": int} for frames where face was detected
    """
    try:
        import mediapipe as mp
        import numpy as np
    except ImportError:
        logger.warning("mediapipe not available — falling back to center crop")
        return []

    # Find model file bundled with the package
    model_path = os.path.join(os.path.dirname(__file__), "models", "blaze_face_short_range.tflite")
    if not os.path.isfile(model_path):
        logger.warning("face detection model not found — falling back to center crop")
        return []

    try:
        options = mp.tasks.vision.FaceDetectorOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=model_path),
        )
        detector = mp.tasks.vision.FaceDetector.create_from_options(options)
    except Exception as e:
        logger.warning(f"face detection init failed: {e} — falling back to center crop")
        return []

    import cv2

    track = []
    for i, path in enumerate(frame_paths):
        image = cv2.imread(path)
        if image is None:
            continue

        h, w = image.shape[:2]
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = detector.detect(mp_image)

        if result.detections:
            bbox = result.detections[0].bounding_box
            center_x = bbox.origin_x + bbox.width // 2
            center_y = bbox.origin_y + bbox.height // 2
            track.append({"t": i * interval, "x": center_x, "y": center_y})

    detector.close()
    return track


def build_face_track(
    video_path: str, start_time: float, duration: float
) -> dict:
    """Build a complete face track for a clip segment.

    Returns:
        {"frames": [...], "smoothed": true, "method": "mediapipe"|"center"}
    """
    frames = extract_keyframes(video_path, start_time, duration)

    try:
        track = detect_faces_in_frames(frames)
    finally:
        # Clean up frame images
        import shutil
        if frames:
            frame_dir = os.path.dirname(frames[0])
            shutil.rmtree(frame_dir, ignore_errors=True)

    if not track:
        return {"frames": [], "smoothed": False, "method": "center"}

    smoothed = smooth_face_track(track, window=15)
    return {"frames": smoothed, "smoothed": True, "method": "mediapipe"}
