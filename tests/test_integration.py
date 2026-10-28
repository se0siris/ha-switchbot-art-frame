"""Tests for the config flow, sensor and delete_image action in Home Assistant."""

import pytest

from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.setup import async_setup_component

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.switchbot_art_frame.const import CONF_SWITCHBOT_ENTRY_ID, DOMAIN

from .conftest import ADDRESS

ENTITY_ID = "sensor.art_frame_eeff_local_images"


@pytest.fixture
async def setup_entry(
    hass: HomeAssistant, core_entry, art_frame_device
) -> MockConfigEntry:
    """Our entry, set up against the core entry, with status already read."""
    await art_frame_device.update()
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=core_entry.title,
        unique_id=core_entry.unique_id,
        data={CONF_SWITCHBOT_ENTRY_ID: core_entry.entry_id},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_config_flow(hass: HomeAssistant, core_entry) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_SWITCHBOT_ENTRY_ID: core_entry.entry_id}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Art Frame EEFF"
    assert result["data"] == {CONF_SWITCHBOT_ENTRY_ID: core_entry.entry_id}

    # Second attempt: nothing left to add.
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_config_flow_no_frames(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_art_frames"


async def test_sensor(hass: HomeAssistant, setup_entry, core_entry) -> None:
    state = hass.states.get(ENTITY_ID)
    assert state is not None
    assert state.state == "10"
    assert state.attributes["image_ids"][-2:] == [0x18, 0x19]
    assert state.attributes["current_image_id"] == 0x19
    assert state.attributes["free_slots"] == 0

    # Shown on the core integration's device; no second device is created.
    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_device_by_connection(
        (dr.CONNECTION_BLUETOOTH, ADDRESS), core_entry.entry_id
    )
    entity = er.async_get(hass).async_get(ENTITY_ID)
    assert entity.device_id == device.id
    assert dr.async_entries_for_config_entry(dev_reg, setup_entry.entry_id) == []


async def test_delete_action(hass: HomeAssistant, setup_entry, frame) -> None:
    response = await hass.services.async_call(
        DOMAIN,
        "delete_image",
        {"entity_id": ENTITY_ID, "image": "last"},
        blocking=True,
        return_response=True,
    )
    assert response[ENTITY_ID]["deleted_image_id"] == 0x19
    assert response[ENTITY_ID]["switched_to_image_id"] == 0x10
    state = hass.states.get(ENTITY_ID)
    assert state.state == "9"
    assert state.attributes["free_slots"] == 1
    assert 0x19 not in frame.image_ids


async def test_delete_action_by_id_string(
    hass: HomeAssistant, setup_entry, frame
) -> None:
    """IDs typed in the UI arrive as strings."""
    await hass.services.async_call(
        DOMAIN, "delete_image", {"entity_id": ENTITY_ID, "image": "16"}, blocking=True
    )
    assert 0x10 not in frame.image_ids


async def test_delete_action_unknown_id(hass: HomeAssistant, setup_entry) -> None:
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "delete_image",
            {"entity_id": ENTITY_ID, "image": 0x99},
            blocking=True,
        )


async def test_delete_action_refused(hass: HomeAssistant, setup_entry, frame) -> None:
    frame.refuse = {"570F7A0102"}
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN,
            "delete_image",
            {"entity_id": ENTITY_ID, "image": 0x10},
            blocking=True,
        )


async def test_update_entity(hass: HomeAssistant, setup_entry, frame) -> None:
    """homeassistant.update_entity re-reads the frame."""
    frame.image_ids.pop(0)
    assert await async_setup_component(hass, "homeassistant", {})
    await hass.services.async_call(
        "homeassistant", "update_entity", {"entity_id": ENTITY_ID}, blocking=True
    )
    assert hass.states.get(ENTITY_ID).state == "9"


async def test_waits_for_core_entry(hass: HomeAssistant, core_entry) -> None:
    core_entry.mock_state(hass, ConfigEntryState.SETUP_RETRY)
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_SWITCHBOT_ENTRY_ID: core_entry.entry_id}
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_missing_core_entry(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_SWITCHBOT_ENTRY_ID: "gone"})
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_ERROR


async def test_reloads_when_core_unloads(
    hass: HomeAssistant, setup_entry, core_entry
) -> None:
    """When the core entry goes away its coordinator is stale, so we reload."""
    core_entry.mock_state(hass, ConfigEntryState.NOT_LOADED)
    await hass.async_block_till_done()
    assert setup_entry.state is ConfigEntryState.SETUP_RETRY


async def test_download_action(hass: HomeAssistant, setup_entry, frame) -> None:
    frame.image_ids.pop(0)
    response = await hass.services.async_call(
        DOMAIN,
        "download_image",
        {"entity_id": ENTITY_ID, "image_id": "26"},
        blocking=True,
        return_response=True,
    )
    assert response[ENTITY_ID]["image_id"] == 26
    state = hass.states.get(ENTITY_ID)
    assert state.state == "10"
    assert state.attributes["current_image_id"] == 26


async def test_download_action_frame_full(hass: HomeAssistant, setup_entry) -> None:
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "download_image", {"entity_id": ENTITY_ID}, blocking=True
        )


async def test_delete_oldest(hass: HomeAssistant, setup_entry, frame) -> None:
    await hass.services.async_call(
        DOMAIN,
        "delete_image",
        {"entity_id": ENTITY_ID, "image": "oldest"},
        blocking=True,
    )
    assert 0x10 not in frame.image_ids


async def test_upload_action_returns_cloud_reply(
    hass: HomeAssistant, setup_entry
) -> None:
    calls = []

    class FakeApi:
        async def _request(self, method, path, json=None):
            calls.append((method, path, json))
            return {"imageId": 26}

    cloud = MockConfigEntry(domain="switchbot_cloud")
    cloud.add_to_hass(hass)
    cloud.mock_state(hass, ConfigEntryState.LOADED)
    cloud.runtime_data = type("D", (), {"api": FakeApi()})()

    response = await hass.services.async_call(
        DOMAIN,
        "upload_image",
        {"entity_id": ENTITY_ID, "image_url": "https://example.com/a.jpg"},
        blocking=True,
        return_response=True,
    )
    assert response[ENTITY_ID] == {"cloud_response": {"imageId": 26}}
    assert calls == [
        (
            "POST",
            "devices/AABBCCDDEEFF/commands",
            {
                "commandType": "command",
                "command": "uploadImage",
                "parameter": {"imageUrl": "https://example.com/a.jpg"},
            },
        )
    ]
    # A fake entry: stop HA importing the real integration to unload it.
    cloud.mock_state(hass, ConfigEntryState.NOT_LOADED)


async def test_upload_action_without_cloud(hass: HomeAssistant, setup_entry) -> None:
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "upload_image",
            {"entity_id": ENTITY_ID, "image_url": "https://example.com/a.jpg"},
            blocking=True,
            return_response=True,
        )
