"""Constants for SwitchBot Art Frame Tools."""

from typing import Final

DOMAIN: Final = "switchbot_art_frame"

# Domain and config entry fields of the core SwitchBot Bluetooth integration.
SWITCHBOT_DOMAIN: Final = "switchbot"
SWITCHBOT_SENSOR_TYPE: Final = "sensor_type"
SWITCHBOT_ART_FRAME: Final = "art_frame"

CONF_SWITCHBOT_ENTRY_ID: Final = "switchbot_entry_id"

# The frame stores at most this many images locally.
MAX_LOCAL_IMAGES: Final = 10

# Delete one locally stored image by its ID. Captured from the SwitchBot app
# over BLE; sent encrypted like every other Art Frame command.
COMMAND_DELETE_IMAGE: Final = "570F7A0102{:02X}"

SERVICE_DELETE_IMAGE: Final = "delete_image"
ATTR_IMAGE: Final = "image"

IMAGE_FIRST: Final = "first"
IMAGE_LAST: Final = "last"
IMAGE_CURRENT: Final = "current"
IMAGE_KEYWORDS: Final = (IMAGE_FIRST, IMAGE_LAST, IMAGE_CURRENT)
