# SwitchBot Art Frame Tools

A small Home Assistant custom integration that adds image management to a
SwitchBot AI Art Frame already set up with the core **SwitchBot Bluetooth**
integration:

- **Local images** sensor: how many images are stored on the frame (max 10),
  with `image_ids`, `current_image_id` and `free_slots` attributes.
- **`switchbot_art_frame.delete_image`** action: deletes one stored image over
  Bluetooth.
- **`switchbot_art_frame.show_image`** action: puts a new image on the
  frame (from a web address, a file on the HA machine, or image data) without
  the SwitchBot app, a hub or a phone.
  Needs your SwitchBot account (see below).
- **`switchbot_art_frame.download_image`** action: tells the frame to fetch an
  image from SwitchBot's cloud by its ID (used by `show_image`).
- **`switchbot_art_frame.upload_image`** action (experimental): uploads an
  image to SwitchBot's cloud for the frame and returns SwitchBot's reply.
- **Dashboard card**: pick an image in the browser, preview it at the frame's
  shape, and send it with `show_image`.

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

### SwitchBot account (optional)

`show_image`, and keeping SwitchBot's cloud album in step when you
delete images, need your SwitchBot account email and password. Add them when
setting up, or later with **Reconfigure** on the integration's entry.

The password isn't stored. Logging in gives a session token, renewed
automatically (SwitchBot's access tokens last two hours, the refresh token 30
days), which is stored in Home Assistant's config like other integrations'
tokens. If SwitchBot ends the session, Home Assistant shows a
**Re-authenticate** prompt under Settings > Devices & services and asks for the
password again; until then `show_image` fails and deletes only happen on the
frame. Updating from 0.5 or earlier swaps a stored password for a token the
first time the integration starts.

This uses SwitchBot's private app API (the one PySwitchbot already uses to get
encryption keys), found by reading the app's Art Frame module. It isn't
supported by SwitchBot, could change without notice, and using it may be
against their terms. Google or Apple sign-in accounts won't work.

## delete_image

Target the Local images sensor. `image` is one of:

- an image ID from the sensor's `image_ids` attribute (for example `25`),
- `current`: the image on display,
- `oldest` or `newest`: the frame lists its images oldest first. (`first` and
  `last` mean the same.) The SwitchBot app shows them the other way round.

If the image being deleted is the one on display, the frame switches to the
next image first, so it is never left showing a deleted picture.

The action reads the frame's status before and after, and fails if the image
is still listed afterwards. It returns `deleted_image_id`,
`switched_to_image_id` and `remaining_image_ids` if you ask for a response.

If the frame is unavailable in HA (no recent Bluetooth adverts), Home Assistant
skips the action without an error, so a response without the sensor's entity ID
in it means nothing was deleted.

`homeassistant.update_entity` on the sensor re-reads the frame's status.

`show_image` makes room automatically, so you rarely need to call
`delete_image` yourself.

## show_image

Target the Local images sensor and give exactly one of:

- `image_url`: a web address SwitchBot's servers can reach;
- `image_path`: a PNG or JPEG on the HA machine, in a folder HA may read
  (such as `/config/www` or `/media`);
- `image_data`: the image itself, base64-encoded (or a `data:` URI).

Files and data are sent to SwitchBot as `imageBase64`, so no public URL is
needed. SwitchBot rejects uploads larger than about 1 MiB, so a file or data
must be under about 650 KB (900,000 base64 characters); a 1200×1600 JPEG
usually is. Anything larger is rejected before anything on the frame changes.
It:

1. removes cloud album entries for images no longer on the frame (left over
   from deletes made outside the app), so they don't count against the
   cloud's 10-image limit;
2. if the frame is full, deletes its oldest image, on the frame and in the
   cloud (set `make_room: false` to fail instead);
3. uploads the image through SwitchBot Cloud's API (as
   `switchbot_cloud.upload_art_frame_image` does for URLs; needs the
   SwitchBot Cloud integration);
4. finds the ID SwitchBot gave it in the frame's cloud album;
5. tells the frame over Bluetooth to download that ID (it fetches the image
   over its own Wi-Fi, about 25 s) and shows it.

It returns `image_id`, `image_ids`, `current_image_id`, `progress`,
`deleted_image_id` and `removed_cloud_leftovers`.

```yaml
action: switchbot_art_frame.show_image
target:
  entity_id: sensor.art_frame_eeff_local_images
data:
  image_path: /config/www/frame/today.png
```

## Dashboard card

The integration serves and loads its own card, so there's no resource to add.
Add it to a dashboard:

```yaml
type: custom:switchbot-art-frame-card
entity: sensor.art_frame_eeff_local_images
```

Options:

- `entity` (required): the frame's Local images sensor;
- `orientation`: `portrait` (default) or `landscape`;
- `fit`: `fill` (default; crops to fill the frame) or `fit` (shows the whole
  image with white borders). Both can also be switched on the card;
- `title`: the card's heading (default "Art Frame").

The card shows how many images the frame holds, and warns when it's full that
sending will replace the oldest. When idle it's just a "Choose an image" bar.
Pick a PNG or JPEG and a preview opens at the frame's shape; check it, then
**Show on frame**, or **Cancel** to close it. The card resizes the image to 1200×1600 in the browser and
sends it with `show_image`, so it needs the SwitchBot account too. It sends a
PNG where that fits under the upload limit and a JPEG otherwise. Sending takes
about a minute.

## download_image

Tells the frame to fetch an image that's already in SwitchBot's cloud for it.
`image_id` is required and must be the ID SwitchBot assigned (the frame asks
the cloud for that ID; any other ID fails with download state 3). `show`
defaults to `true`. `show_image` does the whole upload and finds the ID for
you.

## upload_image (experimental)

Uploads the image at `image_url` to SwitchBot's cloud for the frame, through
the SwitchBot Cloud integration, and returns SwitchBot's reply as
`cloud_response`. It makes the same call as
`switchbot_cloud.upload_art_frame_image`, which discards the reply. The frame
doesn't fetch the image until it's told to with `download_image`;
`show_image` does the whole thing.

## How it works

The commands were captured from the SwitchBot app with an Android
Bluetooth HCI snoop log and decrypted with the frame's key:

```
570F7A0102{image_id}     delete image   (reply: 01 <image_id> 1E)
570F7A00                 start Wi-Fi (the app's comment: "trigger device to connect")
570F7A0101{image_id}     download pending cloud image, store as image_id
570F7B00                 download progress (state 0 idle, 1 busy, 2 done, 3 failed)
570F7A02{image_id}       show image     (already in PySwitchbot)
5702                     status         (already in PySwitchbot)
```

## Caveats

- It relies on internals of the core SwitchBot integration and PySwitchbot
  (the coordinator in `runtime_data` and the device's `_send_command`), and of
  the SwitchBot Cloud integration (its API client's `_request`, for uploads).
  An HA update could break it; the fix is usually small.
- Without an account, a Bluetooth delete doesn't tell SwitchBot's cloud, and
  the app shows the image as waiting to sync. With an account, `delete_image`
  also removes it from the cloud album (as the app does).
- New images still come from SwitchBot's cloud: the frame downloads them over
  its own Wi-Fi. If SwitchBot's servers or private API change or go away,
  uploading stops working; images already on the frame are unaffected.
- If the core SwitchBot entry reloads, this integration reloads with it.

Private API calls used (host `wonderlabs.<region>.api.switchbot.net`, after
logging in at `account.api.switchbot.net`), all with `deviceID` (the frame's
MAC) and `groupID` (its SwitchBot home):

```
device/artframe/api/v1/images/list     album: id, imageIndex, status (0 pending, 1 synced)
device/artframe/api/v1/images/delete   {imageIndexList, deleteAll}
productbiz/v1/slideshow/syncDeletedImages   {imageIndexes, deleteAll}
```

## Tests

The development dependencies are pinned in `pyproject.toml` and `uv.lock`.
With [uv](https://docs.astral.sh/uv/):

```
uv sync
uv run pytest
```

The tests use a simulated frame that answers commands the way an Art Frame
does.
