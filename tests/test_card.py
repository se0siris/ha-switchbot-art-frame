"""The dashboard card is served and loaded with a content-hashed URL."""

import hashlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant

from custom_components.switchbot_art_frame import CARD_URL, _async_register_card

CARD = (
    Path(__file__).parents[1]
    / "custom_components/switchbot_art_frame/frontend/art-frame-card.js"
)


async def test_card_registered_with_content_hash(hass: HomeAssistant) -> None:
    hass.config.components.update({"http", "frontend"})
    hass.http = MagicMock(async_register_static_paths=AsyncMock())
    with patch("homeassistant.components.frontend.add_extra_js_url") as add:
        await _async_register_card(hass)

    (config,) = hass.http.async_register_static_paths.call_args.args[0]
    assert config.url_path == CARD_URL
    assert Path(config.path) == CARD
    digest = hashlib.sha256(CARD.read_bytes()).hexdigest()[:12]
    add.assert_called_once_with(hass, f"{CARD_URL}?v={digest}")


async def test_card_skipped_without_frontend(hass: HomeAssistant) -> None:
    with patch("homeassistant.components.frontend.add_extra_js_url") as add:
        await _async_register_card(hass)
    add.assert_not_called()
