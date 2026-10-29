"""SwitchBot Art Frame Tools.

Adds image management to an Art Frame that is already set up with the core
SwitchBot Bluetooth integration. It reuses that integration's connected device
(and so its encryption key and Bluetooth routing) rather than holding its own.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from switchbot import SwitchbotArtFrame

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, CONF_TOKEN, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .account import AccountError, AuthError, SwitchBotAccount
from .const import CONF_SWITCHBOT_ENTRY_ID, DOMAIN
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)

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

    path = Path(__file__).parent / "frontend" / "art-frame-card.js"
    content = await hass.async_add_executor_job(path.read_bytes)
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(path), cache_headers=False)]
    )
    # Tag the URL with a hash of the file, so browsers never reuse a cached
    # copy of a different (or failed) version.
    add_extra_js_url(hass, f"{CARD_URL}?v={hashlib.sha256(content).hexdigest()[:12]}")


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
    address = coordinator.ble_device.address
    if CONF_PASSWORD in entry.data:
        await _async_replace_password(hass, entry, address)

    account = None
    if entry.data.get(CONF_TOKEN):

        @callback
        def _save_tokens(tokens: dict[str, Any]) -> None:
            hass.config_entries.async_update_entry(
                entry, data={**entry.data, CONF_TOKEN: tokens}
            )

        # Contacts SwitchBot only on first use, so setup doesn't depend on
        # SwitchBot's servers.
        account = SwitchBotAccount(
            async_get_clientsession(hass),
            address,
            entry.data[CONF_TOKEN],
            _save_tokens,
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


async def _async_replace_password(
    hass: HomeAssistant, entry: ArtFrameConfigEntry, address: str
) -> None:
    """Swap a password stored by version 0.5 and earlier for tokens."""
    data = dict(entry.data)
    account = SwitchBotAccount(async_get_clientsession(hass), address)
    try:
        await account.async_login(data[CONF_EMAIL], data[CONF_PASSWORD])
    except AuthError as err:
        _LOGGER.warning("Stored SwitchBot login no longer works: %s", err)
        entry.async_start_reauth(hass)
    except AccountError as err:
        # E.g. SwitchBot's servers are down: keep the password and try again
        # next time, running without the account until then.
        _LOGGER.warning(
            "Couldn't swap the stored SwitchBot password for a token: %s", err
        )
        return
    else:
        data[CONF_TOKEN] = account.tokens
    del data[CONF_PASSWORD]
    hass.config_entries.async_update_entry(entry, data=data)


async def async_unload_entry(hass: HomeAssistant, entry: ArtFrameConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
