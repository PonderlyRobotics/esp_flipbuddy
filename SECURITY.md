# Security and feedback

FlipBuddy is open source (see [LICENSE](./LICENSE) and [LICENSE-HARDWARE](./LICENSE-HARDWARE)). I maintain it in spare time under **Ponderly Robotics**, with no formal SLA — but reports, questions, and ideas from builders are welcome.

## Bugs, questions, and feature requests

For almost everything that is **not** a sensitive security finding, please open a **GitHub issue** on this repository:

- Unexpected cube or firmware behaviour
- Docs, flash, print, or wiring confusion
- Ideas for boards, enclosure variants, or host tooling
- Small improvements you noticed while building

A short write-up with expected vs actual, board / flash path, and serial logs (with secrets redacted) helps a lot. Feature requests do not need a perfect design — a clear “I wish it did X because Y” is enough.

There is no promise that every request will ship, but I read them when I can and they shape what gets attention next.

## Security reports (private when it matters)

I still want to hear about real security problems. Prefer a **private** channel when disclosure could put devices or accounts at risk:

- GitHub **Security Advisory** / private vulnerability reporting on this repo, when available
- Or the contact email on recent commits / the Ponderly Robotics GitHub profile

Please include version or commit, board type, frozen image vs full source, steps to reproduce, and what could go wrong. If live devices or the free companion service might be affected, give a little time to fix things before a public write-up.

**Do not** paste live `device_token` values, Wi‑Fi passwords, or private keys into public issues.

### What counts as a private security report

- Bugs that could leak device tokens or credentials
- Ways to force untrusted OTA or `mip` installs through remote config
- Auth issues against the companion API when using official credentials
- Secrets that landed in this repository by mistake
- Firmware logic that creates an unsafe charge or battery condition (LiPo hardware safety remains on the person building the cube)

Everyday bugs, typos, and “please add this feature” belong in **public issues**, not private advisories.

## Supported versions

| Version | Support |
|---------|---------|
| **0.2.x** | Best effort (claim pairing + dual-OTA freeze) |
| **0.1.x** (v0.1.0–v0.1.5) | Obsolete. Does not work with Production claim pairing or dual-OTA. USB-flash **0.2.3**. |
| Older or untagged trees | No formal support |

## Credentials

NVS holds `device_id`, `device_token`, and house Wi‑Fi secrets. Treat them like passwords. `credentials.json` is identity recovery only (`device_id` / `device_token`); firmware never copies house Wi‑Fi from that file onto flash or to the API. Do not commit either. `.gitignore` already blocks the usual credential JSON names; please do not force-add them.

If a cube has been offline for a long time and no longer talks to the dashboard, the device token may have expired (see the README FAQ). Refresh credentials from the app and re-upload them.

## SoftAP captive portal (HTTP, PIN, Wi‑Fi)

When the **SoftAP cutout** is up (`back_cutout`, opposite the USB‑C port, and AP mode is enabled), the cube can soft‑reset into a temporary **WPA2‑PSK** SoftAP and serve a captive portal over **HTTP** at `http://10.20.30.40/`. Claimed cubes without a host `ap_psk` still use SSID **`FlipBuddy`** and password **`FB` + last 6 alphanumeric characters of `device_id`**. After `just gen-ap-psk`, join SSID is **`FlipBuddy-XXXX`** and the password is the printed NVS value (not derived from the MAC). Unclaimed pairing uses that same PSK and has **no PIN**; type home Wi-Fi on a desk you control (HTTP after WPA2 join). Claimed SoftAP maintenance still needs the setup PIN for Wi-Fi writes. It is **not** a hardened remote admin interface.

### Risks (honest)

| Risk | Why it exists |
|------|----------------|
| **No TLS on SoftAP** | ESP SoftAP + MicroPython cannot host a meaningful HTTPS cert chain for a local AP. After you join, PIN, Wi‑Fi password, and form bodies travel in **cleartext HTTP on the encrypted SoftAP radio**. |
| **Join password is derivable** | WPA2 PSK = **`FB` + last 6 alnum of `device_id`**. Anyone who knows your device id (credentials.json / account UI) can join. Serial also prints `SoftAP PSK=` for DIY/USB-console owners. |
| **PIN over HTTP** | Unlocking settings (or setting a custom PIN) sends the setup PIN in HTTP form posts. A listener already on that SoftAP can capture it for that session. |
| **Wi‑Fi password over HTTP** | After unlock, saving a home SSID/password also uses cleartext forms. Prefer doing this on a private desk, not a shared café radio environment. |
| **Factory default PIN is derivable** | Default unlock PIN = **last 6 alphanumeric characters of `device_id`** (uppercased). Same people who can compute the join PSK can compute the factory PIN until you set a custom PIN. |
| **`/reset` is not PIN‑gated** | Physical possession of the cube (SoftAP cutout + SoftAP) is treated as enough to reboot. That is a usability choice; it is not remote reset over the internet. `/reset` still works after PIN lockout. |
| **Status without unlock** | Time, battery, face map, and local activity summaries are readable without the PIN so the portal stays useful when locked. |
| **Multi‑client shared unlock** | Unlock is **device‑global for that SoftAP session**, not per phone. After one client unlocks, **any other client already on (or joining) the SoftAP** can POST Wi‑Fi / PIN / LED test without knowing the PIN until idle timeout, lock, or SoftAP end. |

`device_token` is **never** shown or written through SoftAP. Changing API credentials still requires USB/`credentials.json` (or equivalent maker path).

### Measures in firmware

These do not make SoftAP “secure against a motivated local attacker,” but they bound the blast radius for hobby use:

| Measure | Detail |
|---------|--------|
| **WPA2-PSK on the radio** | SoftAP is `AUTH_WPA_WPA2_PSK`, not open. Casual neighbors cannot associate without the 8-character join password. Portal stays HTTP `:80` (phone TLS on SoftAP would OOM and break captive detect). |
| **Physical access required** | SoftAP starts only when the cube is on the SoftAP cutout (and AP mode is enabled), via soft-reset into a short maintenance session, not from arbitrary remote wake. |
| **Time‑bound session** | SoftAP portal runs about **5 minutes**, then SoftAP is stopped and the device deep‑sleeps. Unlock idle timeout is also about **5 minutes** of inactivity. |
| **Session unlock, not always‑on admin** | Status is open; **Wi‑Fi write, PIN change, and LED test** need a successful PIN unlock for that SoftAP session. Prefer **only one phone** on `FlipBuddy` while unlocked; use **Lock settings** when finished. |
| **Custom PIN** | After first unlock, set a custom 4–16 alphanumeric PIN in NVS so the factory `device_id` rule no longer applies. |
| **Failed attempt limit** | Wrong PINs are counted; after **8** failures unlock is refused until reboot (portal **Reset device** or power‑cycle). Status and `/reset` remain available. |
| **No `device_token` on SoftAP** | The API device token is never shown or written on the portal. |
| **Cooldown after SoftAP** | Handoff marks reduce SoftAP soft-reset loops while the cube remains on the SoftAP cutout. Leave that cutout before expecting SoftAP again. |

### What you should do as a builder

1. Prefer SoftAP Wi‑Fi / PIN changes in a place you control (your desk), not a crowded shared spectrum if you can avoid it.
2. Change the setup PIN after first use if the cube might leave your desk or if `device_id` is shared.
3. While unlocked, keep only one client on the `FlipBuddy` network; lock settings when done.
4. Treat a lost cube as a physical-security event: refresh dashboard credentials, rotate Wi‑Fi if you saved it on the cube, and assume status data on the portal was readable while SoftAP was up.
5. Keep using USB `credentials.json` as the recovery path when SoftAP is wrong or unavailable.

End-user SoftAP steps (join AP, fix Wi-Fi, clock recovery) live in [Use the cube](./docs/USE.md#softap-maintenance-mode).

Hobby firmware cannot fully stop physical theft, an unlocked session, or someone who already knows `device_id`. Report real escalations (e.g. remote trigger of SoftAP, token leak, unauthenticated Wi‑Fi write) via the private channels above.

## Firmware images

Prefer Release assets that ship with SHA-256 checksums. GitHub Releases attach **USB** images only (`*-ota.bin` and the factory `.bin`). App-slot OTA packages are not public Release files. Frozen images also contain MicroPython and other third-party code; see [docs/NOTICE](./docs/NOTICE). Supported freeze is **0.2.x**; **0.1.x** does not work with Production claim pairing or dual-OTA.

## Scope

This note covers the open firmware and DIY tree. The [flipbuddy.app](https://flipbuddy.app) backend is a separate system. Hobby firmware cannot fully stop physical theft, an unlocked device, or a hostile Wi‑Fi network.

Thanks for building carefully and for helping make FlipBuddy safer and easier for the next person.
