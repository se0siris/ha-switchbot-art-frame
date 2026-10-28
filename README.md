# SwitchBot Art Frame Tools

A small Home Assistant custom integration that adds image management to a
SwitchBot AI Art Frame already set up with the core **SwitchBot Bluetooth**
integration:

- **Local images** sensor: how many images are stored on the frame (max 10),
  with `image_ids`, `current_image_id` and `free_slots` attributes.
- **`switchbot_art_frame.delete_image`** action: deletes one stored image over
  Bluetooth.

It holds no keys or connections of its own. It uses the core integration's
connected device, so commands are encrypted with the key that integration
already has and are routed through your Bluetooth proxies as usual.

Built and tested against Home Assistant 2026.10.1 (PySwitchbot 2.9.0).

## Install

1. Copy `custom_components/switchbot_art_frame` into your HA config's
   `custom_components` folder.
2. Restart Home Assistant.
3. Settings → Devices & services → Add integration → **SwitchBot Art Frame
   Tools**, and pick the frame.

The sensor appears on the existing Art Frame device page.

## delete_image

Target the Local images sensor. `image` is one of:

- an image ID from the sensor's `image_ids` attribute (for example `187`),
- `current`: the image on display,
- `first` or `last`: by the order the frame lists its images in. How that order
  relates to upload time hasn't been checked yet.

If the image being deleted is the one on display, the frame switches to the
next image first, so it is never left showing a deleted picture.

The action reads the frame's status before and after, and fails if the image
is still listed afterwards. It returns `deleted_image_id`,
`switched_to_image_id` and `remaining_image_ids` if you ask for a response.

If the frame is unavailable in HA (no recent Bluetooth adverts), Home Assistant
skips the action without an error, so a response without the sensor's entity ID
in it means nothing was deleted.

`homeassistant.update_entity` on the sensor re-reads the frame's status.

### Example: make room before a cloud upload

```yaml
sequence:
  - action: homeassistant.update_entity
    target:
      entity_id: sensor.art_frame_eeff_local_images
  - if:
      - condition: numeric_state
        entity_id: sensor.art_frame_eeff_local_images
        above: 9
    then:
      - action: switchbot_art_frame.delete_image
        target:
          entity_id: sensor.art_frame_eeff_local_images
        data:
          image: first
  # ...then your existing switchbot_cloud.upload_art_frame_image step
```

## How it works

The delete command was captured from the SwitchBot app with an Android
Bluetooth HCI snoop log and decrypted with the frame's key:

```
570F7A0102{image_id}     delete image   (reply: 01 <image_id> 1E)
570F7A02{image_id}       show image     (already in PySwitchbot)
5702                     status         (already in PySwitchbot)
```

## Caveats

- It relies on internals of the core SwitchBot integration and PySwitchbot
  (the coordinator in `runtime_data` and the device's `_send_command`). An HA
  update could break it; the fix is usually small.
- A Bluetooth delete doesn't tell SwitchBot's cloud. How the app's album
  view reacts to that is untested.
- If the core SwitchBot entry reloads, this integration reloads with it.

## Tests

The development dependencies are pinned in `pyproject.toml` and `uv.lock`.
With [uv](https://docs.astral.sh/uv/):

```
uv sync
uv run pytest
```

The tests use a simulated frame that answers commands the way an Art Frame
does.
