"""
* License: MIT
* Repository: https://github.com/metachris/micropython-captiveportal
* Author: Chris Hager <chris@linuxuser.at> / https://twitter.com/metachris

Built upon:
- https://github.com/metachris/micropython-captiveportal/blob/master/main.py

References:
- https://github.com/p-doyle/Micropython-DNSServer-Captive-Portal
- http://docs.micropython.org/en/latest/library/uasyncio.html
- https://github.com/peterhinch/micropython-async/blob/master/v3/README.md
- https://github.com/peterhinch/micropython-async/blob/master/v3/docs/TUTORIAL.md
- https://www.w3.org/Protocols/rfc2616/rfc2616-sec5.html#sec5

FlipBuddy SoftAP captive portal (USB face / AP mode):

- Status: time, battery, face map, activity records
- Unlock with PIN (factory: last 6 alnum of device_id, or custom NVS pin)
- Unlocked: Wi-Fi profiles, change PIN, LED self-test, lock
- Reset is always available (not PIN protected)
"""

import gc
import socket

import machine
import network
import uasyncio as asyncio
import utime as time
from credentials import (
    get_ap_unlock_pin,
    load_credentials,
    set_ap_unlock_pin,
    store_wifi_profile,
    wifi_profiles_public,
)
from models import BaseFSM, Transition
from network_helper import start_softap
from util import read_battery_voltage, rgb_self_test, suppress

AP_SSID = "FlipBuddy"
AP_IP = "10.20.30.40"
AP_SUBNET = "255.255.255.0"
USB_VOLTAGE_THRESHOLD = 4.3
_MAX_PIN_ATTEMPTS = 8
_UNLOCK_IDLE_MS = 5 * 60 * 1000


def _is_alnum_char(c):
    o = ord(c)
    return (48 <= o <= 57) or (65 <= o <= 90) or (97 <= o <= 122)


def _alnum_upper(s):
    return "".join(
        (c.upper() if 97 <= ord(c) <= 122 else c)
        for c in str(s or "")
        if _is_alnum_char(c)
    )


def _esc(s):
    """Minimal HTML escape for portal text."""
    return (
        str(s if s is not None else "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _clip(s, max_len=24):
    """Clip long labels with ellipsis (also CSS ellipsis on face cards)."""
    s = str(s if s is not None else "")
    if len(s) <= max_len:
        return s
    if max_len <= 1:
        return "…"
    return s[: max_len - 1] + "…"


def _fmt_iso(ts):
    """2026-07-21T15:39:24Z -> 2026-07-21 15:39:24"""
    t = str(ts or "").rstrip("Z")
    return t.replace("T", " ")


class DNSQuery:
    def __init__(self, data):
        self.data = data
        self.domain = ""
        try:
            tipo = (data[2] >> 3) & 15
            if tipo == 0:
                ini = 12
                lon = data[ini]
                while lon != 0:
                    self.domain += data[ini + 1 : ini + lon + 1].decode("utf-8") + "."
                    ini += lon + 1
                    lon = data[ini]
        except Exception:
            pass

    def response(self, ip):
        if not self.domain:
            return None
        packet = self.data[:2] + b"\x81\x80"
        packet += self.data[4:6] + self.data[4:6] + b"\x00\x00\x00\x00"
        packet += self.data[12:]
        packet += b"\xc0\x0c"
        packet += b"\x00\x01\x00\x01\x00\x00\x00\x3c\x00\x04"
        packet += bytes(int(x) for x in ip.split("."))
        return packet


def _parse_form(body_bytes):
    out = {}
    if not body_bytes:
        return out
    try:
        text = body_bytes.decode()
    except Exception:
        return out
    for pair in text.split("&"):
        if not pair:
            continue
        if "=" in pair:
            k, v = pair.split("=", 1)
        else:
            k, v = pair, ""
        out[_urldecode(k)] = _urldecode(v)
    return out


def _urldecode(s):
    s = s.replace("+", " ")
    res = []
    i = 0
    while i < len(s):
        c = s[i]
        if c == "%" and i + 2 < len(s):
            try:
                res.append(chr(int(s[i + 1 : i + 3], 16)))
                i += 3
                continue
            except ValueError:
                pass
        res.append(c)
        i += 1
    return "".join(res)


def _path_only(raw_path):
    if not raw_path:
        return "/"
    if "?" in raw_path:
        return raw_path.split("?", 1)[0]
    return raw_path


class ApModeFSM(BaseFSM):
    def __init__(
        self, config, tracker, adc_vin=None, existing_ap=None, np_obj=None, np_vcc=None
    ):
        self.config = config
        self.tracker = tracker
        self.adc_vin = adc_vin
        self.existing_ap = existing_ap
        self.np_obj = np_obj
        self.np_vcc = np_vcc
        self.state = "START_AP"
        self.ap = None
        self.flash_message = ""
        self.flash_ok = True
        creds = load_credentials() or {}
        self.device_id = creds.get("device_id") or ""
        self._expected_pin = get_ap_unlock_pin(self.device_id)
        self._unlocked = False
        self._unlock_at_ms = 0
        self._pin_attempts = 0
        self._led_test_busy = False
        self.rules = {
            "START_AP": [
                Transition("SERVE_WEB", lambda: True, lambda: self.start_ap()),
            ],
            "SERVE_WEB": [],
        }

    def _set_flash(self, msg, ok=True):
        """Portal banner: ok=True green, ok=False amber/red."""
        self.flash_message = msg
        self.flash_ok = bool(ok)

    def is_unlocked(self):
        if not self._unlocked:
            return False
        if (
            self._unlock_at_ms
            and time.ticks_diff(time.ticks_ms(), self._unlock_at_ms) > _UNLOCK_IDLE_MS
        ):
            self._unlocked = False
            self._unlock_at_ms = 0
            return False
        return True

    def _touch_unlock(self):
        if self._unlocked:
            self._unlock_at_ms = time.ticks_ms()

    def try_unlock(self, pin):
        if self._pin_attempts >= _MAX_PIN_ATTEMPTS:
            return (
                False,
                "Too many attempts — use Reset (top) or power-cycle, then try again.",
            )
        # Reload PIN in case it was changed earlier this session on another tab
        self._expected_pin = get_ap_unlock_pin(self.device_id)
        got = _alnum_upper(pin)
        if got == self._expected_pin:
            self._unlocked = True
            self._unlock_at_ms = time.ticks_ms()
            self._pin_attempts = 0
            print("AP settings unlocked")
            return True, "Unlocked"
        self._pin_attempts += 1
        return False, "Wrong PIN (%d/%d)" % (self._pin_attempts, _MAX_PIN_ATTEMPTS)

    def lock(self):
        self._unlocked = False
        self._unlock_at_ms = 0

    def change_pin(self, new_pin, confirm_pin):
        a = _alnum_upper(new_pin)
        b = _alnum_upper(confirm_pin)
        if a != b:
            return False, "New PIN and confirm do not match"
        if len(a) < 4 or len(a) > 16:
            return False, "PIN must be 4-16 letters/numbers"
        try:
            set_ap_unlock_pin(a)
            self._expected_pin = a
            self._touch_unlock()
            return True, "Unlock PIN updated"
        except Exception as e:
            return False, "PIN update failed: %s" % e

    def run_led_test(self):
        """Blocking LED self-test (same pattern as boot rgb_self_test)."""
        if self._led_test_busy:
            return False, "LED test already running"
        if self.np_obj is None:
            return False, "No LED hardware available"
        self._led_test_busy = True
        try:
            if self.np_vcc is not None:
                self.np_vcc.on()
                time.sleep_ms(50)
            rgb_self_test(self.np_obj)
            if self.np_vcc is not None:
                self.np_vcc.off()
            self._touch_unlock()
            return True, "LED test finished"
        except Exception as e:
            with suppress(Exception):
                if self.np_vcc is not None:
                    self.np_vcc.off()
            return False, "LED test failed: %s" % e
        finally:
            self._led_test_busy = False

    async def start_ap(self):
        print("Starting Access Point (SoftAP only)...")
        if self.existing_ap is not None:
            self.ap = self.existing_ap
            print("Using pre-started SoftAP", self.ap.ifconfig())
        else:
            await asyncio.sleep_ms(50)
            gc.collect()
            self.ap = start_softap(
                essid=AP_SSID,
                ip=AP_IP,
                subnet=AP_SUBNET,
                authmode=network.AUTH_OPEN,
                settle_ms=300,
                retries=3,
            )
            print("Network config:", self.ap.ifconfig())

        server = await asyncio.start_server(self.handle_http_connection, "0.0.0.0", 80)
        asyncio.create_task(server.wait_closed())
        asyncio.create_task(self.run_dns_server())
        print("Servers started mem_free=", gc.mem_free())

    def shutdown(self):
        if self.ap is not None:
            with suppress(Exception):
                self.ap.active(False)
            self.ap = None
        if self.np_vcc is not None:
            with suppress(Exception):
                self.np_vcc.off()
        gc.collect()

    async def handle_http_connection(self, reader, writer):
        try:
            data = await reader.readline()
            if not data:
                await writer.aclose()
                return
            request_line = data.decode()
            print("HTTP", request_line.strip())

            headers = {}
            while True:
                line = await reader.readline()
                if not line or line == b"\r\n":
                    break
                try:
                    decoded = line.decode()
                except Exception:
                    continue
                if ":" in decoded:
                    key, val = decoded.split(":", 1)
                    headers[key.strip().lower()] = val.strip()

            content_length = 0
            try:
                content_length = int(headers.get("content-length") or 0)
            except ValueError:
                content_length = 0
            body = b""
            if content_length > 0:
                if content_length > 2048:
                    content_length = 2048
                body = await reader.readexactly(content_length)

            parts = request_line.split()
            if len(parts) < 2:
                await writer.aclose()
                return

            method = parts[0].upper()
            path = _path_only(parts[1])
            form = _parse_form(body) if method == "POST" else {}
            run_led_after = False

            if path == "/" or path == "/index.html":
                await self._reply_html(writer, self.generate_html())
            elif path == "/unlock" and method == "POST":
                ok, msg = self.try_unlock(form.get("pin", ""))
                self._set_flash(msg, ok=ok)
                await self._reply_redirect(writer, "/")
            elif path == "/lock" and method == "POST":
                self.lock()
                self._set_flash("Locked", ok=True)
                await self._reply_redirect(writer, "/")
            elif path == "/pin" and method == "POST":
                await self._handle_pin_change(writer, form)
            elif path == "/led-test" and method == "POST":
                if not self.is_unlocked():
                    self._set_flash("Unlock first", ok=False)
                    await self._reply_redirect(writer, "/")
                else:
                    self._set_flash("LED test finished (see cube)", ok=True)
                    await self._reply_redirect(writer, "/")
                    run_led_after = True
            elif path == "/wifi" and method == "POST":
                await self._handle_wifi_post(writer, form)
            elif path == "/reset":
                # Always allowed (not PIN protected)
                await self._handle_reset(writer)
                return
            else:
                await self._reply_redirect(writer, "http://%s/" % AP_IP)

            await writer.drain()
            await writer.aclose()
            if run_led_after:
                ok, msg = self.run_led_test()
                self._set_flash(msg, ok=ok)
                print("LED test:", msg)
        except Exception as e:
            print("HTTP error:", e)
            with suppress(BaseException):
                await writer.aclose()

    async def _handle_pin_change(self, writer, form):
        if not self.is_unlocked():
            self._set_flash("Unlock first", ok=False)
            await self._reply_redirect(writer, "/")
            return
        ok, msg = self.change_pin(form.get("new_pin", ""), form.get("confirm_pin", ""))
        self._set_flash(msg, ok=ok)
        await self._reply_redirect(writer, "/")

    async def _handle_wifi_post(self, writer, form):
        if not self.is_unlocked():
            self._set_flash("Unlock first", ok=False)
            await self._reply_redirect(writer, "/")
            return
        try:
            profile = form.get("profile") or "default"
            ssid = form.get("ssid") or ""
            password = form.get("password") or ""
            hidden = form.get("hidden") in ("1", "on", "true", "yes")
            store_wifi_profile(profile, ssid, password, hidden=hidden)
            self._touch_unlock()
            self._set_flash(
                "Wi-Fi saved (ssid=%s). Flip off USB face (or Reset). "
                "Rejoin home Wi-Fi on this phone." % ssid,
                ok=True,
            )
        except Exception as e:
            self._set_flash("Save failed: %s" % e, ok=False)
        await self._reply_redirect(writer, "/")

    async def _handle_reset(self, writer):
        # Not PIN protected
        await writer.awrite(
            "HTTP/1.1 200 OK\r\nContent-type: text/plain\r\nConnection: close\r\n\r\n"
            "Resetting..."
        )
        await writer.drain()
        await writer.aclose()
        await asyncio.sleep(1)
        machine.reset()

    async def _reply_html(self, writer, html):
        await writer.awrite(
            "HTTP/1.1 200 OK\r\n"
            "Content-Type: text/html; charset=utf-8\r\n"
            "Connection: close\r\n\r\n" + html
        )

    async def _reply_redirect(self, writer, location):
        await writer.awrite(
            "HTTP/1.1 303 See Other\r\nLocation: %s\r\nConnection: close\r\n\r\n"
            % location
        )

    async def run_dns_server(self):
        udps = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udps.setblocking(False)
        udps.bind(("", 53))
        print("DNS on :53")
        while True:
            try:
                try:
                    data, addr = udps.recvfrom(512)
                except OSError:
                    await asyncio.sleep(0.1)
                    continue
                query = DNSQuery(data)
                response = query.response(AP_IP)
                if response:
                    udps.sendto(response, addr)
            except Exception as e:
                print("DNS error:", e)
                await asyncio.sleep(1)
        udps.close()

    def _device_datetime_label(self):
        y, mo, d, h, mi, s, *_ = time.localtime()
        return "%04d-%02d-%02d %02d:%02d:%02d UTC" % (y, mo, d, h, mi, s)

    def _battery_status(self):
        if self.adc_vin is None:
            return {"label": "n/a", "percent": None, "usb": False}
        try:
            batt = read_battery_voltage(self.adc_vin)
            v = batt["adjusted_voltage_v"]
            p = batt["battery_percentage"]
            usb = v > USB_VOLTAGE_THRESHOLD
            label = (
                ("USB · %.2f V · %.0f%%" % (v, p))
                if usb
                else ("%.0f%% · %.2f V" % (p, v))
            )
            return {"label": label, "percent": p, "usb": usb}
        except Exception:
            return {"label": "error", "percent": None, "usb": False}

    def _wifi_status_html(self):
        profiles = wifi_profiles_public()
        if not profiles:
            return '<p class="muted">No Wi-Fi profiles yet.</p>'
        rows = []
        for p in profiles:
            rows.append(
                "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
                % (
                    _esc(p["name"]),
                    _esc(_clip(p["ssid"], 24)),
                    "set" if p["has_password"] else "empty",
                    "yes" if p["hidden"] else "no",
                )
            )
        return (
            '<table class="wifi-table"><tr><th>Profile</th><th>SSID</th>'
            "<th>Password</th><th>Hidden</th></tr>%s</table>" % "".join(rows)
        )

    def _faces_html(self):
        """Fixed-size face cards; long activity names ellipsized."""
        parts = []
        for face in ("front", "back", "left", "right", "top", "bottom"):
            fo = getattr(self.tracker, face)
            name = fo.activity_name or "(none)"
            full = _esc(name)
            short = _esc(_clip(name, 22))
            color = fo.led_color or "#e5e7eb"
            parts.append(
                '<div class="face" style="background-color:%s" title="%s">'
                '<div class="face-orient">%s</div>'
                '<div class="face-act">%s</div>'
                "</div>" % (_esc(color), full, _esc(face), short)
            )
        return "".join(parts)

    def _empty_logs_html(self):
        """Empty activity-records block (plain double-quoted HTML, no %% formatting)."""
        return (
            '<div class="card">'
            '<p class="muted">No finished sessions stored yet.</p>'
            '<p class="muted">Sessions shorter than 1 minute are not saved.</p>'
            "</div>"
        )

    def _tracking_log_html(self):
        """
        tracking_log is {orientation: ["orient,activity_id,started,finished", ...]}
        Render as a readable table instead of raw CSV dumps.
        """
        from util import str_to_epoch

        log = self.tracker.running.get("tracking_log") or {}
        if not isinstance(log, dict) or not log:
            return self._empty_logs_html()

        rows = []
        # Stable face order, then any extra keys
        order = ["front", "back", "left", "right", "top", "bottom"]
        faces = [f for f in order if f in log] + [
            f for f in log.keys() if f not in order
        ]
        for face in faces:
            entries = log.get(face) or []
            if not isinstance(entries, list):
                entries = [entries]
            for ent in entries:
                # Skip non-string / non-CSV junk (avoids str(type) noise in the table)
                if not isinstance(ent, (str, bytes)):
                    continue
                if isinstance(ent, bytes):
                    try:
                        ent = ent.decode()
                    except Exception:
                        continue
                parts = ent.split(",")
                if len(parts) >= 4:
                    orient = parts[0]
                    act_id = parts[1]
                    started = parts[2]
                    finished = parts[3]
                elif len(parts) == 1 and not parts[0].strip():
                    continue
                else:
                    # Incomplete row: still show as one line, never a Python type repr
                    orient, act_id, started, finished = face, "-", "-", _clip(ent, 40)

                dur = ""
                try:
                    sec = int(str_to_epoch(finished) - str_to_epoch(started))
                    if sec < 0:
                        sec = 0
                    m, s = divmod(sec, 60)
                    h, m = divmod(m, 60)
                    if h:
                        dur = "%dh %02dm" % (h, m)
                    else:
                        dur = "%dm %02ds" % (m, s)
                except Exception:
                    dur = "-"

                rows.append(
                    "<tr>"
                    "<td>%s</td>"
                    '<td title="%s">%s</td>'
                    "<td>%s</td>"
                    "<td>%s</td>"
                    "<td>%s</td>"
                    "</tr>"
                    % (
                        _esc(orient or face),
                        _esc(act_id),
                        _esc(_clip(act_id or "-", 18)),
                        _esc(_fmt_iso(started)),
                        _esc(_fmt_iso(finished)),
                        _esc(dur),
                    )
                )

        if not rows:
            return self._empty_logs_html()

        return (
            '<div class="log-wrap"><table class="log-table">'
            "<thead><tr>"
            "<th>Face</th><th>Activity id</th><th>Started</th>"
            "<th>Finished</th><th>Duration</th>"
            "</tr></thead><tbody>%s</tbody></table></div>" % "".join(rows)
        )

    def generate_html(self):
        dt = self._device_datetime_label()
        batt = self._battery_status()
        bc = "batt-usb" if batt["usb"] else "batt-ok"
        if batt["percent"] is not None and not batt["usb"] and batt["percent"] < 20:
            bc = "batt-low"
        unlocked = self.is_unlocked()
        flash = self.flash_message or ""
        flash_ok = self.flash_ok
        self.flash_message = ""
        self.flash_ok = True
        if flash:
            fcls = "flash flash-ok" if flash_ok else "flash flash-err"
            flash_html = '<div class="%s">%s</div>' % (fcls, _esc(flash))
        else:
            flash_html = ""

        # Reset always available
        reset_btn = (
            '<a class="reset-btn" href="/reset" '
            "onclick=\"return confirm('Reset the device now?');\">"
            "Reset device</a>"
        )

        if unlocked:
            mid = (
                '<section class="card settings">'
                "<h2>Settings</h2>"
                '<p class="ok">Unlocked for this SoftAP session. '
                "Use only one phone on FlipBuddy while unlocked.</p>"
                "<h3>Wi-Fi</h3>"
                + self._wifi_status_html()
                + '<form method="POST" action="/wifi" class="form">'
                '<label>Profile <input name="profile" value="default"></label>'
                '<label>SSID <input name="ssid" required maxlength="32"></label>'
                '<label>Password <input name="password" type="password" maxlength="64" '
                'placeholder="blank keeps existing"></label>'
                '<label class="check"><input type="checkbox" name="hidden" value="1"> Hidden</label>'
                '<button type="submit">Save Wi-Fi</button>'
                "</form>"
                "<h3>Change unlock PIN</h3>"
                '<p class="muted">Factory default is the last 6 characters of device_id. '
                "Custom PIN is stored on the cube (NVS).</p>"
                '<form method="POST" action="/pin" class="form">'
                "<label>New PIN (4-16 letters/numbers)"
                '<input name="new_pin" type="password" maxlength="16" required></label>'
                "<label>Confirm new PIN"
                '<input name="confirm_pin" type="password" maxlength="16" required></label>'
                '<button type="submit">Update PIN</button>'
                "</form>"
                "<h3>Hardware</h3>"
                '<form method="POST" action="/led-test" class="form">'
                '<button type="submit">Run LED test</button>'
                "</form>"
                '<p class="muted">Same cycle / bounce / fade sequence as first boot.</p>'
                '<form method="POST" action="/lock" class="form">'
                '<button type="submit" class="secondary">Lock settings</button>'
                "</form>"
                "</section>"
            )
        else:
            mid = (
                '<section class="card">'
                "<h2>Unlock settings</h2>"
                "<p>Enter the setup PIN to change Wi-Fi, PIN, or run LED test.</p>"
                '<p class="muted">Default PIN = last 6 letters/numbers of '
                "<code>device_id</code> (flipbuddy.app / credentials.json), "
                "unless you already changed it. PIN is not shown on the cube.</p>"
                '<form method="POST" action="/unlock" class="form">'
                "<label>Setup PIN"
                '<input name="pin" type="password" maxlength="16" autocomplete="one-time-code" '
                'placeholder="4-16 characters" required>'
                "</label>"
                '<button type="submit">Unlock</button>'
                "</form>"
                "</section>"
            )

        faces = self._faces_html()
        logs = self._tracking_log_html()

        # Token replace (not %-format): battery labels contain "%" and must not
        # re-enter the template engine.
        page = """<!DOCTYPE html><html><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>FlipBuddy</title>
<style>
body{font-family:Arial,sans-serif;margin:0;background:#f6f7f9;color:#111}
.top-bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;justify-content:space-between;
padding:10px 14px;background:#111827;color:#f9fafb;font-size:14px}
.brand{font-weight:bold}.status{flex:1;display:flex;flex-wrap:wrap;gap:12px;justify-content:center}
.batt-ok{color:#86efac}.batt-low{color:#fca5a5}.batt-usb{color:#93c5fd}
.reset-btn{background:#dc2626;color:#fff;padding:8px 12px;border-radius:4px;text-decoration:none}
.content{max-width:720px;margin:0 auto;padding:16px}
.card{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:16px;margin:16px 0}
.card.settings{border-color:#86efac}
.flash{padding:10px;border-radius:8px;margin:12px 0}
.flash-ok{background:#ecfdf5;border:1px solid #6ee7b7}
.flash-err{background:#fef2f2;border:1px solid #fca5a5;color:#991b1b}
.ok{color:#047857;font-weight:600}
.form label{display:block;margin:10px 0}
.form input{display:block;width:100%;max-width:360px;margin-top:4px;padding:8px;box-sizing:border-box}
.form .check{display:flex;align-items:center;gap:8px}
.form .check input{width:auto}
.form button{margin-top:8px;margin-right:8px;padding:10px 14px;border:0;border-radius:6px;background:#2563eb;color:#fff}
.form button.secondary{background:#4b5563}
.wifi-table,.log-table{width:100%;border-collapse:collapse;font-size:13px}
.wifi-table td,.wifi-table th,.log-table td,.log-table th{
border:1px solid #e5e7eb;padding:6px 8px;text-align:left;vertical-align:top}
.wifi-table th,.log-table th{background:#f3f4f6}
.log-wrap{overflow-x:auto;background:#fff;border-radius:8px;border:1px solid #e5e7eb}
.faces{display:flex;flex-wrap:wrap;justify-content:center;gap:12px}
.face{box-sizing:border-box;width:132px;height:112px;padding:12px 10px;border:1px solid #ccc;
border-radius:8px;text-align:center;display:flex;flex-direction:column;justify-content:center;
align-items:center;overflow:hidden}
.face-orient{font-size:13px;font-weight:700;text-transform:capitalize;margin-bottom:6px;
max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.face-act{font-size:13px;line-height:1.25;max-width:100%;overflow:hidden;
text-overflow:ellipsis;white-space:nowrap}
.muted{color:#6b7280;font-size:13px}
.foot{margin:24px 0 8px;text-align:center}
h3{margin-top:1.4em}
</style></head><body>
<div class="top-bar">
  <span class="brand">FlipBuddy</span>
  <div class="status">
    <span>Time __DT__</span>
    <span class="__BC__">Battery __BATT__</span>
  </div>
  __RESET__
</div>
<div class="content">
  __FLASH__
  __MID__
  <h1>Cube faces</h1>
  <div class="faces">__FACES__</div>
  <h2>Activity records</h2>
  __LOGS__
  <p class="muted foot">SoftAP ~5 min · open network · HTTP only</p>
</div>
</body></html>"""
        return (
            page.replace("__DT__", _esc(dt))
            .replace("__BC__", _esc(bc))
            .replace("__BATT__", _esc(batt["label"]))
            .replace("__RESET__", reset_btn)
            .replace("__FLASH__", flash_html)
            .replace("__MID__", mid)
            .replace("__FACES__", faces)
            .replace("__LOGS__", logs)
        )

    async def run(self):
        await self.start_ap()
