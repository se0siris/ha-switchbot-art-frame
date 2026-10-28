"""Art Frame operations not (yet) provided by PySwitchbot.

Kept free of Home Assistant imports so the logic can be tested on its own and
moved into PySwitchbot later.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from switchbot.devices.art_frame import COMMAND_SET_IMAGE

from .const import COMMAND_DELETE_IMAGE, IMAGE_CURRENT, IMAGE_FIRST, IMAGE_LAST

if TYPE_CHECKING:
    from switchbot import SwitchbotArtFrame


class ArtFrameError(Exception):
    """The frame did not do what was asked."""


class ImageSelectionError(ValueError):
    """The requested image does not exist on the frame."""


def resolve_image_id(
    target: str | int, image_ids: list[int], current: int | None
) -> int:
    """Turn an image ID or keyword into an ID that is on the frame."""
    if not image_ids:
        raise ImageSelectionError("The frame has no locally stored images")
    if target == IMAGE_FIRST:
        return image_ids[0]
    if target == IMAGE_LAST:
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


async def async_refresh(device: SwitchbotArtFrame) -> tuple[list[int], int]:
    """Read the frame's status; return (image IDs, current image ID).

    Uses the reply directly rather than the device's cached data, which
    PySwitchbot only stores once it has seen an advertisement. The device's
    cache is still updated so its subscribers (our sensor) refresh.
    """
    info = await device.get_basic_info()
    if not info:
        raise ArtFrameError("Could not read the image list from the frame")
    device._update_parsed_data(info)  # noqa: SLF001
    device._fire_callbacks()  # noqa: SLF001
    return list(info["all_images_index"]), info["current_image_index"]


async def async_delete_image(
    device: SwitchbotArtFrame, target: str | int
) -> dict[str, Any]:
    """Delete one locally stored image.

    If the image is the one on display and others exist, the frame is first
    switched to the next image, so it is never left showing a deleted image.
    """
    image_ids, current = await async_refresh(device)
    image_id = resolve_image_id(target, image_ids, current)

    switched_to: int | None = None
    if image_id == current and len(image_ids) > 1:
        switched_to = image_ids[(image_ids.index(image_id) + 1) % len(image_ids)]
        result = await device._send_command(  # noqa: SLF001
            COMMAND_SET_IMAGE.format(f"{switched_to:02X}")
        )
        if not device._check_command_result(result, 0, {1}):  # noqa: SLF001
            raise ArtFrameError(
                f"Frame refused to switch to image {switched_to} before deleting"
            )

    result = await device._send_command(  # noqa: SLF001
        COMMAND_DELETE_IMAGE.format(image_id)
    )
    if not device._check_command_result(result, 0, {1}):  # noqa: SLF001
        raise ArtFrameError(f"Frame refused to delete image {image_id}")

    remaining, _ = await async_refresh(device)
    if image_id in remaining:
        raise ArtFrameError(
            f"Frame accepted the delete but still lists image {image_id}"
        )

    return {
        "deleted_image_id": image_id,
        "switched_to_image_id": switched_to,
        "remaining_image_ids": remaining,
    }
