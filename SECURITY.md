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
| **0.1.x** | Best effort |
| Older or untagged trees | No formal support |

## Credentials

`credentials.json` and NVS hold `device_id`, `device_token`, and Wi‑Fi secrets. Treat them like passwords. Do not commit them. `.gitignore` already blocks the usual credential JSON names; please do not force-add them.

If a cube has been offline for a long time and no longer talks to the dashboard, the device token may have expired (see the README FAQ). Refresh credentials from the app and re-upload them.

## SoftAP captive portal (HTTP, PIN, Wi‑Fi)

When the **USB‑C face** is up (and AP mode is enabled), the cube can soft‑reset into a temporary SoftAP named **`FlipBuddy`** and serve a captive portal over **cleartext HTTP** at `http://10.20.30.40/`. That path is intentional local maintenance: status, Wi‑Fi profile edits, setup PIN change, LED self‑test, and device reset. It is **not** a hardened remote admin interface.

### Risks (honest)

| Risk | Why it exists |
|------|----------------|
| **No TLS on SoftAP** | ESP SoftAP + MicroPython cannot host a meaningful HTTPS cert chain for a local AP. PIN, Wi‑Fi password, and form bodies travel in **cleartext on the SoftAP Wi‑Fi**. |
| **Open SoftAP** | The AP uses open auth so a phone can join without a Wi‑Fi password. Anyone in radio range while the session is up can associate and hit the portal. |
| **PIN over HTTP** | Unlocking settings (or setting a custom PIN) sends the setup PIN in HTTP form posts. A passive listener on that SoftAP can capture it for that session. |
| **Wi‑Fi password over HTTP** | After unlock, saving a home SSID/password also uses cleartext forms. Prefer doing this on a private desk, not a shared café radio environment. |
| **Factory default PIN is derivable** | Default unlock PIN = **last 6 alphanumeric characters of `device_id`** (uppercased). Anyone who knows your device id (e.g. from credentials or account UI) can compute it until you set a custom PIN. |
| **`/reset` is not PIN‑gated** | Physical possession of the cube (USB face + SoftAP) is treated as enough to reboot. That is a usability choice; it is not remote reset over the internet. `/reset` still works after PIN lockout. |
| **Status without unlock** | Time, battery, face map, and local activity summaries are readable without the PIN so the portal stays useful when locked. |
| **Multi‑client shared unlock** | Unlock is **device‑global for that SoftAP session**, not per phone. After one client unlocks, **any other client already on (or joining) the open SoftAP** can POST Wi‑Fi / PIN / LED test without knowing the PIN until idle timeout, lock, or SoftAP end. |

`device_token` is **never** shown or written through SoftAP. Changing API credentials still requires USB/`credentials.json` (or equivalent maker path).

### Measures in firmware

These do not make SoftAP “secure against a motivated local attacker,” but they bound the blast radius for hobby use:

| Measure | Detail |
|---------|--------|
| **Physical access required** | SoftAP starts only when the cube is on the USB face (and AP mode is enabled), via soft‑reset into a short maintenance session—not from arbitrary remote wake. |
| **Time‑bound session** | SoftAP portal runs about **5 minutes**, then SoftAP is stopped and the device deep‑sleeps. Unlock idle timeout is also about **5 minutes** of inactivity. |
| **Session unlock, not always‑on admin** | Status is open; **Wi‑Fi write, PIN change, and LED test** need a successful PIN unlock for that SoftAP session. Prefer **only one phone** on `FlipBuddy` while unlocked; use **Lock settings** when finished. |
| **Custom PIN** | After first unlock, set a custom 4–16 alphanumeric PIN in NVS so the factory `device_id` rule no longer applies. |
| **Failed attempt limit** | Wrong PINs are counted; after **8** failures unlock is refused until reboot (portal **Reset device** or power‑cycle). Status and `/reset` remain available. |
| **No `device_token` on SoftAP** | The API device token is never shown or written on the portal. |
| **Cooldown after SoftAP** | Handoff marks reduce SoftAP soft‑reset loops while the cube remains on the USB face. Leave the USB face before expecting SoftAP again. |

### What you should do as a builder

1. Prefer SoftAP Wi‑Fi / PIN changes in a place you control (your desk), not a crowded shared spectrum if you can avoid it.
2. Change the setup PIN after first use if the cube might leave your desk or if `device_id` is shared.
3. While unlocked, keep only one client on the `FlipBuddy` network; lock settings when done.
4. Treat a lost cube as a physical-security event: refresh dashboard credentials, rotate Wi‑Fi if you saved it on the cube, and assume status data on the portal was readable while SoftAP was up.
5. Keep using USB `credentials.json` as the recovery path when SoftAP is wrong or unavailable.

End‑user SoftAP steps (join AP, fix Wi‑Fi, clock recovery) live in the [README SoftAP section](./README.md#softap-maintenance-mode).

Hobby firmware cannot fully stop physical theft, an unlocked session, or a hostile radio environment next to an open SoftAP. Report real escalations (e.g. remote trigger of SoftAP, token leak, unauthenticated Wi‑Fi write) via the private channels above.

## Firmware images

Prefer Release assets that ship with SHA-256 checksums. Frozen images also contain MicroPython and other third-party code; see [docs/NOTICE](./NOTICE).

## Scope

This note covers the open firmware and DIY tree. The [flipbuddy.app](https://flipbuddy.app) backend is a separate system. Hobby firmware cannot fully stop physical theft, an unlocked device, or a hostile Wi‑Fi network.

Thanks for building carefully and for helping make FlipBuddy safer and easier for the next person.
