"""
London-School TDD test suite for comfyui-bridge.

Tests are grouped by increment and follow the London School style:
- Mock at I/O boundaries (filesystem, requests, ComfyUI WebSocket/HTTP)
- Assert on interactions (what was called, with what) AND return values
- No real filesystem writes, no real HTTP calls
"""

import asyncio
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

# ---------------------------------------------------------------------------
# Import the objects under test (stub implementations)
# ---------------------------------------------------------------------------
from bridge import (
    IMAGE_DIR,
    cleanup_old_images,
    inject_prompt,
    make_image_filename,
    save_image_to_disk,
    stream_prompt_progress,
    wait_for_prompt_async,
)
from main import app
from mcp_tools import generate_image


# ===========================================================================
# Increment 1 — make_image_filename()
# ===========================================================================

class TestMakeImageFilename:
    """Tests for make_image_filename() — pure, no I/O."""

    def test_increment1_returns_string_ending_with_png(self):
        result = make_image_filename()
        assert isinstance(result, str)
        assert result.endswith(".png")

    def test_increment1_matches_expected_pattern(self):
        result = make_image_filename()
        pattern = r"^\d{8}T\d{6}-[0-9a-f]{8}\.png$"
        assert re.match(pattern, result), (
            f"Filename '{result}' does not match pattern '{pattern}'"
        )

    def test_increment1_two_calls_return_different_filenames(self):
        first = make_image_filename()
        second = make_image_filename()
        assert first != second, "Two consecutive calls must return different filenames"

    def test_increment1_timestamp_prefix_reflects_current_datetime(self):
        fixed_dt = datetime(2026, 5, 31, 14, 23, 1)
        with patch("bridge.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_dt
            # Ensure date still works (used elsewhere)
            mock_dt.side_effect = None
            result = make_image_filename()
        assert result.startswith("20260531T142301-"), (
            f"Expected timestamp prefix '20260531T142301-', got '{result}'"
        )


# ===========================================================================
# Increment 1 — cleanup_old_images()
# ===========================================================================

class TestCleanupOldImages:
    """Tests for cleanup_old_images(image_dir, retention_days)."""

    def test_increment1_returns_empty_list_when_dir_does_not_exist(self, tmp_path):
        nonexistent = tmp_path / "does-not-exist"
        result = cleanup_old_images(nonexistent, retention_days=7)
        assert result == []

    def test_increment1_deletes_folder_older_than_retention_days(self, tmp_path):
        old_date = (date.today() - timedelta(days=10)).isoformat()
        old_dir = tmp_path / old_date
        old_dir.mkdir()

        with patch("shutil.rmtree") as mock_rmtree:
            result = cleanup_old_images(tmp_path, retention_days=7)

        mock_rmtree.assert_called_once_with(old_dir)
        assert old_dir in result

    def test_increment1_does_not_delete_todays_folder(self, tmp_path):
        today_dir = tmp_path / date.today().isoformat()
        today_dir.mkdir()

        with patch("shutil.rmtree") as mock_rmtree:
            result = cleanup_old_images(tmp_path, retention_days=7)

        mock_rmtree.assert_not_called()
        assert result == []

    def test_increment1_does_not_delete_folder_within_retention_window(self, tmp_path):
        recent_date = (date.today() - timedelta(days=3)).isoformat()
        recent_dir = tmp_path / recent_date
        recent_dir.mkdir()

        with patch("shutil.rmtree") as mock_rmtree:
            result = cleanup_old_images(tmp_path, retention_days=7)

        mock_rmtree.assert_not_called()
        assert result == []

    def test_increment1_does_not_delete_non_date_named_entries(self, tmp_path):
        some_dir = tmp_path / "some-folder"
        some_dir.mkdir()

        with patch("shutil.rmtree") as mock_rmtree:
            result = cleanup_old_images(tmp_path, retention_days=7)

        mock_rmtree.assert_not_called()
        assert result == []

    def test_increment1_uses_shutil_rmtree_for_removal(self, tmp_path):
        old_date = (date.today() - timedelta(days=10)).isoformat()
        old_dir = tmp_path / old_date
        old_dir.mkdir()

        with patch("bridge.shutil.rmtree") as mock_rmtree:
            cleanup_old_images(tmp_path, retention_days=7)

        mock_rmtree.assert_called_once_with(old_dir)

    def test_increment1_returns_list_of_removed_paths(self, tmp_path):
        old_date1 = (date.today() - timedelta(days=10)).isoformat()
        old_date2 = (date.today() - timedelta(days=15)).isoformat()
        (tmp_path / old_date1).mkdir()
        (tmp_path / old_date2).mkdir()

        with patch("bridge.shutil.rmtree"):
            result = cleanup_old_images(tmp_path, retention_days=7)

        assert len(result) == 2
        assert all(isinstance(p, Path) for p in result)

    def test_increment1_continues_when_rmtree_raises_os_error(self, tmp_path):
        old_date1 = (date.today() - timedelta(days=10)).isoformat()
        old_date2 = (date.today() - timedelta(days=15)).isoformat()
        (tmp_path / old_date1).mkdir()
        (tmp_path / old_date2).mkdir()

        with patch("bridge.shutil.rmtree", side_effect=OSError("permission denied")):
            # Must not raise; should log and continue
            result = cleanup_old_images(tmp_path, retention_days=7)

        # Both were attempted; neither succeeded (rmtree raised), but function
        # should still return the paths it tried to remove (or empty — either
        # is acceptable as long as no exception propagates)
        assert isinstance(result, list)


# ===========================================================================
# Increment 2 — save_image_to_disk()
# ===========================================================================

class TestSaveImageToDisk:
    """Tests for save_image_to_disk(image_bytes, image_dir)."""

    def test_increment2_creates_date_subdirectory(self, tmp_path):
        image_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        save_image_to_disk(image_bytes, tmp_path)
        today_str = date.today().isoformat()
        assert (tmp_path / today_str).is_dir()

    def test_increment2_writes_exact_bytes_to_file(self, tmp_path):
        image_bytes = b"\x89PNG\r\n\x1a\n" + b"test_image_data"
        save_image_to_disk(image_bytes, tmp_path)
        today_str = date.today().isoformat()
        date_dir = tmp_path / today_str
        files = list(date_dir.glob("*.png"))
        assert len(files) == 1
        assert files[0].read_bytes() == image_bytes

    def test_increment2_returns_date_str_matching_today(self, tmp_path):
        image_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 10
        date_str, filename = save_image_to_disk(image_bytes, tmp_path)
        assert date_str == date.today().isoformat()

    def test_increment2_returns_filename_matching_pattern(self, tmp_path):
        image_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 10
        date_str, filename = save_image_to_disk(image_bytes, tmp_path)
        pattern = r"^\d{8}T\d{6}-[0-9a-f]{8}\.png$"
        assert re.match(pattern, filename), (
            f"Filename '{filename}' does not match pattern '{pattern}'"
        )

    def test_increment2_file_exists_on_disk_after_call(self, tmp_path):
        image_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 10
        date_str, filename = save_image_to_disk(image_bytes, tmp_path)
        saved_file = tmp_path / date_str / filename
        assert saved_file.exists()

    def test_increment2_returns_tuple_of_two_strings(self, tmp_path):
        image_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 10
        result = save_image_to_disk(image_bytes, tmp_path)
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert all(isinstance(s, str) for s in result)


# ===========================================================================
# Increment 3 — inject_prompt() steps, stream_prompt_progress(), wait_for_prompt_async()
# ===========================================================================

def _make_simple_workflow():
    return {
        "1": {"class_type": "BasicScheduler", "inputs": {"steps": 8, "scheduler": "normal", "denoise": 1.0, "model": ["x", 0]}},
        "2": {"class_type": "KSampler", "inputs": {"steps": 8, "seed": 0, "noise_seed": 0}},
        "3": {"class_type": "RandomNoise", "inputs": {"noise_seed": 0}},
    }


class TestInjectPromptSteps:
    """Tests for inject_prompt() steps injection."""

    def test_inject_steps_into_basic_scheduler(self):
        wf = _make_simple_workflow()
        result = inject_prompt(wf, "a cat", 512, 512, seed=1, steps=25)
        assert result["1"]["inputs"]["steps"] == 25

    def test_inject_steps_into_ksampler(self):
        wf = _make_simple_workflow()
        result = inject_prompt(wf, "a cat", 512, 512, seed=1, steps=15)
        assert result["2"]["inputs"]["steps"] == 15

    def test_steps_none_leaves_workflow_default(self):
        wf = _make_simple_workflow()
        result = inject_prompt(wf, "a cat", 512, 512, seed=1, steps=None)
        # steps=None must not change the workflow default (8)
        assert result["1"]["inputs"]["steps"] == 8
        assert result["2"]["inputs"]["steps"] == 8

    def test_steps_does_not_affect_random_noise_node(self):
        wf = _make_simple_workflow()
        result = inject_prompt(wf, "a cat", 512, 512, seed=1, steps=30)
        # RandomNoise has no 'steps' field — must not be added
        assert "steps" not in result["3"]["inputs"]


class TestStreamPromptProgress:
    """Tests for stream_prompt_progress(prompt_id, timeout)."""

    @pytest.mark.asyncio
    async def test_yields_progress_events(self):
        prompt_id = "prog-test-1"

        messages = [
            json.dumps({"type": "progress", "data": {"value": 1, "max": 10, "prompt_id": prompt_id}}),
            json.dumps({"type": "progress", "data": {"value": 5, "max": 10, "prompt_id": prompt_id}}),
            json.dumps({"type": "executing", "data": {"node": None, "prompt_id": prompt_id}}),
        ]

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=messages)
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=False)

        with patch("bridge.websockets.connect", return_value=mock_ws):
            events = []
            async for event in stream_prompt_progress(prompt_id, timeout=10):
                events.append(event)

        progress_events = [e for e in events if e["type"] == "progress"]
        done_events = [e for e in events if e["type"] == "done"]
        assert len(progress_events) == 2
        assert progress_events[0] == {"type": "progress", "step": 1, "total": 10}
        assert progress_events[1] == {"type": "progress", "step": 5, "total": 10}
        assert len(done_events) == 1

    @pytest.mark.asyncio
    async def test_yields_done_when_executing_node_is_null(self):
        prompt_id = "done-test"
        messages = [
            json.dumps({"type": "executing", "data": {"node": None, "prompt_id": prompt_id}}),
        ]
        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=messages)
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=False)

        with patch("bridge.websockets.connect", return_value=mock_ws):
            events = []
            async for event in stream_prompt_progress(prompt_id, timeout=10):
                events.append(event)

        assert any(e["type"] == "done" for e in events)

    @pytest.mark.asyncio
    async def test_skips_binary_frames(self):
        prompt_id = "binary-test"
        messages = [
            b"\x00\x01binary_preview_data",  # binary frame — must be ignored
            json.dumps({"type": "executing", "data": {"node": None, "prompt_id": prompt_id}}),
        ]
        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=messages)
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=False)

        with patch("bridge.websockets.connect", return_value=mock_ws):
            events = []
            async for event in stream_prompt_progress(prompt_id, timeout=10):
                events.append(event)

        # Must still complete without error
        assert any(e["type"] == "done" for e in events)

    @pytest.mark.asyncio
    async def test_raises_timeout_error(self):
        prompt_id = "timeout-test"
        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=asyncio.TimeoutError())
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=False)

        with patch("bridge.websockets.connect", return_value=mock_ws):
            with pytest.raises(TimeoutError):
                async for _ in stream_prompt_progress(prompt_id, timeout=1):
                    pass


class TestWaitForPromptAsync:
    """Tests for wait_for_prompt_async(prompt_id, timeout)."""

    @pytest.mark.asyncio
    async def test_returns_history_entry_after_done(self):
        prompt_id = "hist-test-1"
        expected_entry = {"outputs": {"9": {"images": [{"filename": "img.png"}]}}}

        async def fake_stream(pid, timeout=1200):
            yield {"type": "progress", "step": 1, "total": 10}
            yield {"type": "done"}

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {prompt_id: expected_entry}

        with patch("bridge.stream_prompt_progress", side_effect=fake_stream), \
             patch("bridge.asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
            mock_thread.return_value = mock_resp
            result = await wait_for_prompt_async(prompt_id, timeout=10)

        assert result == expected_entry

    @pytest.mark.asyncio
    async def test_raises_timeout_error_when_stream_times_out(self):
        prompt_id = "timeout-hist"

        async def fake_stream_timeout(pid, timeout=1200):
            raise TimeoutError("ws timed out")
            yield  # make it a generator

        with patch("bridge.stream_prompt_progress", side_effect=fake_stream_timeout):
            with pytest.raises(TimeoutError):
                await wait_for_prompt_async(prompt_id, timeout=1)

    @pytest.mark.asyncio
    async def test_fetches_history_via_rest_after_completion(self):
        prompt_id = "hist-fetch-test"

        async def fake_stream(pid, timeout=1200):
            yield {"type": "done"}

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {prompt_id: {"outputs": {}}}

        with patch("bridge.stream_prompt_progress", side_effect=fake_stream), \
             patch("bridge.asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
            mock_thread.return_value = mock_resp
            await wait_for_prompt_async(prompt_id, timeout=10)

        # Must have called the history REST endpoint
        mock_thread.assert_called_once()


# ===========================================================================
# Increment 4 — GET /v1/images/{date}/{filename}
# ===========================================================================

class TestServeImage:
    """Tests for GET /v1/images/{date}/{filename} FastAPI route."""

    @pytest.mark.asyncio
    async def test_increment4_returns_200_with_image_png_content_type(self, tmp_path):
        today_str = date.today().isoformat()
        date_dir = tmp_path / today_str
        date_dir.mkdir()
        img_file = date_dir / "20260531T142301-a3f7c2d1.png"
        img_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)

        with patch("bridge.IMAGE_DIR", tmp_path):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get(
                    f"/v1/images/{today_str}/20260531T142301-a3f7c2d1.png"
                )

        assert response.status_code == 200
        assert "image/png" in response.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_increment4_returns_404_when_file_does_not_exist(self, tmp_path):
        with patch("bridge.IMAGE_DIR", tmp_path):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get(
                    "/v1/images/2026-01-01/nonexistent-file.png"
                )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_increment4_serves_correct_file_from_image_dir(self, tmp_path):
        today_str = date.today().isoformat()
        date_dir = tmp_path / today_str
        date_dir.mkdir()
        expected_content = b"\x89PNG\r\n\x1a\nUNIQUE_CONTENT_MARKER"
        img_file = date_dir / "20260531T142301-deadbeef.png"
        img_file.write_bytes(expected_content)

        with patch("bridge.IMAGE_DIR", tmp_path):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get(
                    f"/v1/images/{today_str}/20260531T142301-deadbeef.png"
                )

        assert response.status_code == 200
        assert response.content == expected_content


# ===========================================================================
# Increment 5 — POST /v1/images/generations
# ===========================================================================

class TestGenerateImages:
    """Tests for POST /v1/images/generations FastAPI route."""

    def _make_request_payload(self, **overrides):
        payload = {
            "model": "flux-schnell",
            "prompt": "a red sunset",
            "n": 1,
            "size": "1024x1024",
            "response_format": "b64_json",
        }
        payload.update(overrides)
        return payload

    @pytest.mark.asyncio
    async def test_increment5_returns_500_when_workflow_json_not_found(self, tmp_path):
        with patch("bridge.WORKFLOW_DIR", tmp_path):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/v1/images/generations",
                    json=self._make_request_payload(model="no-such-model"),
                )

        assert response.status_code == 500

    @pytest.mark.asyncio
    async def test_increment5_calls_cleanup_old_images_at_start(self, tmp_path):
        workflow_dir = tmp_path / "workflows"
        workflow_dir.mkdir()
        (workflow_dir / "flux-schnell.json").write_text('{"1": {"class_type": "KSampler", "inputs": {"seed": 0, "noise_seed": 0}}}')

        image_dir = tmp_path / "images"
        image_dir.mkdir()

        with (
            patch("bridge.WORKFLOW_DIR", workflow_dir),
            patch("bridge.IMAGE_DIR", image_dir),
            patch("bridge.cleanup_old_images") as mock_cleanup,
            patch("bridge.wait_for_prompt_async", new_callable=AsyncMock) as mock_wait,
            patch("bridge.save_image_to_disk") as mock_save,
            patch("requests.post") as mock_post,
            patch("bridge.get_image_data") as mock_get_img,
        ):
            mock_cleanup.return_value = []
            mock_wait.return_value = {
                "outputs": {"9": {"images": [{"filename": "img.png", "subfolder": "", "type": "output"}]}}
            }
            mock_get_img.return_value = b"\x89PNG\r\n\x1a\n"
            mock_save.return_value = (date.today().isoformat(), "20260531T142301-a3f7c2d1.png")
            mock_post_response = MagicMock()
            mock_post_response.raise_for_status.return_value = None
            mock_post_response.json.return_value = {"prompt_id": "test-id-123"}
            mock_post.return_value = mock_post_response

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                await client.post(
                    "/v1/images/generations",
                    json=self._make_request_payload(),
                )

        mock_cleanup.assert_called_once()

    @pytest.mark.asyncio
    async def test_increment5_calls_save_image_to_disk_with_fetched_bytes(self, tmp_path):
        workflow_dir = tmp_path / "workflows"
        workflow_dir.mkdir()
        (workflow_dir / "flux-schnell.json").write_text('{"1": {"class_type": "KSampler", "inputs": {"seed": 0, "noise_seed": 0}}}')

        image_dir = tmp_path / "images"
        image_dir.mkdir()

        image_bytes = b"\x89PNG\r\n\x1a\nFAKE_IMAGE_DATA"

        with (
            patch("bridge.WORKFLOW_DIR", workflow_dir),
            patch("bridge.IMAGE_DIR", image_dir),
            patch("bridge.cleanup_old_images", return_value=[]),
            patch("bridge.wait_for_prompt_async", new_callable=AsyncMock) as mock_wait,
            patch("bridge.save_image_to_disk") as mock_save,
            patch("requests.post") as mock_post,
            patch("bridge.get_image_data") as mock_get_img,
        ):
            mock_wait.return_value = {
                "outputs": {"9": {"images": [{"filename": "img.png", "subfolder": "", "type": "output"}]}}
            }
            mock_get_img.return_value = image_bytes
            mock_save.return_value = (date.today().isoformat(), "20260531T142301-a3f7c2d1.png")
            mock_post_response = MagicMock()
            mock_post_response.raise_for_status.return_value = None
            mock_post_response.json.return_value = {"prompt_id": "test-id-123"}
            mock_post.return_value = mock_post_response

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                await client.post(
                    "/v1/images/generations",
                    json=self._make_request_payload(),
                )

        mock_save.assert_called_once()
        call_args = mock_save.call_args
        assert call_args[0][0] == image_bytes  # first positional arg is image_bytes

    @pytest.mark.asyncio
    async def test_increment5_returns_b64_json_response_when_format_is_b64_json(self, tmp_path):
        workflow_dir = tmp_path / "workflows"
        workflow_dir.mkdir()
        (workflow_dir / "flux-schnell.json").write_text('{"1": {"class_type": "KSampler", "inputs": {"seed": 0, "noise_seed": 0}}}')

        image_dir = tmp_path / "images"
        image_dir.mkdir()

        image_bytes = b"\x89PNG\r\n\x1a\nFAKE"

        with (
            patch("bridge.WORKFLOW_DIR", workflow_dir),
            patch("bridge.IMAGE_DIR", image_dir),
            patch("bridge.cleanup_old_images", return_value=[]),
            patch("bridge.wait_for_prompt_async", new_callable=AsyncMock) as mock_wait,
            patch("bridge.save_image_to_disk", return_value=(date.today().isoformat(), "20260531T142301-a3f7c2d1.png")),
            patch("requests.post") as mock_post,
            patch("bridge.get_image_data", return_value=image_bytes),
        ):
            mock_wait.return_value = {
                "outputs": {"9": {"images": [{"filename": "img.png", "subfolder": "", "type": "output"}]}}
            }
            mock_post_response = MagicMock()
            mock_post_response.raise_for_status.return_value = None
            mock_post_response.json.return_value = {"prompt_id": "test-id-123"}
            mock_post.return_value = mock_post_response

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/v1/images/generations",
                    json=self._make_request_payload(response_format="b64_json"),
                )

        assert response.status_code == 200
        body = response.json()
        assert "data" in body
        assert "created" in body
        assert "b64_json" in body["data"][0]

    @pytest.mark.asyncio
    async def test_increment5_returns_url_response_when_format_is_url(self, tmp_path):
        workflow_dir = tmp_path / "workflows"
        workflow_dir.mkdir()
        (workflow_dir / "flux-schnell.json").write_text('{"1": {"class_type": "KSampler", "inputs": {"seed": 0, "noise_seed": 0}}}')

        image_dir = tmp_path / "images"
        image_dir.mkdir()

        today_str = date.today().isoformat()
        filename = "20260531T142301-a3f7c2d1.png"

        with (
            patch("bridge.WORKFLOW_DIR", workflow_dir),
            patch("bridge.IMAGE_DIR", image_dir),
            patch("bridge.cleanup_old_images", return_value=[]),
            patch("bridge.wait_for_prompt_async", new_callable=AsyncMock) as mock_wait,
            patch("bridge.save_image_to_disk", return_value=(today_str, filename)),
            patch("requests.post") as mock_post,
            patch("bridge.get_image_data", return_value=b"\x89PNG\r\n\x1a\nFAKE"),
        ):
            mock_wait.return_value = {
                "outputs": {"9": {"images": [{"filename": "img.png", "subfolder": "", "type": "output"}]}}
            }
            mock_post_response = MagicMock()
            mock_post_response.raise_for_status.return_value = None
            mock_post_response.json.return_value = {"prompt_id": "test-id-123"}
            mock_post.return_value = mock_post_response

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/v1/images/generations",
                    json=self._make_request_payload(response_format="url"),
                )

        assert response.status_code == 200
        body = response.json()
        assert "data" in body
        assert "created" in body
        assert "url" in body["data"][0]
        assert f"/v1/images/{today_str}/{filename}" in body["data"][0]["url"]

    @pytest.mark.asyncio
    async def test_increment5_calls_wait_for_prompt_async_not_sync(self, tmp_path):
        workflow_dir = tmp_path / "workflows"
        workflow_dir.mkdir()
        (workflow_dir / "flux-schnell.json").write_text('{"1": {"class_type": "KSampler", "inputs": {"seed": 0, "noise_seed": 0}}}')

        image_dir = tmp_path / "images"
        image_dir.mkdir()

        with (
            patch("bridge.WORKFLOW_DIR", workflow_dir),
            patch("bridge.IMAGE_DIR", image_dir),
            patch("bridge.cleanup_old_images", return_value=[]),
            patch("bridge.wait_for_prompt_async", new_callable=AsyncMock) as mock_wait,
            patch("bridge.save_image_to_disk", return_value=(date.today().isoformat(), "20260531T142301-a3f7c2d1.png")),
            patch("requests.post") as mock_post,
            patch("bridge.get_image_data", return_value=b"\x89PNG\r\n\x1a\nFAKE"),
        ):
            mock_wait.return_value = {
                "outputs": {"9": {"images": [{"filename": "img.png", "subfolder": "", "type": "output"}]}}
            }
            mock_post_response = MagicMock()
            mock_post_response.raise_for_status.return_value = None
            mock_post_response.json.return_value = {"prompt_id": "test-id-123"}
            mock_post.return_value = mock_post_response

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                await client.post(
                    "/v1/images/generations",
                    json=self._make_request_payload(),
                )

        mock_wait.assert_called_once()

    @pytest.mark.asyncio
    async def test_increment5_accepts_width_and_height_overriding_size(self, tmp_path):
        workflow_dir = tmp_path / "workflows"
        workflow_dir.mkdir()
        (workflow_dir / "flux-schnell.json").write_text('{"1": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512}}}')

        image_dir = tmp_path / "images"
        image_dir.mkdir()

        with (
            patch("bridge.WORKFLOW_DIR", workflow_dir),
            patch("bridge.IMAGE_DIR", image_dir),
            patch("bridge.cleanup_old_images", return_value=[]),
            patch("bridge.wait_for_prompt_async", new_callable=AsyncMock) as mock_wait,
            patch("bridge.save_image_to_disk", return_value=(date.today().isoformat(), "20260531T142301-a3f7c2d1.png")),
            patch("requests.post") as mock_post,
            patch("bridge.get_image_data", return_value=b"\x89PNG\r\n\x1a\nFAKE"),
        ):
            mock_wait.return_value = {
                "outputs": {"9": {"images": [{"filename": "img.png", "subfolder": "", "type": "output"}]}}
            }
            mock_post_response = MagicMock()
            mock_post_response.raise_for_status.return_value = None
            mock_post_response.json.return_value = {"prompt_id": "test-id-123"}
            mock_post.return_value = mock_post_response

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/v1/images/generations",
                    json=self._make_request_payload(width=768, height=1024, size="512x512"),
                )

        # Should succeed (accept the request) even when width+height override size
        assert response.status_code == 200


# ===========================================================================
# Increment 6 — generate_image MCP tool
# ===========================================================================

def _fake_history_entry():
    return {"outputs": {"9": {"images": [{"filename": "img.png", "subfolder": "", "type": "output"}]}}}


class TestGenerateImageMcpTool:
    """Tests for the generate_image() FastMCP tool."""

    @pytest.mark.asyncio
    async def test_increment6_calls_generation_logic(self):
        """The MCP tool must delegate to bridge.run_generation."""
        today_str = date.today().isoformat()
        filename = "20260531T142301-cafebabe.png"

        with patch("bridge.run_generation", new_callable=AsyncMock) as mock_run, \
             patch("bridge.get_image_data", return_value=b"\x89PNG\r\n\x1a\nFAKE"), \
             patch("bridge.save_image_to_disk", return_value=(today_str, filename)):

            mock_run.return_value = (_fake_history_entry(), 999)

            result = await generate_image(
                prompt="a test image",
                model="flux-dev-fast",
                width=1024,
                height=1024,
            )

        mock_run.assert_called_once()
        assert hasattr(result, "url")
        assert hasattr(result, "seed")
        assert isinstance(result.url, str)
        assert isinstance(result.seed, int)

    @pytest.mark.asyncio
    async def test_increment6_returns_url_matching_expected_pattern(self):
        today_str = date.today().isoformat()
        filename = "20260531T142301-cafebabe.png"

        with patch("bridge.run_generation", new_callable=AsyncMock) as mock_run, \
             patch("bridge.get_image_data", return_value=b"\x89PNG\r\n\x1a\nFAKE"), \
             patch("bridge.save_image_to_disk", return_value=(today_str, filename)):

            mock_run.return_value = (_fake_history_entry(), 12345)

            result = await generate_image(
                prompt="a test image",
                model="flux-dev-fast",
                width=1024,
                height=1024,
            )

        url_pattern = r"^http://[^/]+/v1/images/\d{4}-\d{2}-\d{2}/\d{8}T\d{6}-[0-9a-f]{8}"
        assert re.search(url_pattern, result.url), (
            f"URL '{result.url}' does not match pattern '{url_pattern}'"
        )
        assert isinstance(result.seed, int), f"seed {result.seed!r} is not an int"

    @pytest.mark.asyncio
    async def test_increment6_seed_returned_in_result(self):
        """Seed used for generation must be included in the return value."""
        today_str = date.today().isoformat()
        filename = "20260531T142301-cafebabe.png"

        with patch("bridge.run_generation", new_callable=AsyncMock) as mock_run, \
             patch("bridge.get_image_data", return_value=b"\x89PNG\r\n\x1a\nFAKE"), \
             patch("bridge.save_image_to_disk", return_value=(today_str, filename)):

            mock_run.return_value = (_fake_history_entry(), 42)

            result = await generate_image(
                prompt="a test image",
                model="flux-dev-fast",
                width=1024,
                height=1024,
                seed=42,
            )

        assert result.seed == 42, f"Expected seed 42, got: {result.seed!r}"

    @pytest.mark.asyncio
    async def test_increment6_propagates_exceptions_as_runtime_error(self):
        """Exceptions from the underlying helper must surface as RuntimeError."""
        with patch("bridge.run_generation", new_callable=AsyncMock, side_effect=ValueError("comfyui down")):
            with pytest.raises(RuntimeError):
                await generate_image(
                    prompt="a test image",
                    model="flux-dev-fast",
                    width=1024,
                    height=1024,
                )
