"""Tests for the SwitchBot account client, with replies shaped like SwitchBot's."""

import time

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.switchbot_art_frame.account import (
    TOKEN_URL,
    AccountError,
    AuthError,
    SwitchBotAccount,
)

from .conftest import ADDRESS

ACCOUNT = "https://account.api.switchbot.net/account/api/v1/user"
WONDER = "https://wonderlabs.eu.api.switchbot.net"
GROUP = "G01-0000000000000-0000"

IMAGES = [
    {"id": 1002, "status": 1, "imageIndex": 16},
    {"id": 1003, "status": 0, "imageIndex": 26},
    {"id": 1001, "status": 1, "imageIndex": 17},
]


def token_reply(access: str, refresh: str = "refresh1") -> dict:
    return {
        "access_token": access,
        "refresh_token": refresh,
        "expires_in": 7200,
        "refresh_expires_in": 2592000,
        "token_type": "Bearer",
    }


def mock_login(aioclient_mock, token="tok1"):
    aioclient_mock.post(
        f"{ACCOUNT}/login", json={"statusCode": 100, "body": token_reply(token)}
    )
    mock_frame_lookup(aioclient_mock)


def mock_frame_lookup(aioclient_mock):
    aioclient_mock.post(
        f"{ACCOUNT}/userinfo", json={"statusCode": 100, "body": {"botRegion": "eu"}}
    )
    aioclient_mock.post(
        f"{WONDER}/wonder/device/v3/getdevice",
        json={
            "statusCode": 100,
            "body": {
                "Items": [
                    {"device_mac": "112233445566", "groupID": "other"},
                    {"device_mac": "AABBCCDDEEFF", "groupID": GROUP},
                ]
            },
        },
    )


def account(
    hass: HomeAssistant, expires_in: float = 7200, saved: list | None = None
) -> SwitchBotAccount:
    """An account with stored tokens, as after a restart."""
    tokens = {
        "access_token": "tok1",
        "refresh_token": "refresh1",
        "expires_at": time.time() + expires_in,
    }
    on_tokens = saved.append if saved is not None else None
    return SwitchBotAccount(async_get_clientsession(hass), ADDRESS, tokens, on_tokens)


async def test_login_finds_group(hass: HomeAssistant, aioclient_mock) -> None:
    mock_login(aioclient_mock)
    saved = []
    acc = SwitchBotAccount(
        async_get_clientsession(hass), ADDRESS, on_tokens=saved.append
    )
    await acc.async_login("a@b.c", "pw")
    assert acc.group_id == GROUP
    login_body = aioclient_mock.mock_calls[0][2]
    assert login_body["username"] == "a@b.c"
    assert login_body["grantType"] == "password"
    # Later calls carry the token.
    assert aioclient_mock.mock_calls[1][3]["authorization"] == "tok1"
    # The tokens are kept (to be stored); the password isn't.
    assert acc.tokens["access_token"] == "tok1"
    assert acc.tokens["refresh_token"] == "refresh1"
    assert acc.tokens["expires_at"] == pytest.approx(time.time() + 7200, abs=5)
    assert saved == [acc.tokens]
    assert "pw" not in repr(vars(acc))


async def test_login_rejected(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.post(
        f"{ACCOUNT}/login", json={"statusCode": 190, "message": "wrong password"}
    )
    with pytest.raises(AuthError):
        await SwitchBotAccount(async_get_clientsession(hass), ADDRESS).async_login(
            "a@b.c", "pw"
        )


async def test_frame_not_in_account(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.post(
        f"{ACCOUNT}/login", json={"statusCode": 100, "body": {"access_token": "t"}}
    )
    aioclient_mock.post(
        f"{ACCOUNT}/userinfo", json={"statusCode": 100, "body": {"botRegion": "eu"}}
    )
    aioclient_mock.post(
        f"{WONDER}/wonder/device/v3/getdevice",
        json={"statusCode": 100, "body": {"Items": []}},
    )
    with pytest.raises(AccountError, match="not in this SwitchBot account"):
        await SwitchBotAccount(async_get_clientsession(hass), ADDRESS).async_login(
            "a@b.c", "pw"
        )


async def test_list_images_newest_first(hass: HomeAssistant, aioclient_mock) -> None:
    mock_frame_lookup(aioclient_mock)
    aioclient_mock.post(
        f"{WONDER}/device/artframe/api/v1/images/list",
        json={"resultCode": 100, "data": {"images": IMAGES}, "message": ""},
    )
    images = await account(hass).async_list_images()
    assert [i["id"] for i in images] == [1003, 1002, 1001]
    body = aioclient_mock.mock_calls[-1][2]
    assert body == {"deviceID": "AABBCCDDEEFF", "groupID": GROUP}


async def test_list_images_error(hass: HomeAssistant, aioclient_mock) -> None:
    mock_frame_lookup(aioclient_mock)
    aioclient_mock.post(
        f"{WONDER}/device/artframe/api/v1/images/list",
        json={"resultCode": 191, "data": None, "message": "not in this group"},
    )
    with pytest.raises(AccountError, match="not in this group"):
        await account(hass).async_list_images()


async def test_delete_images(hass: HomeAssistant, aioclient_mock) -> None:
    mock_frame_lookup(aioclient_mock)
    aioclient_mock.post(
        f"{WONDER}/device/artframe/api/v1/images/delete",
        json={"resultCode": 100, "data": None},
    )
    aioclient_mock.post(
        f"{WONDER}/productbiz/v1/slideshow/syncDeletedImages",
        json={"resultCode": 100, "data": None},
    )
    await account(hass).async_delete_images([16, 17])
    delete_body = aioclient_mock.mock_calls[-2][2]
    sync_body = aioclient_mock.mock_calls[-1][2]
    assert delete_body["imageIndexList"] == [16, 17]
    assert delete_body["deleteAll"] is False
    assert sync_body["imageIndexes"] == [16, 17]


async def test_delete_nothing_makes_no_calls(
    hass: HomeAssistant, aioclient_mock
) -> None:
    await account(hass).async_delete_images([])
    assert aioclient_mock.call_count == 0


async def test_slideshow_sync_failure_is_not_fatal(
    hass: HomeAssistant, aioclient_mock
) -> None:
    mock_frame_lookup(aioclient_mock)
    aioclient_mock.post(
        f"{WONDER}/device/artframe/api/v1/images/delete",
        json={"resultCode": 100, "data": None},
    )
    aioclient_mock.post(
        f"{WONDER}/productbiz/v1/slideshow/syncDeletedImages", status=500
    )
    await account(hass).async_delete_images([16])


def mock_list(aioclient_mock, **kwargs):
    aioclient_mock.post(
        f"{WONDER}/device/artframe/api/v1/images/list",
        **(kwargs or {"json": {"resultCode": 100, "data": {"images": IMAGES}}}),
    )


async def test_refresh_when_expired(hass: HomeAssistant, aioclient_mock) -> None:
    mock_frame_lookup(aioclient_mock)
    mock_list(aioclient_mock)
    aioclient_mock.post(TOKEN_URL, json=token_reply("tok2"))
    saved = []
    acc = account(hass, expires_in=60, saved=saved)
    await acc.async_list_images()
    _, url, data, _ = aioclient_mock.mock_calls[0]
    assert str(url) == TOKEN_URL
    assert data == {
        "client_id": "5nnwmhmsa9xxskm14hd85lm9bm",
        "grant_type": "refresh_token",
        "refresh_token": "refresh1",
    }
    # Every later call uses the new token, and it is handed over for storing.
    assert all(c[3]["authorization"] == "tok2" for c in aioclient_mock.mock_calls[1:])
    assert [t["access_token"] for t in saved] == ["tok2"]
    assert saved[0]["refresh_token"] == "refresh1"


async def test_no_refresh_while_token_is_fresh(
    hass: HomeAssistant, aioclient_mock
) -> None:
    mock_frame_lookup(aioclient_mock)
    mock_list(aioclient_mock)
    await account(hass).async_list_images()
    assert TOKEN_URL not in [str(c[1]) for c in aioclient_mock.mock_calls]


async def test_refresh_when_session_rejected(
    hass: HomeAssistant, aioclient_mock
) -> None:
    mock_frame_lookup(aioclient_mock)
    mock_list(aioclient_mock, status=401)
    aioclient_mock.post(TOKEN_URL, json=token_reply("tok2"))
    with pytest.raises(AuthError):
        await account(hass).async_list_images()
    # The rejected list, a refresh, then the retried list (still rejected).
    paths = [str(c[1]) for c in aioclient_mock.mock_calls[2:]]
    assert paths[0].endswith("images/list")
    assert paths[1] == TOKEN_URL
    assert paths[2].endswith("images/list")
    assert len(paths) == 3
    assert aioclient_mock.mock_calls[-1][3]["authorization"] == "tok2"


async def test_refresh_token_rejected(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.post(TOKEN_URL, status=400, json={"error": "invalid_grant"})
    with pytest.raises(AuthError):
        await account(hass, expires_in=0).async_list_images()
    # Not retried: only a new login can help.
    assert aioclient_mock.call_count == 1


async def test_refresh_server_error_is_not_auth_error(
    hass: HomeAssistant, aioclient_mock
) -> None:
    aioclient_mock.post(TOKEN_URL, status=503)
    with pytest.raises(AccountError) as err:
        await account(hass, expires_in=0).async_list_images()
    assert not isinstance(err.value, AuthError)


async def test_no_tokens_needs_login(hass: HomeAssistant, aioclient_mock) -> None:
    acc = SwitchBotAccount(async_get_clientsession(hass), ADDRESS)
    with pytest.raises(AuthError):
        await acc.async_list_images()
    assert aioclient_mock.call_count == 0
