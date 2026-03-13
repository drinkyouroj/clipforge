"""Tests for temp file cleanup handling subdirectories."""

import os
import time
from unittest.mock import patch

from app.jobs.tasks import _cleanup_old_temp_files, TEMP_DIR


def test_cleanup_removes_old_subdirectories(tmp_path):
    """Cleanup sweeps old job dirs inside render/, even if render/ itself is recent."""
    with patch("app.jobs.tasks.TEMP_DIR", str(tmp_path)):
        # Create render/ parent (recent — new jobs keep this fresh)
        render_dir = tmp_path / "render"
        render_dir.mkdir()

        # Create an old job subdirectory inside render/
        old_dir = render_dir / "old-job-id"
        old_dir.mkdir()
        old_file = old_dir / "input.mp4"
        old_file.write_text("data")

        # Make job dir appear old (>1hr) but NOT the parent render/ dir
        old_time = time.time() - 7200
        os.utime(str(old_dir), (old_time, old_time))
        # render/ dir stays recent (default mtime = now)

        # Create a recent file at top level (should NOT be deleted)
        recent = tmp_path / "recent.mp4"
        recent.write_text("fresh")

        _cleanup_old_temp_files()

        assert not old_dir.exists(), "Old render job subdirectory should be removed"
        assert recent.exists(), "Recent files should not be removed"
        assert render_dir.exists(), "render/ parent should remain (may have active jobs)"
