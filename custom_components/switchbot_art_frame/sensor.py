"""Local images sensor for the Art Frame."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from bleak.exc import BleakError
from switchbot import SwitchbotArtFrame, SwitchbotOperationError

from homeassistant.components.bluetooth.passive_update_coordinator import (
    PassiveBluetoothCoordinatorEntity,
)
from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant, ServiceResponse, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .art_frame import (
    ArtFrameError,
    ImageSelectionError,
    async_delete_image,
    async_refresh,
)
from .const import CONF_SWITCHBOT_ENTRY_ID, MAX_LOCAL_IMAGES

if TYPE_CHECKING:
    from homeassistant.components.switchbot.coordinator import (
        SwitchbotDataUpdateCoordinator,
    )

    from . import ArtFrameConfigEntry

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ArtFrameConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensor."""
    coordinator = entry.runtime_data
    # Show the sensor on the core integration's device rather than creating a
    # second device. Since devices are now owned by a single config entry,
    # this is done the way helper integrations do it: by linking the entity
    # to that device directly.
    core_device = dr.async_get(hass).async_get_device_by_connection(
        (dr.CONNECTION_BLUETOOTH, coordinator.ble_device.address),
        entry.data[CONF_SWITCHBOT_ENTRY_ID],
    )
    async_add_entities([ArtFrameLocalImagesSensor(coordinator, core_device)])


class ArtFrameLocalImagesSensor(
    PassiveBluetoothCoordinatorEntity["SwitchbotDataUpdateCoordinator"], SensorEntity
):
    """Number of images stored on the frame, with their IDs as attributes."""

    _attr_has_entity_name = True
    _attr_translation_key = "local_images"
    _device: SwitchbotArtFrame

    def __init__(
        self,
        coordinator: SwitchbotDataUpdateCoordinator,
        core_device: dr.DeviceEntry | None,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator)
        self._device = coordinator.device
        self._attr_unique_id = f"{coordinator.base_unique_id}-local_images"
        self.device_entry = core_device
        if core_device is None:
            # Not found (should not happen): fall back to a name of our own.
            self._attr_has_entity_name = False
            self._attr_name = f"{coordinator.device_name} Local images"

    async def async_added_to_hass(self) -> None:
        """Also update when the device itself reports fresh status."""
        await super().async_added_to_hass()
        self.async_on_remove(self._device.subscribe(self._handle_device_update))

    @callback
    def _handle_device_update(self) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> int | None:
        """Return the number of locally stored images."""
        return self._device.get_total_images()

    @property
    def extra_state_attributes(self) -> Mapping[str, Any]:
        """Return the image IDs."""
        image_ids = self._device.get_all_images_index()
        total = self._device.get_total_images()
        return {
            "image_ids": list(image_ids) if image_ids is not None else None,
            "current_image_id": self._device.get_current_image_index(),
            "free_slots": MAX_LOCAL_IMAGES - total if total is not None else None,
        }

    async def async_update(self) -> None:
        """Read status from the frame (used by homeassistant.update_entity)."""
        try:
            await async_refresh(self._device)
        except (ArtFrameError, SwitchbotOperationError, BleakError) as err:
            raise HomeAssistantError(
                f"Could not read the frame's status: {err}"
            ) from err

    async def async_delete_image(self, image: str | int) -> ServiceResponse:
        """Handle the delete_image action."""
        try:
            response = await async_delete_image(self._device, image)
        except ImageSelectionError as err:
            raise ServiceValidationError(str(err)) from err
        except (ArtFrameError, SwitchbotOperationError, BleakError) as err:
            raise HomeAssistantError(f"Deleting the image failed: {err}") from err
        self.async_write_ha_state()
        return response
