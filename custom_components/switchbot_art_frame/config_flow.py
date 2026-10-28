"""Config flow: pick an Art Frame already set up in SwitchBot Bluetooth, and
optionally a SwitchBot account for uploading images without the app."""

from __future__ import annotations

from typing import Any

import probatio as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .account import AccountError, AuthError, SwitchBotAccount
from .const import (
    CONF_SWITCHBOT_ENTRY_ID,
    DOMAIN,
    SWITCHBOT_ART_FRAME,
    SWITCHBOT_DOMAIN,
    SWITCHBOT_SENSOR_TYPE,
)

ACCOUNT_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_EMAIL, default=""): TextSelector(
            TextSelectorConfig(type=TextSelectorType.EMAIL)
        ),
        vol.Optional(CONF_PASSWORD, default=""): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
    }
)


class ArtFrameToolsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialise."""
        self._core_id: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose which Art Frame to manage."""
        frames = {
            core.entry_id: core.title
            for core in self.hass.config_entries.async_entries(SWITCHBOT_DOMAIN)
            if core.data.get(SWITCHBOT_SENSOR_TYPE) == SWITCHBOT_ART_FRAME
        }
        if not frames:
            return self.async_abort(reason="no_art_frames")

        configured = {
            entry.data[CONF_SWITCHBOT_ENTRY_ID]
            for entry in self._async_current_entries()
        }
        available = {k: v for k, v in frames.items() if k not in configured}
        if not available:
            return self.async_abort(reason="already_configured")

        if user_input is not None:
            self._core_id = user_input[CONF_SWITCHBOT_ENTRY_ID]
            core = self.hass.config_entries.async_get_known_entry(self._core_id)
            await self.async_set_unique_id(core.unique_id or self._core_id)
            self._abort_if_unique_id_configured()
            return await self.async_step_account()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_SWITCHBOT_ENTRY_ID): vol.In(available)}
            ),
        )

    async def _async_check_account(
        self, core_id: str, user_input: dict[str, Any]
    ) -> dict[str, str]:
        """Return form errors; empty if the account is fine or left blank."""
        email = user_input.get(CONF_EMAIL, "").strip()
        password = user_input.get(CONF_PASSWORD, "")
        if not email and not password:
            return {}
        if not email or not password:
            return {"base": "account_incomplete"}
        core = self.hass.config_entries.async_get_known_entry(core_id)
        account = SwitchBotAccount(
            async_get_clientsession(self.hass),
            email,
            password,
            core.data.get("address", ""),
        )
        try:
            await account.async_login()
        except AuthError:
            return {"base": "invalid_auth"}
        except AccountError:
            return {"base": "frame_not_in_account"}
        return {}

    async def async_step_account(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Optionally add a SwitchBot account."""
        assert self._core_id is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = await self._async_check_account(self._core_id, user_input)
            if not errors:
                core = self.hass.config_entries.async_get_known_entry(self._core_id)
                return self.async_create_entry(
                    title=core.title,
                    data=_entry_data(self._core_id, user_input),
                )
        return self.async_show_form(
            step_id="account",
            data_schema=self.add_suggested_values_to_schema(
                ACCOUNT_SCHEMA, user_input or {}
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add, change or remove the SwitchBot account."""
        entry = self._get_reconfigure_entry()
        core_id = entry.data[CONF_SWITCHBOT_ENTRY_ID]
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = await self._async_check_account(core_id, user_input)
            if not errors:
                return self.async_update_reload_and_abort(
                    entry, data=_entry_data(core_id, user_input)
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                ACCOUNT_SCHEMA,
                user_input or {CONF_EMAIL: entry.data.get(CONF_EMAIL, "")},
            ),
            errors=errors,
        )


def _entry_data(core_id: str, user_input: dict[str, Any]) -> dict[str, Any]:
    data: dict[str, Any] = {CONF_SWITCHBOT_ENTRY_ID: core_id}
    email = user_input.get(CONF_EMAIL, "").strip()
    if email and user_input.get(CONF_PASSWORD):
        data[CONF_EMAIL] = email
        data[CONF_PASSWORD] = user_input[CONF_PASSWORD]
    return data
