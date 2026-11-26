"""Art Frame operations not (yet) provided by PySwitchbot.

Kept free of Home Assistant imports so the logic can be tested on its own and
moved into PySwitchbot later.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
import logging
import time
from typing import TYPE_CHECKING, Any, NamedTuple

from bleak.exc import BleakError
from switchbot import SwitchbotOperationError
from switchbot.devices.art_frame import COMMAND_SET_IMAGE

from .const import (
    COMMAND_DELETE_IMAGE,
    COMMAND_DOWNLOAD_IMAGE,
    COMMAND_DOWNLOAD_STATUS,
    COMMAND_START_WIFI,
    IMAGE_CURRENT,
    IMAGE_FIRST,
    IMAGE_LAST,
    IMAGE_NEWEST,
    IMAGE_OLDEST,
    MAX_LOCAL_IMAGES,
    STATUS_IDS,
    STATUS_PERCENT,
    STATUS_STATE,
)

_LOGGER = logging.getLogger(__name__)

# First bytes of a reply that mean success. The SwitchBot app accepts all
# three (isBleDataSuccess); PySwitchbot's lock documents 06 as "success, but
# the battery is low". The meaning of 0E isn't known.
SUCCESS_CODES = frozenset({0x01, 0x06, 0x0E})

POLL_INTERVAL = 1.0  # seconds between progress polls, as the app does
DOWNLOAD_TIMEOUT = 120.0  # for the whole download; the app's took about 25 s
DOWNLOAD_ATTEMPTS = 2  # start again once, only if the download never started
RETRY_DELAY = 5.0  # seconds to let the frame's Wi-Fi and Bluetooth settle
# How long the frame may report state 0 (idle) after the download command, or
# after a progress read it didn't answer, before that counts as a failure.
START_GRACE = 10.0

if TYPE_CHECKING:
    from switchbot import SwitchbotArtFrame


class ArtFrameError(Exception):
    """The frame did not do what was asked."""


class DownloadTimeoutError(ArtFrameError):
    """The frame was still downloading when we gave up (not retried)."""


class DownloadNotStartedError(ArtFrameError):
    """The download failed before the frame reported it running (retried)."""


class ImageSelectionError(ValueError):
    """The requested image does not exist on the frame."""


def resolve_image_id(
    target: str | int, image_ids: list[int], current: int | None
) -> int:
    """Turn an image ID or keyword into an ID that is on the frame."""
    if not image_ids:
        raise ImageSelectionError("The frame has no locally stored images")
    if target in (IMAGE_FIRST, IMAGE_OLDEST):
        return image_ids[0]
    if target in (IMAGE_LAST, IMAGE_NEWEST):
        return image_ids[-1]
    if target == IMAGE_CURRENT:
        if current not in image_ids:
            raise ImageSelectionError("The frame reports no image currently displayed")
        return current
    if target not in image_ids:
        raise ImageSelectionError(
            f"Image ID {target} is not on the frame (it has {image_ids})"
        )
    return int(target)


class FrameStatus(NamedTuple):
    """The frame's image list, as read by async_refresh."""

    image_ids: list[int]  # oldest first, without 0 or repeats (stored_images)
    current: int  # the image on display
    # How many entries the frame listed, which can be one more than it holds.
    # The frame counts as full by this, as its reply has room for only
    # MAX_LOCAL_IMAGES entries.
    entries: int


def stored_images(listed: Iterable[int]) -> list[int]:
    """The images in the frame's image list, without 0 or repeats.

    Some frames list one entry more than they hold: a 0, or the newest image
    a second time. 0 isn't an image ID. Keeps the frame's order.
    """
    return list(dict.fromkeys(image_id for image_id in listed if image_id))


async def async_refresh(device: SwitchbotArtFrame) -> FrameStatus:
    """Read the frame's status.

    Uses the reply directly rather than the device's cached data, which
    PySwitchbot only stores once it has seen an advertisement. The device's
    cache is still updated so its subscribers (our sensor) refresh.
    """
    try:
        info = await device.get_basic_info()
    except IndexError as err:
        # PySwitchbot reads as many IDs as the frame's count says.
        raise ArtFrameError(
            "The frame listed more images than its status reply holds"
        ) from err
    if not info:
        raise ArtFrameError("Could not read the image list from the frame")
    device._update_parsed_data(info)  # noqa: SLF001
    device._fire_callbacks()  # noqa: SLF001
    listed = list(info["all_images_index"])
    image_ids = stored_images(listed)
    if image_ids != listed:
        _LOGGER.debug("The frame listed images %s; using %s", listed, image_ids)
    return FrameStatus(image_ids, info["current_image_index"], len(listed))


async def async_delete_image(
    device: SwitchbotArtFrame, target: str | int
) -> dict[str, Any]:
    """Delete one locally stored image.

    If the image is the one on display and others exist, the frame is first
    switched to the next image, so it is never left showing a deleted image.
    """
    image_ids, current, _ = await async_refresh(device)
    image_id = resolve_image_id(target, image_ids, current)

    switched_to: int | None = None
    if image_id == current and len(image_ids) > 1:
        switched_to = image_ids[(image_ids.index(image_id) + 1) % len(image_ids)]
        await _send(
            device,
            COMMAND_SET_IMAGE.format(f"{switched_to:02X}"),
            f"switch to image {switched_to} before deleting",
        )

    await _send(
        device, COMMAND_DELETE_IMAGE.format(image_id), f"delete image {image_id}"
    )

    remaining = (await async_refresh(device)).image_ids
    if image_id in remaining:
        raise ArtFrameError(
            f"Frame accepted the delete but still lists image {image_id}"
        )

    return {
        "deleted_image_id": image_id,
        "switched_to_image_id": switched_to,
        "remaining_image_ids": remaining,
    }


async def _send(device: SwitchbotArtFrame, key: str, what: str) -> bytes:
    """Send a command; raise ArtFrameError unless the frame reports success."""
    result = await device._send_command(key)  # noqa: SLF001
    if not device._check_command_result(result, 0, SUCCESS_CODES):  # noqa: SLF001
        raise ArtFrameError(
            f"Frame refused to {what} (reply {result.hex() if result else None})"
        )
    if result[0] != 0x01:
        _LOGGER.debug("Frame replied %02x (success) to %s: %s", result[0], what, key)
    return result


async def async_download_image(
    device: SwitchbotArtFrame, image_id: int, show: bool = True
) -> dict[str, Any]:
    """Tell the frame to fetch an image from SwitchBot's cloud.

    Replays what the app does when you tap Sync: the frame downloads over its
    own Wi-Fi. The image must already be in SwitchBot's cloud, and image_id
    must be the ID the cloud assigned it: the frame asks the cloud for that
    ID, and any other fails (download state 3).

    Refused or lost progress reads are waited out. The download is started
    again (once) only if it never got going; once the frame reports it
    downloading, the command is never sent twice. Before reporting a failure
    the frame's image list is checked, in case the image arrived anyway.
    """
    image_ids, _, entries = await async_refresh(device)
    if entries >= MAX_LOCAL_IMAGES:
        raise ImageSelectionError(
            f"The frame is full: it already lists {MAX_LOCAL_IMAGES} images; "
            "delete one first"
        )
    if image_id in image_ids:
        raise ImageSelectionError(f"Image ID {image_id} is already on the frame")
    elif not 1 <= image_id <= 255:
        raise ImageSelectionError("Image ID must be between 1 and 255")

    deadline = time.monotonic() + DOWNLOAD_TIMEOUT
    progress: list[int] = []
    resume = False  # the frame is already downloading: just poll
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        try:
            start_reply = None if resume else await _async_start(device, image_id)
            progress = await _async_poll(
                device, image_id, deadline, started=resume, start_reply=start_reply
            )
            break
        except DownloadNotStartedError:
            retry = (
                attempt < DOWNLOAD_ATTEMPTS
                and time.monotonic() + RETRY_DELAY < deadline
            )
            if not retry:
                if await _async_image_arrived(device, image_id):
                    break
                raise
        except ArtFrameError:
            # Failed or timed out after the download started: never restart
            # it, as the frame may still be busy with it.
            if await _async_image_arrived(device, image_id):
                break
            raise
        await asyncio.sleep(RETRY_DELAY)
        # The frame may have finished after all, or still be downloading
        # (a lost reply to the download command).
        if await _async_image_arrived(device, image_id):
            break
        resume = await _async_downloading(device)

    if show:
        await _send(device, COMMAND_SET_IMAGE.format(f"{image_id:02X}"), "show it")

    remaining, current, _ = await async_refresh(device)
    return {
        "image_id": image_id,
        "image_ids": remaining,
        "current_image_id": current,
        "progress": progress,
    }


async def _async_start(device: SwitchbotArtFrame, image_id: int) -> bytes:
    """Send Wi-Fi start and the download command; return the latter's reply."""
    try:
        await _send(device, COMMAND_START_WIFI, "connect to Wi-Fi")
        return await _send(
            device, COMMAND_DOWNLOAD_IMAGE.format(image_id), "start the download"
        )
    except (ArtFrameError, SwitchbotOperationError, BleakError) as err:
        raise DownloadNotStartedError(str(err) or type(err).__name__) from err


async def _async_poll(
    device: SwitchbotArtFrame,
    image_id: int,
    deadline: float,
    started: bool,
    start_reply: bytes | None,
) -> list[int]:
    """Poll the download until it finishes; return the progress percentages.

    Raises DownloadNotStartedError if it failed before the frame reported it
    downloading (safe to start again), ArtFrameError if it failed after, and
    DownloadTimeoutError at the deadline.
    """
    progress: list[int] = []
    status: bytes | None = None
    # State 0 (idle) is expected for a few seconds after the download command
    # and after a read the frame didn't answer.
    quiet_since = time.monotonic()

    def detail() -> str:
        last = status.hex() if status else None
        start = start_reply.hex() if start_reply else None
        return f"last reply {last}, start reply {start}"

    while True:
        await asyncio.sleep(POLL_INTERVAL)
        reply = await _async_read_progress(device)
        if reply is None:
            quiet_since = time.monotonic()
        else:
            status = reply
            state = status[STATUS_STATE]
            if state == 2 and image_id in status[STATUS_IDS]:
                return progress
            if not progress or progress[-1] != status[STATUS_PERCENT]:
                progress.append(status[STATUS_PERCENT])
            if state == 1:
                started = True
            elif state != 2 and (
                state != 0 or time.monotonic() - quiet_since > START_GRACE
            ):
                error = ArtFrameError if started else DownloadNotStartedError
                raise error(f"Download failed (state {state}, {detail()})")
        if time.monotonic() > deadline:
            raise DownloadTimeoutError(f"Download did not finish ({detail()})")


async def _async_read_progress(device: SwitchbotArtFrame) -> bytes | None:
    """Read the download status (after the result byte).

    None if the frame refused or didn't answer, which it sometimes does while
    downloading.
    """
    try:
        reply = await _send(device, COMMAND_DOWNLOAD_STATUS, "report progress")
    except (ArtFrameError, SwitchbotOperationError, BleakError) as err:
        _LOGGER.debug("No download progress from the frame: %s", err)
        return None
    status = reply[1:]
    if len(status) <= STATUS_PERCENT:
        _LOGGER.debug("Unexpected progress reply %s", status.hex())
        return None
    return status


async def _async_downloading(device: SwitchbotArtFrame) -> bool:
    """Whether the frame reports a download in progress."""
    status = await _async_read_progress(device)
    return status is not None and status[STATUS_STATE] == 1


async def _async_image_arrived(device: SwitchbotArtFrame, image_id: int) -> bool:
    """Whether the image is on the frame (False if the list can't be read)."""
    try:
        image_ids = (await async_refresh(device)).image_ids
    except (ArtFrameError, SwitchbotOperationError, BleakError) as err:
        _LOGGER.debug("Couldn't read the image list: %s", err)
        return False
    return image_id in image_ids
