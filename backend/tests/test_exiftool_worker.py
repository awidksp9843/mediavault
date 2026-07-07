"""Tests for ExifTool atomic write operations in exiftool_worker.py."""
import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, ANY

import pytest

from backend.exiftool_worker import (
    DEFAULT_METADATA,
    ExifToolQueue,
    read_xmp_metadata,
    write_xmp_metadata,
)


# ── Fixtures ──

@pytest.fixture
def temp_file():
    """Create a temporary file for testing."""
    tmp = Path(tempfile.mktemp(suffix=".jpg"))
    tmp.write_text("fake image data")
    yield tmp
    if tmp.exists():
        tmp.unlink(missing_ok=True)


@pytest.fixture
def temp_dir():
    """Create a temporary directory."""
    tmp = Path(tempfile.mkdtemp())
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


# ── Test: Atomic Write ──

class TestWriteXMP:
    """Tests for write_xmp_metadata atomic write logic."""

    def test_writes_to_temp_then_replaces(self, temp_file, mocker):
        """Verify atomic write: writes to a temp file first, then replaces original."""
        mock_subprocess = mocker.patch("backend.exiftool_worker.subprocess.run")
        mock_subprocess.return_value.returncode = 0
        mock_subprocess.return_value.stdout = ""
        mocker.patch("backend.exiftool_worker.shutil.which", return_value="/usr/bin/exiftool")
        mocker.patch("backend.exiftool_worker.blacklist.add")
        mocker.patch("backend.exiftool_worker.blacklist.remove")

        metadata = {"version": "1.0", "is_favorite": True, "tags": ["test"]}
        result = write_xmp_metadata(temp_file, metadata)

        assert result is True

        # Verify temp file was used then moved onto original
        calls = mock_subprocess.call_args_list
        assert len(calls) == 1
        temp_arg = calls[0].args[0][-1]  # last element of list = temp file path
        assert ".mediavault_tmp_" in temp_arg
        assert temp_file.name in temp_arg

    def test_cleans_up_temp_on_failure(self, temp_file, mocker):
        """Verify temp file is cleaned up when exiftool write fails."""
        mock_subprocess = mocker.patch("backend.exiftool_worker.subprocess.run")
        mock_subprocess.return_value.returncode = 1
        mock_subprocess.return_value.stderr = "error"
        mocker.patch("backend.exiftool_worker.shutil.which", return_value="/usr/bin/exiftool")
        mocker.patch("backend.exiftool_worker.blacklist.add")
        mocker.patch("backend.exiftool_worker.blacklist.remove")

        metadata = {"version": "1.0", "is_favorite": False, "tags": []}
        result = write_xmp_metadata(temp_file, metadata)

        assert result is False

        # Temp file should be cleaned up
        temp_path = temp_file.parent / f".mediavault_tmp_{temp_file.name}"
        assert not temp_path.exists()

    def test_schema_defaults_applied(self, temp_file, mocker):
        """Verify missing schema fields get defaults."""
        mock_subprocess = mocker.patch("backend.exiftool_worker.subprocess.run")
        mock_subprocess.return_value.returncode = 0
        mock_subprocess.return_value.stdout = ""
        mocker.patch("backend.exiftool_worker.shutil.which", return_value="/usr/bin/exiftool")
        mocker.patch("backend.exiftool_worker.blacklist.add")
        mocker.patch("backend.exiftool_worker.blacklist.remove")

        write_xmp_metadata(temp_file, {})

        # Extract JSON passed to exiftool
        call_args = mock_subprocess.call_args[0][0]
        json_flag = next(a for a in call_args if a.startswith("-XMP:MediaVault="))
        written = json.loads(json_flag.split("=", 1)[1])

        assert written["version"] == "1.0"
        assert written["is_favorite"] is False
        assert written["tags"] == []

    def test_skips_if_exiftool_missing(self, temp_file, mocker):
        """Verify no crash when exiftool is not installed."""
        mocker.patch("backend.exiftool_worker.shutil.which", return_value=None)
        result = write_xmp_metadata(temp_file, {"version": "1.0", "is_favorite": False, "tags": []})
        assert result is False

    def test_registers_blacklist(self, temp_file, mocker):
        """Verify file is blacklisted to prevent watchdog loop."""
        mock_subprocess = mocker.patch("backend.exiftool_worker.subprocess.run")
        mock_subprocess.return_value.returncode = 0
        mocker.patch("backend.exiftool_worker.shutil.which", return_value="/usr/bin/exiftool")
        blacklist_add = mocker.patch("backend.exiftool_worker.blacklist.add")
        blacklist_remove = mocker.patch("backend.exiftool_worker.blacklist.remove")

        write_xmp_metadata(temp_file, {"version": "1.0", "is_favorite": False, "tags": []})

        blacklist_add.assert_called_once_with(temp_file)


# ── Test: Read XMP ──

class TestReadXMP:
    """Tests for read_xmp_metadata."""

    def test_parses_json_from_exiftool_output(self, temp_file, mocker):
        """Verify JSON metadata is correctly extracted from exiftool output."""
        mock_subprocess = mocker.patch("backend.exiftool_worker.subprocess.run")
        mock_data = {"MediaVault": json.dumps({"version": "1.0", "is_favorite": True, "tags": ["test"]})}
        mock_subprocess.return_value.returncode = 0
        mock_subprocess.return_value.stdout = json.dumps([mock_data])
        mocker.patch("backend.exiftool_worker.shutil.which", return_value="/usr/bin/exiftool")

        result = read_xmp_metadata(temp_file)
        assert result == {"version": "1.0", "is_favorite": True, "tags": ["test"]}

    def test_returns_none_on_exiftool_failure(self, temp_file, mocker):
        """Verify None returned when exiftool fails."""
        mock_subprocess = mocker.patch("backend.exiftool_worker.subprocess.run")
        mock_subprocess.return_value.returncode = 1
        mocker.patch("backend.exiftool_worker.shutil.which", return_value="/usr/bin/exiftool")

        result = read_xmp_metadata(temp_file)
        assert result is None

    def test_returns_none_when_exiftool_missing(self, temp_file, mocker):
        """Verify None returned when exiftool is not installed."""
        mocker.patch("backend.exiftool_worker.shutil.which", return_value=None)
        result = read_xmp_metadata(temp_file)
        assert result is None


# ── Test: ExifTool Queue ──

class TestExifToolQueue:
    """Tests for ExifToolQueue async worker."""

    @pytest.mark.asyncio
    async def test_enqueue_and_process(self, temp_file, mocker):
        """Verify queue processes a write operation."""
        mock_write = mocker.patch("backend.exiftool_worker.write_xmp_metadata", return_value=True)
        q = ExifToolQueue()
        await q.start()

        metadata = {"version": "1.0", "is_favorite": False, "tags": ["test"]}
        await q.enqueue(temp_file, metadata)

        import asyncio
        await asyncio.sleep(0.2)

        mock_write.assert_called_once_with(temp_file, metadata)
        await q.stop()

    @pytest.mark.asyncio
    async def test_queue_processes_multiple_items(self, temp_file, mocker):
        """Verify queue processes multiple items sequentially."""
        mock_write = mocker.patch("backend.exiftool_worker.write_xmp_metadata", return_value=True)
        q = ExifToolQueue()
        await q.start()

        await q.enqueue(temp_file, {"version": "1.0", "is_favorite": False, "tags": ["a"]})
        await q.enqueue(temp_file, {"version": "1.0", "is_favorite": True, "tags": ["b"]})

        import asyncio
        await asyncio.sleep(0.3)

        assert mock_write.call_count == 2
        await q.stop()

    @pytest.mark.asyncio
    async def test_queue_handles_failure_gracefully(self, temp_file, mocker):
        """Verify queue continues processing after a failure."""
        mock_write = mocker.patch(
            "backend.exiftool_worker.write_xmp_metadata",
            side_effect=[False, True],
        )
        q = ExifToolQueue()
        await q.start()

        await q.enqueue(temp_file, {"version": "1.0", "is_favorite": False, "tags": ["fail"]})
        await q.enqueue(temp_file, {"version": "1.0", "is_favorite": True, "tags": ["ok"]})

        import asyncio
        await asyncio.sleep(0.3)

        assert mock_write.call_count == 2
        await q.stop()
