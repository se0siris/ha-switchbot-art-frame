"""Tests for the SwitchBot account client, with replies shaped like SwitchBot's."""

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.switchbot_art_frame.account import (
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


def mock_login(aioclient_mock, token="tok1"):
    aioclient_mock.post(
        f"{ACCOUNT}/login",
        json={"statusCode": 100, "body": {"access_token": token}},
    )
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


def account(hass: HomeAssistant) -> SwitchBotAccount:
    return SwitchBotAccount(async_get_clientsession(hass), "a@b.c", "pw", ADDRESS)


async def test_login_finds_group(hass: HomeAssistant, aioclient_mock) -> None:
    mock_login(aioclient_mock)
    acc = account(hass)
    await acc.async_login()
    assert acc.group_id == GROUP
    login_body = aioclient_mock.mock_calls[0][2]
    assert login_body["username"] == "a@b.c"
    assert login_body["grantType"] == "password"
    # Later calls carry the token.
    assert aioclient_mock.mock_calls[1][3]["authorization"] == "tok1"


async def test_login_rejected(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.post(
        f"{ACCOUNT}/login", json={"statusCode": 190, "message": "wrong password"}
    )
    with pytest.raises(AuthError):
        await account(hass).async_login()


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
        await account(hass).async_login()


async def test_list_images_newest_first(hass: HomeAssistant, aioclient_mock) -> None:
    mock_login(aioclient_mock)
    aioclient_mock.post(
        f"{WONDER}/device/artframe/api/v1/images/list",
        json={"resultCode": 100, "data": {"images": IMAGES}, "message": ""},
    )
    images = await account(hass).async_list_images()
    assert [i["id"] for i in images] == [1003, 1002, 1001]
    body = aioclient_mock.mock_calls[-1][2]
    assert body == {"deviceID": "AABBCCDDEEFF", "groupID": GROUP}


async def test_list_images_error(hass: HomeAssistant, aioclient_mock) -> None:
    mock_login(aioclient_mock)
    aioclient_mock.post(
        f"{WONDER}/device/artframe/api/v1/images/list",
        json={"resultCode": 191, "data": None, "message": "not in this group"},
    )
    with pytest.raises(AccountError, match="not in this group"):
        await account(hass).async_list_images()


async def test_delete_images(hass: HomeAssistant, aioclient_mock) -> None:
    mock_login(aioclient_mock)
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
    mock_login(aioclient_mock)
    aioclient_mock.post(
        f"{WONDER}/device/artframe/api/v1/images/delete",
        json={"resultCode": 100, "data": None},
    )
    aioclient_mock.post(
        f"{WONDER}/productbiz/v1/slideshow/syncDeletedImages", status=500
    )
    await account(hass).async_delete_images([16])


async def test_relogin_when_session_rejected(
    hass: HomeAssistant, aioclient_mock
) -> None:
    mock_login(aioclient_mock)
    acc = account(hass)
    await acc.async_login()
    aioclient_mock.post(f"{WONDER}/device/artframe/api/v1/images/list", status=401)
    with pytest.raises(AuthError):
        await acc.async_list_images()
    # One failed list, a fresh login (3 calls), then the retried list.
    paths = [str(c[1]) for c in aioclient_mock.mock_calls[3:]]
    assert paths[0].endswith("images/list")
    assert paths[1].endswith("user/login")
    assert paths[-1].endswith("images/list")
