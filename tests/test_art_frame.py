"""Tests for the frame-level logic."""

import pytest

from custom_components.switchbot_art_frame.art_frame import (
    ArtFrameError,
    ImageSelectionError,
    async_delete_image,
    resolve_image_id,
)


@pytest.mark.parametrize(
    ("target", "expected"),
    [("first", 0x10), ("last", 0x19), ("current", 0x19), (0x16, 0x16)],
)
def test_resolve(target, expected) -> None:
    ids = [0x10, 0x16, 0x19]
    assert resolve_image_id(target, ids, 0x19) == expected


@pytest.mark.parametrize(
    ("target", "ids", "current"),
    [(0x99, [0x10], 0x10), ("current", [0x10], 0), ("first", [], 0)],
)
def test_resolve_errors(target, ids, current) -> None:
    with pytest.raises(ImageSelectionError):
        resolve_image_id(target, ids, current)


async def test_delete_not_displayed(frame, art_frame_device) -> None:
    result = await async_delete_image(art_frame_device, 0x10)
    assert result["deleted_image_id"] == 0x10
    assert result["switched_to_image_id"] is None
    assert 0x10 not in result["remaining_image_ids"]
    assert frame.current == 0x19
    assert "570F7A010210" in frame.sent


async def test_delete_displayed_switches_first(frame, art_frame_device) -> None:
    """Deleting the image on screen moves to the next one (wrapping) first."""
    result = await async_delete_image(art_frame_device, "current")
    assert result["deleted_image_id"] == 0x19
    assert result["switched_to_image_id"] == 0x10
    assert frame.current == 0x10
    switch = frame.sent.index("570F7A0210")
    delete = frame.sent.index("570F7A010219")
    assert switch < delete


async def test_delete_only_image(frame, art_frame_device) -> None:
    frame.image_ids = [0x19]
    result = await async_delete_image(art_frame_device, "current")
    assert result["switched_to_image_id"] is None
    assert result["remaining_image_ids"] == []


async def test_delete_refused(frame, art_frame_device) -> None:
    frame.refuse = {"570F7A0102"}
    with pytest.raises(ArtFrameError):
        await async_delete_image(art_frame_device, 0x10)
    assert 0x10 in frame.image_ids
