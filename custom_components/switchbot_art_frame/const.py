"""Constants for SwitchBot Art Frame Tools."""

from typing import Final

DOMAIN: Final = "switchbot_art_frame"

# Domain and config entry fields of the core SwitchBot Bluetooth integration.
SWITCHBOT_DOMAIN: Final = "switchbot"
SWITCHBOT_CLOUD_DOMAIN: Final = "switchbot_cloud"
SWITCHBOT_SENSOR_TYPE: Final = "sensor_type"
SWITCHBOT_ART_FRAME: Final = "art_frame"

CONF_SWITCHBOT_ENTRY_ID: Final = "switchbot_entry_id"

# The frame stores at most this many images locally.
MAX_LOCAL_IMAGES: Final = 10

# Delete one locally stored image by its ID. Captured from the SwitchBot app
# over BLE; sent encrypted like every other Art Frame command.
COMMAND_DELETE_IMAGE: Final = "570F7A0102{:02X}"

# Captured from the app syncing an image to the frame. The frame fetches the
# image itself over Wi-Fi from SwitchBot's cloud; Bluetooth only starts it.
COMMAND_DOWNLOAD_PREPARE: Final = "570F7A00"  # sent by the app first; purpose unknown
COMMAND_DOWNLOAD_IMAGE: Final = "570F7A0101{:02X}"  # download, store under this ID
COMMAND_DOWNLOAD_STATUS: Final = "570F7B00"  # progress; polled once a second

# Fields of the COMMAND_DOWNLOAD_STATUS reply (after the result byte).
STATUS_STATE: Final = 2  # 0 idle, 1 downloading, 2 finished
STATUS_COUNT: Final = 3
STATUS_IDS: Final = slice(4, 14)
STATUS_PERCENT: Final = 14

SERVICE_DELETE_IMAGE: Final = "delete_image"
SERVICE_DOWNLOAD_IMAGE: Final = "download_image"
SERVICE_UPLOAD_IMAGE: Final = "upload_image"
SERVICE_SHOW_IMAGE_FROM_URL: Final = "show_image_from_url"
ATTR_MAKE_ROOM: Final = "make_room"
ATTR_IMAGE_URL: Final = "image_url"
ATTR_IMAGE: Final = "image"
ATTR_IMAGE_ID: Final = "image_id"
ATTR_SHOW: Final = "show"

# The frame lists images oldest first, so first == oldest and last == newest.
IMAGE_FIRST: Final = "first"
IMAGE_LAST: Final = "last"
IMAGE_OLDEST: Final = "oldest"
IMAGE_NEWEST: Final = "newest"
IMAGE_CURRENT: Final = "current"
IMAGE_KEYWORDS: Final = (
    IMAGE_OLDEST,
    IMAGE_NEWEST,
    IMAGE_CURRENT,
    IMAGE_FIRST,
    IMAGE_LAST,
)
