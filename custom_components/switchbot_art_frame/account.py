"""Client for the parts of SwitchBot's app API that the Art Frame album uses.

This is SwitchBot's private, undocumented API (the one the phone app and
PySwitchbot use), not the public Cloud API. Endpoints and payloads were found
in the app's Art Frame module; they can change without notice.
"""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout

_LOGGER = logging.getLogger(__name__)

API = "api.switchbot.net"
# The SwitchBot app's client ID, as used by PySwitchbot.
CLIENT_ID = "5nnwmhmsa9xxskm14hd85lm9bm"
OK = 100

LOGIN_PATH = "account/api/v1/user/login"
USERINFO_PATH = "account/api/v1/user/userinfo"
DEVICES_PATH = "wonder/device/v3/getdevice"
IMAGES_LIST_PATH = "device/artframe/api/v1/images/list"
IMAGES_DELETE_PATH = "device/artframe/api/v1/images/delete"
SYNC_DELETED_PATH = "productbiz/v1/slideshow/syncDeletedImages"

# Image record "status": 0 = in the cloud, not yet on the frame; 1 = synced.
STATUS_PENDING = 0
STATUS_SYNCED = 1


class AccountError(Exception):
    """The SwitchBot account API did not do what was asked."""


class AuthError(AccountError):
    """Login failed or the session was rejected."""


class SwitchBotAccount:
    """A logged-in session for one Art Frame."""

    def __init__(
        self, session: ClientSession, email: str, password: str, mac: str
    ) -> None:
        self._session = session
        self._email = email
        self._password = password
        self.mac = mac.replace(":", "").upper()
        self._token: str | None = None
        self._region: str | None = None
        self.group_id: str | None = None

    async def _post(
        self, host: str, path: str, data: dict[str, Any], auth: bool = True
    ) -> Any:
        headers = {"authorization": self._token} if auth and self._token else {}
        try:
            async with self._session.post(
                f"https://{host}.{API}/{path}",
                json=data,
                headers=headers,
                timeout=ClientTimeout(total=20),
            ) as resp:
                if resp.status in (401, 403):
                    raise AuthError(f"{path}: HTTP {resp.status}")
                if resp.status >= 400:
                    raise AccountError(f"{path}: HTTP {resp.status}")
                body = await resp.json(content_type=None)
        except (ClientError, TimeoutError) as err:
            raise AccountError(f"{path}: {err!r}") from err
        if not isinstance(body, dict):
            raise AccountError(f"{path}: unexpected reply {body!r}")
        code = body.get("statusCode", body.get("resultCode"))
        if code != OK:
            raise AccountError(f"{path}: {body.get('message')} (code {code})")
        return body["body"] if "body" in body else body.get("data")

    async def async_login(self) -> None:
        """Log in and find the frame's region and group (home)."""
        self._token = None
        try:
            result = await self._post(
                "account",
                LOGIN_PATH,
                {
                    "clientId": CLIENT_ID,
                    "username": self._email,
                    "password": self._password,
                    "grantType": "password",
                    "verifyCode": "",
                },
                auth=False,
            )
        except AccountError as err:
            raise AuthError(f"SwitchBot login failed: {err}") from err
        token = (result or {}).get("access_token")
        if not token:
            raise AuthError("SwitchBot login returned no access token")
        self._token = token

        info = await self._post("account", USERINFO_PATH, {})
        self._region = (info or {}).get("botRegion") or "us"

        devices = await self._post(
            f"wonderlabs.{self._region}", DEVICES_PATH, {"required_type": "All"}
        )
        for item in (devices or {}).get("Items") or []:
            if str(item.get("device_mac", "")).upper() == self.mac:
                self.group_id = item.get("groupID")
                break
        else:
            raise AccountError(f"Frame {self.mac} is not in this SwitchBot account")
        if not self.group_id:
            raise AccountError(f"No group (home) ID for frame {self.mac}")

    async def _call(self, path: str, data: dict[str, Any]) -> Any:
        """Call a frame endpoint, logging in (again) if needed."""
        if self._token is None:
            await self.async_login()
        body = {"deviceID": self.mac, "groupID": self.group_id, **data}
        try:
            return await self._post(f"wonderlabs.{self._region}", path, body)
        except AuthError:
            _LOGGER.debug("SwitchBot session rejected; logging in again")
            await self.async_login()
            body["groupID"] = self.group_id
            return await self._post(f"wonderlabs.{self._region}", path, body)

    async def async_list_images(self) -> list[dict[str, Any]]:
        """Images the cloud holds for this frame, newest first."""
        result = await self._call(IMAGES_LIST_PATH, {})
        images = (result or {}).get("images") or []
        return sorted(images, key=lambda img: img.get("id", 0), reverse=True)

    async def async_delete_images(self, image_ids: list[int]) -> None:
        """Remove images from the cloud album, as the app does after a delete."""
        if not image_ids:
            return
        await self._call(
            IMAGES_DELETE_PATH, {"imageIndexList": image_ids, "deleteAll": False}
        )
        try:
            await self._call(
                SYNC_DELETED_PATH, {"imageIndexes": image_ids, "deleteAll": False}
            )
        except AccountError as err:
            # Only affects slideshow playlists; the album delete already worked.
            _LOGGER.warning("Removing deleted images from slideshows failed: %s", err)
