## LS03A compatibility fork

This fork includes fixes tested by a user on a 2021 Samsung Frame LS03A (Art API 2.03):

- Detect the Art API version and use D2D TCP upload for API 2.x+, retaining the legacy WebSocket upload path.
- Send correlated select-image requests so uploaded artwork is displayed automatically.
- Avoid assigning the read-only OptionsFlow config_entry property on current Home Assistant versions.
- Reload through Home Assistant's config-entry lifecycle manager instead of directly calling integration unload/setup. The user confirmed this resolved a freeze when saving matte options.

For HACS, add `https://github.com/yurchenkoiv/samsungtheframe_HAdashboard` as a custom repository of type **Integration**, download it, and restart Home Assistant. For manual installation, copy `custom_components/samsung_frame` to `/config/custom_components/samsung_frame` and restart. Back up existing files first. Do not install duplicate copies of this integration.

Choose `none` for the TV matte option (`matte_color`) to remove the TV-added border; Digital Matte Type is a separate compositor setting. Keep Debug Save off unless diagnosing images. Each refresh uploads a new TV photo; this fork does not add automatic photo cleanup or a refresh schedule. Never use Delete All TV Images unless you intend to remove all user-uploaded artwork.

Run dependency-free regression tests with `python -m unittest discover -s tests -v`. Tests cover protocol helpers and lifecycle/OptionsFlow regressions, not a full Home Assistant runtime or all TV models. No credentials or personal configuration are included.

---

# Samsung Frame Art 

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![GitHub release](https://img.shields.io/github/release/yurchenkoiv/samsungtheframe_HAdashboard.svg)](https://github.com/yurchenkoiv/samsungtheframe_HAdashboard/releases)

A Home Assistant custom integration that pushes randomly selected images with an elegant overlay to your **Samsung The Frame TV** — including full support for the **2019 model**.

---

## Features

- 🖼️ Pushes a random image from a configurable folder to the Frame's Art Mode
- 📅 Elegant frosted-glass overlay with today's date
- 📆 Upcoming calendar events from any HA calendar entity
- 🌤️ Today's weather forecast with icons (condition, hi/lo temp, precipitation)
- 🎨 Digital matte (modern, shadowbox, baroque) with configurable color
- 🔆 Art mode brightness control
- 🗂️ All settings exposed as persistent HA entities (sliders, toggles, dropdowns)
- ✅ Tested on Samsung The Frame 2019 (also works on 2020+)

---

## Screenshots

> *(Add screenshots of your Frame TV here)*

---

## Installation via HACS

1. In HACS, go to **Integrations → Custom Repositories**
2. Add `https://github.com/yurchenkoiv/samsungtheframe_HAdashboard` as an **Integration**
3. Search for **Samsung Frame Art** and install
4. Restart Home Assistant
5. Go to **Settings → Devices & Services → Add Integration** → search **Samsung Frame Art**

## Manual Installation

1. Copy `custom_components/samsung_frame` into your HA `config/custom_components/` folder
2. Restart Home Assistant
3. Add the integration via Settings → Devices & Services

---

## Configuration

During setup you will be asked for:

| Field | Description |
|-------|-------------|
| TV IP Address | Static IP of your Frame TV (set a DHCP reservation in your router) |
| Media Folder | Path to images, default `/media/frame` |
| Token File | Pairing token storage, default `/config/samsung_frame_token.txt` |
| Calendar Entity | HA calendar entity to show events from |
| Language | English / Deutsch / Magyar |
| Days to Show | How many days of calendar events (1 = today only) |
| Matte Style | Physical TV matte style for Samsung API |
| Overlay Opacity | Transparency of the info panels |
| Font Size | Scale factor for all overlay text |

### First Run — TV Pairing

On the **first service call**, your TV will show a pairing dialog. Accept it with your remote. The token is saved to the token file and subsequent calls won't prompt again.

---

## Entities

After setup, the integration creates these entities:

| Entity | Type | Description |
|--------|------|-------------|
| Refresh Art | Button | Trigger an immediate update |
| Delete All TV Images | Button | Remove all uploaded images from TV library |
| Last Generated Image | Image | Preview the last pushed image |
| Font Size | Number (slider) | Overlay text size, 50–200% |
| Overlay Opacity | Number (slider) | Panel transparency, 10–90% |
| Art Mode Brightness | Number (slider) | TV art mode brightness, 0–100% |
| Calendar Days to Show | Number | Days of events to fetch (1 = today only) |
| Language | Select | Display language for overlay text |
| Weather Entity | Select | HA weather entity for forecast |
| Digital Matte Type | Select | none / modern / shadowbox / baroque |
| Show Date Panel | Switch | Toggle the date/weather panel |
| Show Calendar Panel | Switch | Toggle the calendar events panel |
| Show Weather Forecast | Switch | Toggle weather in the date panel |
| Debug Save | Switch | Save generated images to media folder |
| Digital Matte Color | Text | Hex color for digital matte (e.g. `#F5F0E8`) |
| Image Folder | Text | Override image folder path |
| Image File Name | Text | Specific filename to use (empty = random) |

---

## Automation Example

```yaml
automation:
  alias: "Samsung Frame — daily refresh"
  trigger:
    - platform: time
      at: "08:00:00"
  action:
    - service: samsung_frame.update
```

---

## Uploading Images

Place `.jpg` or `.png` files (lowercase extension) into your media folder:

- Via Samba: `\\homeassistant\media\frame\`
- Via SSH/Terminal: `/media/frame/`

---

## Supported TV Models

Tested on **Samsung The Frame 2019** (QE55LS03R). Should work on 2020 and newer models too. Uses the Art Mode WebSocket API with binary frame upload (0.97 protocol).

---

## Troubleshooting

**Image not changing:** Check HA logs for `samsung_frame` — look for connection or upload errors.

**Pairing dialog not appearing:** Go to TV Settings → General → External Device Manager → Device Connection Manager and set Access Notification to "First Time Only".

**Fonts look wrong:** DejaVu fonts are bundled in the integration — no system installation needed.

**Weather icons not showing:** Make sure you have selected a weather entity with daily forecast support in the Weather Entity dropdown.

---

## Credits

The WebSocket communication with the Samsung Frame TV — including the art mode channel handshake, token pairing, and binary frame upload protocol — is based on the excellent work by [@ollo69](https://github.com/ollo69) in the [ha-samsungtv-smart](https://github.com/ollo69/ha-samsungtv-smart) repository. That integration provided the already-working WebSocket implementation that made 2019 Frame TV support possible.

---

## License

MIT
