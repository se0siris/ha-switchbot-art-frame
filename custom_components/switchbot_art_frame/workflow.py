"""Putting a new image on the frame without the phone app.

1. Tidy up: remove cloud album entries for images no longer on the frame, and
   if the frame is full, delete its oldest image (frame and cloud).
2. Upload the image to SwitchBot's cloud (public Cloud API).
3. Find the ID the cloud gave it (private album API).
4. Tell the frame over Bluetooth to download that ID; it fetches the image
   over its own Wi-Fi.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import time
from typing import TYPE_CHECKING, Any

from .account import STATUS_SYNCED, SwitchBotAccount
from .art_frame import (
    ArtFrameError,
    ImageSelectionError,
    async_delete_image,
    async_download_image,
    async_refresh,
)
from .const import IMAGE_OLDEST, MAX_LOCAL_IMAGES

if TYPE_CHECKING:
    from switchbot import SwitchbotArtFrame

LIST_POLL_INTERVAL = 2.0
LIST_TIMEOUT = 60.0


async def async_remove_cloud_leftovers(
    account: SwitchBotAccount, frame_ids: list[int]
) -> list[int]:
    """Delete cloud entries for images that were synced but are gone from the frame.

    Pending uploads (not yet synced) are left alone.
    """
    leftovers = [
        img["imageIndex"]
        for img in await account.async_list_images()
        if img.get("status") == STATUS_SYNCED and img.get("imageIndex") not in frame_ids
    ]
    await account.async_delete_images(leftovers)
    return leftovers


async def async_show_image_from_url(
    device: SwitchbotArtFrame,
    account: SwitchBotAccount,
    upload: Callable[[str], Awaitable[Any]],
    image_url: str,
    make_room: bool = True,
) -> dict[str, Any]:
    """Upload an image and put it on the frame. See the module docstring."""
    frame_ids, _ = await async_refresh(device)
    removed = await async_remove_cloud_leftovers(account, frame_ids)

    deleted: int | None = None
    if len(frame_ids) >= MAX_LOCAL_IMAGES:
        if not make_room:
            raise ImageSelectionError(
                f"The frame already holds {MAX_LOCAL_IMAGES} images; "
                "delete one first or allow make_room"
            )
        deleted = (await async_delete_image(device, IMAGE_OLDEST))["deleted_image_id"]
        await account.async_delete_images([deleted])

    before = {img.get("id") for img in await account.async_list_images()}
    await upload(image_url)

    new: dict[str, Any] | None = None
    deadline = time.monotonic() + LIST_TIMEOUT
    while new is None:
        await asyncio.sleep(LIST_POLL_INTERVAL)
        added = [
            img
            for img in await account.async_list_images()
            if img.get("id") not in before
        ]
        if added:
            new = added[0]  # list is newest first
        elif time.monotonic() > deadline:
            raise ArtFrameError(
                "The upload was accepted but never appeared in the frame's cloud album"
            )

    result = await async_download_image(device, int(new["imageIndex"]), show=True)
    return {
        **result,
        "deleted_image_id": deleted,
        "removed_cloud_leftovers": removed,
    }
