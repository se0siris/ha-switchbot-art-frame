"""SwitchBot Art Frame Tools.

Adds image management to an Art Frame that is already set up with the core
SwitchBot Bluetooth integration. It reuses that integration's connected device
(and so its encryption key and Bluetooth routing) rather than holding its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from switchbot import SwitchbotArtFrame

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .account import SwitchBotAccount
from .const import CONF_SWITCHBOT_ENTRY_ID, DOMAIN
from .services import async_setup_services

if TYPE_CHECKING:
    from homeassistant.components.switchbot.coordinator import (
        SwitchbotDataUpdateCoordinator,
    )

PLATFORMS = [Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass
class ArtFrameData:
    """What the entities need: the core entry's coordinator, and optionally
    a SwitchBot account session for the cloud album."""

    coordinator: SwitchbotDataUpdateCoordinator
    account: SwitchBotAccount | None


type ArtFrameConfigEntry = ConfigEntry[ArtFrameData]


CARD_URL = f"/{DOMAIN}/art-frame-card.js"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register actions, and serve and load the dashboard card."""
    async_setup_services(hass)
    await _async_register_card(hass)
    return True


async def _async_register_card(hass: HomeAssistant) -> None:
    """Serve the card and add it to the frontend, so it needs no resource."""
    if "http" not in hass.config.components or "frontend" not in hass.config.components:
        return  # e.g. in tests
    from homeassistant.components.frontend import add_extra_js_url  # noqa: PLC0415
    from homeassistant.components.http import StaticPathConfig  # noqa: PLC0415
    from homeassistant.loader import async_get_integration  # noqa: PLC0415

    version = (await async_get_integration(hass, DOMAIN)).version
    path = Path(__file__).parent / "frontend" / "art-frame-card.js"
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(path), cache_headers=False)]
    )
    # The version busts the browser cache when the integration is updated.
    add_extra_js_url(hass, f"{CARD_URL}?v={version}")


async def async_setup_entry(hass: HomeAssistant, entry: ArtFrameConfigEntry) -> bool:
    """Attach to the core SwitchBot entry for this frame."""
    core_entry = hass.config_entries.async_get_entry(
        entry.data[CONF_SWITCHBOT_ENTRY_ID]
    )
    if core_entry is None:
        raise ConfigEntryError(
            "The SwitchBot Bluetooth entry for this frame no longer exists; "
            "remove this entry and add it again"
        )
    if core_entry.state is not ConfigEntryState.LOADED:
        raise ConfigEntryNotReady(
            f"Waiting for SwitchBot Bluetooth entry '{core_entry.title}' to load"
        )

    coordinator = core_entry.runtime_data
    if not isinstance(coordinator.device, SwitchbotArtFrame):
        raise ConfigEntryError(f"'{core_entry.title}' is not an Art Frame")
    account = None
    if entry.data.get(CONF_EMAIL) and entry.data.get(CONF_PASSWORD):
        # Logs in on first use, so setup doesn't depend on SwitchBot's servers.
        account = SwitchBotAccount(
            async_get_clientsession(hass),
            entry.data[CONF_EMAIL],
            entry.data[CONF_PASSWORD],
            coordinator.ble_device.address,
        )
    entry.runtime_data = ArtFrameData(coordinator, account)

    # Our entities hold the core entry's coordinator. When that entry unloads
    # (reload, update, removal) the coordinator is replaced, so reload too.
    @callback
    def _core_state_changed() -> None:
        if core_entry.state is ConfigEntryState.LOADED or hass.is_stopping:
            return
        if entry.state is ConfigEntryState.LOADED:
            hass.config_entries.async_schedule_reload(entry.entry_id)

    entry.async_on_unload(core_entry.async_on_state_change(_core_state_changed))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ArtFrameConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
