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

## Firmware images

Prefer Release assets that ship with SHA-256 checksums. Frozen images also contain MicroPython and other third-party code; see [docs/NOTICE](./NOTICE).

## Scope

This note covers the open firmware and DIY tree. The [flipbuddy.app](https://flipbuddy.app) backend is a separate system. Hobby firmware cannot fully stop physical theft, an unlocked device, or a hostile Wi‑Fi network.

Thanks for building carefully and for helping make FlipBuddy safer and easier for the next person.
