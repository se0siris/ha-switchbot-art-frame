"""Config flow: pick an Art Frame already set up in SwitchBot Bluetooth."""

from __future__ import annotations

from typing import Any

import probatio as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import (
    CONF_SWITCHBOT_ENTRY_ID,
    DOMAIN,
    SWITCHBOT_ART_FRAME,
    SWITCHBOT_DOMAIN,
    SWITCHBOT_SENSOR_TYPE,
)


class ArtFrameToolsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    VERSION = 1

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
            core_id = user_input[CONF_SWITCHBOT_ENTRY_ID]
            core = self.hass.config_entries.async_get_known_entry(core_id)
            await self.async_set_unique_id(core.unique_id or core_id)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=core.title, data={CONF_SWITCHBOT_ENTRY_ID: core_id}
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_SWITCHBOT_ENTRY_ID): vol.In(available)}
            ),
        )
