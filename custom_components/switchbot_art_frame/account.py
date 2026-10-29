"""Client for the parts of SwitchBot's app API that the Art Frame album uses.

This is SwitchBot's private, undocumented API (the one the phone app and
PySwitchbot use), not the public Cloud API. Endpoints and payloads were found
in the app's Art Frame module; they can change without notice.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
import logging
import time
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout

_LOGGER = logging.getLogger(__name__)

API = "api.switchbot.net"
# The SwitchBot app's client ID, as used by PySwitchbot.
CLIENT_ID = "5nnwmhmsa9xxskm14hd85lm9bm"
OK = 100

# The password login gives an access token (2 hours) and a refresh token
# (30 days). Refreshing only works on the OAuth token endpoint, as a form post.
LOGIN_PATH = "account/api/v1/user/login"
TOKEN_URL = f"https://account.{API}/merchant/v1/oauth/token"
# Refresh this long before the access token runs out.
REFRESH_MARGIN = 300

# Keys of the stored token data.
ACCESS_TOKEN = "access_token"
REFRESH_TOKEN = "refresh_token"
EXPIRES_AT = "expires_at"
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
    """A session for one Art Frame, kept going with a refresh token.

    The password is only used by `async_login`; afterwards the session lives
    on its tokens, which `on_tokens` is given whenever they change so they can
    be stored. Once the refresh token is rejected, calls raise `AuthError`
    and the user has to log in again.
    """

    def __init__(
        self,
        session: ClientSession,
        mac: str,
        tokens: Mapping[str, Any] | None = None,
        on_tokens: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._session = session
        self.mac = mac.replace(":", "").upper()
        self._tokens: dict[str, Any] = dict(tokens or {})
        self._on_tokens = on_tokens
        self._refresh_lock = asyncio.Lock()
        self._region: str | None = None
        self.group_id: str | None = None

    @property
    def tokens(self) -> dict[str, Any]:
        """The token data to store."""
        return dict(self._tokens)

    async def _post(
        self, host: str, path: str, data: dict[str, Any], auth: bool = True
    ) -> Any:
        token = self._tokens.get(ACCESS_TOKEN)
        headers = {"authorization": token} if auth and token else {}
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

    def _set_tokens(self, reply: Any) -> None:
        if not isinstance(reply, dict) or not reply.get(ACCESS_TOKEN):
            raise AuthError("SwitchBot returned no access token")
        self._tokens = {
            ACCESS_TOKEN: reply[ACCESS_TOKEN],
            # Not rotated on refresh, but take a new one if it comes.
            REFRESH_TOKEN: reply.get(REFRESH_TOKEN) or self._tokens.get(REFRESH_TOKEN),
            EXPIRES_AT: time.time() + int(reply.get("expires_in") or 0),
        }
        if self._on_tokens is not None:
            self._on_tokens(self.tokens)

    async def async_login(self, email: str, password: str) -> None:
        """Log in with a password and find the frame's region and group (home)."""
        self._tokens = {}
        try:
            result = await self._post(
                "account",
                LOGIN_PATH,
                {
                    "clientId": CLIENT_ID,
                    "username": email,
                    "password": password,
                    "grantType": "password",
                    "verifyCode": "",
                },
                auth=False,
            )
        except AccountError as err:
            raise AuthError(f"SwitchBot login failed: {err}") from err
        self._set_tokens(result)
        await self._async_find_frame()

    async def _async_refresh(self, stale_token: str | None) -> None:
        """Get a new access token, unless another call already has."""
        async with self._refresh_lock:
            if self._tokens.get(ACCESS_TOKEN) != stale_token:
                return
            refresh_token = self._tokens.get(REFRESH_TOKEN)
            if not refresh_token:
                raise AuthError("No SwitchBot refresh token; log in again")
            try:
                async with self._session.post(
                    TOKEN_URL,
                    data={
                        "client_id": CLIENT_ID,
                        "grant_type": "refresh_token",
                        "refresh_token": refresh_token,
                    },
                    timeout=ClientTimeout(total=20),
                ) as resp:
                    status = resp.status
                    body = await resp.json(content_type=None)
            except (ClientError, TimeoutError, ValueError) as err:
                raise AccountError(
                    f"Refreshing the SwitchBot session: {err!r}"
                ) from err
            if status >= 500 or status == 429:
                raise AccountError(f"Refreshing the SwitchBot session: HTTP {status}")
            if not isinstance(body, dict) or not body.get(ACCESS_TOKEN):
                # Most likely the refresh token has expired or been revoked.
                raise AuthError(
                    f"SwitchBot refused to renew the session (HTTP {status})"
                )
            _LOGGER.debug("Renewed the SwitchBot session")
            self._set_tokens(body)

    async def _async_find_frame(self) -> None:
        """Find the account's region and the frame's group (home)."""
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

    async def _async_post_frame(self, path: str, data: dict[str, Any]) -> Any:
        if self.group_id is None:
            await self._async_find_frame()
        body = {"deviceID": self.mac, "groupID": self.group_id, **data}
        return await self._post(f"wonderlabs.{self._region}", path, body)

    async def _call(self, path: str, data: dict[str, Any]) -> Any:
        """Call a frame endpoint, renewing the session if needed."""
        token = self._tokens.get(ACCESS_TOKEN)
        if not token or time.time() > self._tokens.get(EXPIRES_AT, 0) - REFRESH_MARGIN:
            await self._async_refresh(token)
        try:
            return await self._async_post_frame(path, data)
        except AuthError:
            _LOGGER.debug("SwitchBot session rejected; renewing it")
        await self._async_refresh(self._tokens.get(ACCESS_TOKEN))
        return await self._async_post_frame(path, data)

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
