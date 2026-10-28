"""Actions for SwitchBot Art Frame Tools."""

import probatio as vol

from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.core import HomeAssistant, SupportsResponse, callback
from homeassistant.helpers import service

from .const import ATTR_IMAGE, DOMAIN, IMAGE_KEYWORDS, SERVICE_DELETE_IMAGE

IMAGE_SCHEMA = vol.Any(
    vol.In(IMAGE_KEYWORDS), vol.All(vol.Coerce(int), vol.Range(min=0, max=255))
)


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register actions."""
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_DELETE_IMAGE,
        entity_domain=SENSOR_DOMAIN,
        schema={vol.Required(ATTR_IMAGE): IMAGE_SCHEMA},
        func="async_delete_image",
        supports_response=SupportsResponse.OPTIONAL,
    )
