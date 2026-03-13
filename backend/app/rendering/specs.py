"""Platform export specifications per CLAUDE.md."""

PLATFORMS = {
    "shorts": {
        "name": "YouTube Shorts",
        "aspect_ratio": "9:16",
        "width": 1080,
        "height": 1920,
        "fps": 30,
        "max_duration": 60,
        "codec": "libx264",
        "audio_bitrate": "192k",
    },
    "tiktok": {
        "name": "TikTok",
        "aspect_ratio": "9:16",
        "width": 1080,
        "height": 1920,
        "fps": 30,
        "max_duration": 60,
        "codec": "libx264",
        "audio_bitrate": "192k",
    },
    "reels": {
        "name": "Instagram Reels",
        "aspect_ratio": "9:16",
        "width": 1080,
        "height": 1920,
        "fps": 30,
        "max_duration": 90,
        "codec": "libx264",
        "audio_bitrate": "192k",
    },
    "square": {
        "name": "Instagram Square",
        "aspect_ratio": "1:1",
        "width": 1080,
        "height": 1080,
        "fps": 30,
        "max_duration": 60,
        "codec": "libx264",
        "audio_bitrate": "192k",
    },
    "twitter": {
        "name": "X (Twitter)",
        "aspect_ratio": "16:9",
        "width": 1280,
        "height": 720,
        "fps": 30,
        "max_duration": 140,
        "codec": "libx264",
        "audio_bitrate": "192k",
    },
}


def get_platform_spec(platform: str) -> dict:
    """Get export specifications for a platform.

    Args:
        platform: One of 'shorts', 'tiktok', 'reels', 'square', 'twitter'

    Returns:
        Dict with aspect_ratio, width, height, fps, max_duration, codec, audio_bitrate

    Raises:
        ValueError: If platform is not recognized
    """
    if platform not in PLATFORMS:
        raise ValueError(f"Unknown platform: '{platform}'. Must be one of: {list(PLATFORMS.keys())}")
    return PLATFORMS[platform]
