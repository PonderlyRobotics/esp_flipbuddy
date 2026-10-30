# FlipBuddy

[![CI](https://img.shields.io/badge/CI-GitHub%20Actions-2088FF?logo=githubactions&logoColor=white)](./.github/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](./LICENSE)
[![Hardware: CC BY--NC--SA 4.0](https://img.shields.io/badge/Hardware-CC%20BY--NC--SA%204.0-lightgrey.svg)](./LICENSE-HARDWARE)
[![Release](https://img.shields.io/badge/release-v0.2.3-blue.svg)](./docs/CHANGELOG.md)
[![MicroPython](https://img.shields.io/badge/MicroPython-1.28-2B2728.svg)](https://micropython.org/)

Phone timers failed me because I forgot start/stop, so the hardware is deliberately dumb: face up = activity, flip when you switch, stop face when done.

I built it so the hours would get written down. Two weeks of actually using it showed me that was the side effect: the cube does not remind you to focus; leaving a task means you pick it up and turn it, so a context switch is an act you cannot miss, one task cannot take the evening without you noticing, and a distraction is not an accident you discover later; it is an activity you entered on purpose. Two weeks of that physical act is enough for the habit.

The cube logs each flip. LEDs use the colors you set in the free app at [flipbuddy.app](https://flipbuddy.app). [Hackaday wrote about it](https://hackaday.com/2026/08/07/flipbuddy-is-borg-you-will-be-assimilated/).

This repository is the open DIY build. Firmware **0.2.3** (MicroPython **1.28**) is the image I flash and test. I publish it under **Ponderly Robotics** when evenings allow. Treat it as a hobby project, not a product with phone support.

<p align="center">
  <img src="docs/media/hero-desk.png" alt="FlipBuddy cube with activity LED lit" width="220" />
</p>

## Build one

Print and wire the cube first ([assembly PDF](./FlipBuddy%20Assembly%20guide.pdf), files in [stl/](./stl/)). Then, on an ESP32-S3 Super Mini:

1. On GitHub, open **Releases** → **v0.2.3**. Download `esp32_s3_flipbuddy_0.2.3-ota.bin` and its `.sha256`.
2. Check the file, then flash. This erases the chip. Pair again after every full flash.

    ```bash
    sha256sum -c esp32_s3_flipbuddy_0.2.3-ota.bin.sha256
    just flash-firmware esp32_s3_flipbuddy_0.2.3-ota.bin
    ```

3. Put the entry files and a Wi-Fi password for the cube on it. Write the password down. The screen shows `XXXX XXXX`. Type it with no space.

    ```bash
    just fast-track
    ```

4. At [flipbuddy.app](https://flipbuddy.app), choose **Add Device**, pick the physical cube, and copy the 8-character code.
5. Keep USB plugged in. Join Wi-Fi **`FlipBuddy-XXXX`**. Open [http://10.20.30.40/](http://10.20.30.40/). Enter your house Wi-Fi and the code. The cube blinks green. In the app, confirm.

`just fast-track` copies `main.py`, `settings.py`, and `off_check.py`. It does not copy `credentials.json`. Tags **v0.1.0** through **v0.1.5** do not work with this image.

No `just` on your machine, a different board, or you want the pin map and the parts list: [docs/BUILD.md](./docs/BUILD.md).

## How you use it

- The face that is up is the activity. This is not a countdown alarm.
- Flip when you switch tasks. The stop face is the USB-C port.
- Shake the cube if it slept. A pickup lights the color map for about 7 seconds. Hold one face still for about 10 seconds to start that activity.
- Pause tracking in the app: rapid red on the upward face, and no new session.
- Names, colors, and history are in the app. The cube can still log a flip when Wi-Fi is down.

LED timing, the maintenance Wi-Fi, updates, and the FAQ are in [docs/USE.md](./docs/USE.md).

## Where to go

| You want | Open |
|----------|------|
| Print, flash, pair, or use another board | [docs/BUILD.md](./docs/BUILD.md) |
| Day to day, LEDs, maintenance Wi-Fi, updates, FAQ | [docs/USE.md](./docs/USE.md) |
| Change the code | [CONTRIBUTING.md](./CONTRIBUTING.md) |
| What this image changed | [docs/RELEASE_NOTES_v0.2.3.md](./docs/RELEASE_NOTES_v0.2.3.md) |

## Limits

This is for minutes and hours, not a stopwatch. The Release image is for an ESP32-S3 Super Mini. A LiPo needs a proper charger, and do not leave charging unattended. You build this at your own risk.

## License

| What | License |
|------|---------|
| Software (`.py`, host tools, tests) | [MIT](./LICENSE) |
| Hardware, CAD, assembly PDF, `stl/` | [CC BY-NC-SA 4.0](./LICENSE-HARDWARE) |
| Frozen Release `.bin` | FlipBuddy bits MIT; also MicroPython and other third-party code ([docs/NOTICE](./docs/NOTICE)) |

Copyright 2025–2026 Ponderly Robotics. Ask before you use the enclosure designs commercially.

## Links

- App: https://flipbuddy.app
- Hackaday: https://hackaday.com/2026/08/07/flipbuddy-is-borg-you-will-be-assimilated/
- Firmware: GitHub Releases (`esp32_s3_flipbuddy_0.2.3-ota.bin`, factory `.bin`, checksums)
- [docs/BUILD.md](./docs/BUILD.md), [docs/USE.md](./docs/USE.md)
- [CONTRIBUTING.md](./CONTRIBUTING.md), [SECURITY.md](./SECURITY.md)
- [docs/CHANGELOG.md](./docs/CHANGELOG.md), [docs/NOTICE](./docs/NOTICE)
