"""An upload endpoint for the dashboard card.

The card posts the image file here instead of calling show_image with the
image as base64, so the image doesn't travel on the event bus as a
call_service event (which the recorder also refuses to store, logging a
warning each time).
"""

from __future__ import annotations

from http import HTTPStatus
import logging

from aiohttp import BodyPartReader, web

from homeassistant.auth.permissions.const import POLICY_CONTROL
from homeassistant.components.http import KEY_HASS, KEY_HASS_USER, HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    HomeAssistantError,
    ServiceValidationError,
    Unauthorized,
)
from homeassistant.helpers import entity_platform

from .const import DOMAIN
from .sensor import MAX_BASE64_CHARS, ArtFrameLocalImagesSensor, to_data_uri

_LOGGER = logging.getLogger(__name__)

UPLOAD_URL = f"/api/{DOMAIN}/show_image"
# The largest file that fits SwitchBot's upload as a base64 data URI (a third
# larger, plus the "data:image/jpeg;base64," prefix). The card stays under it.
MAX_FILE_BYTES = (MAX_BASE64_CHARS - 23) * 3 // 4


class ShowImageView(HomeAssistantView):
    """Show an uploaded image on the frame: show_image with a file.

    Takes a multipart form with `entity_id` (the Local images sensor) and
    `file` (a PNG or JPEG), and returns show_image's response as JSON. Any
    logged-in user who may control the sensor can use it.
    """

    url = UPLOAD_URL
    name = f"api:{DOMAIN}:show_image"

    async def post(self, request: web.Request) -> web.Response:
        """Read the form, then run show_image as the action would."""
        hass = request.app[KEY_HASS]
        try:
            entity_id, raw = await _async_read_form(request)
        except ValueError as err:
            return self.json_message(str(err), HTTPStatus.BAD_REQUEST)

        if not request[KEY_HASS_USER].permissions.check_entity(
            entity_id, POLICY_CONTROL
        ):
            raise Unauthorized(entity_id=entity_id, permission=POLICY_CONTROL)
        sensor = _find_sensor(hass, entity_id)
        if sensor is None:
            return self.json_message(
                f"{entity_id} is not an Art Frame Local images sensor",
                HTTPStatus.NOT_FOUND,
            )

        try:
            parameter = {"imageBase64": to_data_uri(raw)}
            # Under the entity's PARALLEL_UPDATES semaphore, as an action
            # would be, so this never overlaps another action on the frame.
            response = await sensor.async_request_call(
                sensor.async_show_upload(parameter)
            )
        except ServiceValidationError as err:
            return self.json_message(str(err), HTTPStatus.BAD_REQUEST)
        except HomeAssistantError as err:
            # The card shows the error, but nothing else would record it.
            _LOGGER.warning("Showing an image uploaded from the card failed: %s", err)
            return self.json_message(str(err), HTTPStatus.INTERNAL_SERVER_ERROR)
        return self.json(response)


async def _async_read_form(request: web.Request) -> tuple[str, bytes]:
    """Return the form's entity ID and file; raise ValueError if it's wrong."""
    if not request.content_type.startswith("multipart/"):
        raise ValueError("Send a multipart form with entity_id and file")
    entity_id: str | None = None
    raw: bytes | None = None
    reader = await request.multipart()
    while (part := await reader.next()) is not None:
        if not isinstance(part, BodyPartReader):
            continue
        if part.name == "entity_id":
            entity_id = (await part.text()).strip()
        elif part.name == "file":
            raw = await _async_read_limited(part)
    if not entity_id or raw is None:
        raise ValueError("Send a multipart form with entity_id and file")
    return entity_id, raw


async def _async_read_limited(part: BodyPartReader) -> bytes:
    """Read a file part, stopping as soon as it's too large to upload."""
    data = bytearray()
    while chunk := await part.read_chunk():
        data += chunk
        if len(data) > MAX_FILE_BYTES:
            raise ValueError(
                "The image is too large for SwitchBot's upload (keep it under "
                f"about {MAX_FILE_BYTES // 1000} KB)"
            )
    return bytes(data)


def _find_sensor(
    hass: HomeAssistant, entity_id: str
) -> ArtFrameLocalImagesSensor | None:
    """This integration's Local images sensor with that entity ID, if any."""
    for platform in entity_platform.async_get_platforms(hass, DOMAIN):
        entity = platform.entities.get(entity_id)
        if isinstance(entity, ArtFrameLocalImagesSensor):
            return entity
    return None
