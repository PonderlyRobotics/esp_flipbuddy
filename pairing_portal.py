"""Unclaimed pairing captive portal (OSS v0.2.1).

SSID scan + hidden SSID + house password + pairing code (XXXX-XXXX).
HTTP :80 on WPA2 SoftAP. No PIN.
"""

import gc
import time

import network
from ap_mode import (
    DNSQuery,
    PORTAL_CSS,
    _esc,
    _parse_form,
    _path_only,
)
from credentials import (
    ap_ssid,
    get_ap_psk,
    load_api_url,
    store_credentials,
    store_wifi_profile,
)
from network_helper import start_softap, stop_softap
from pairing import (
    claim_body,
    claim_url,
    normalize_pairing_code,
    parse_claim_response,
    scan_table_rows,
)
from settings import AP_IP, AP_SUBNET, PAIR_DURATION_S
from util import suppress

HTTP_HINT = (
    "Stay on a desk you control. This page is HTTP after the WPA2 join."
)
# Dashboard / email show XXXX-XXXX; claim POST still sends 8 chars (normalize).
PAIR_EXTRA_CSS = (
    ".pw-wrap{position:relative;max-width:360px}"
    ".pw-wrap input{width:100%;max-width:none;padding-right:58px;box-sizing:border-box}"
    ".form button.pw-toggle{position:absolute;right:4px;top:50%;transform:translateY(-50%);"
    "margin:0;padding:4px 8px;background:transparent;color:#2563eb;font-size:13px}"
    "#pc{font-family:ui-monospace,Menlo,Consolas,monospace;letter-spacing:.08em;"
    "text-transform:uppercase}"
)
PAIR_SCRIPT = (
    "<script>(function(){"
    "var c=document.getElementById('pc');"
    "if(c)c.addEventListener('input',function(){"
    "var a=c.value.toUpperCase().replace(/[^A-Z0-9]/g,'').slice(0,8);"
    "c.value=a.length>4?a.slice(0,4)+'-'+a.slice(4):a});"
    "var b=document.getElementById('pwbtn'),p=document.getElementById('pw');"
    "if(b&&p)b.onclick=function(){var h=p.type==='password';"
    "p.type=h?'text':'password';b.textContent=h?'Hide':'Show'}})"
    "();</script>"
)


def generate_pairing_html(ssids, flash="", ssid_value="", hidden=False):
    """Pairing form using the same SoftAP chrome as maintenance (ap_mode)."""
    options = ['<option value="">Scanned networks</option>']
    for row in ssids or ():
        raw = (row.get("ssid") or "").strip()
        if not raw:
            continue
        name = _esc(raw)
        rssi = row.get("rssi")
        label = name if rssi is None else "%s (%s dBm)" % (name, rssi)
        sel = " selected" if raw == ssid_value else ""
        options.append('<option value="%s"%s>%s</option>' % (name, sel, label))
    if ssids:
        scan_block = (
            "<label>Network"
            '<select name="ssid">' + "".join(options) + "</select></label>"
        )
    else:
        scan_block = (
            '<p class="muted">No networks yet. Scan, or type the name below.</p>'
            '<input type="hidden" name="ssid" value="">'
        )
    hid = " checked" if hidden else ""
    if flash:
        ok = str(flash).startswith("ok:")
        text = str(flash)[3:].strip() if ok else str(flash)
        flash_html = '<div class="flash %s">%s</div>' % (
            "flash-ok" if ok else "flash-err",
            _esc(text),
        )
    else:
        flash_html = ""
    page = (
        "<!DOCTYPE html><html><head>"
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>FlipBuddy</title>"
        "<style>" + PORTAL_CSS + PAIR_EXTRA_CSS + "</style></head><body>"
        '<div class="top-bar">'
        '<span class="brand">FlipBuddy</span>'
        '<div class="status"><span>Pairing</span></div>'
        "</div>"
        '<div class="content">'
        + flash_html
        + '<section class="card">'
        "<h2>Pair this cube</h2>"
        "<p>Join home Wi-Fi and type the code from flipbuddy.app (XXXX-XXXX).</p>"
        '<p class="muted">' + _esc(HTTP_HINT) + "</p>"
        "<h3>Home Wi-Fi</h3>"
        '<form method="POST" action="/scan" class="form">'
        '<button type="submit" class="secondary">Scan networks</button>'
        "</form>"
        '<form method="POST" action="/pair" class="form">'
        + scan_block
        + "<label>Or type SSID"
        '<input name="ssid_typed" maxlength="32" value="'
        + _esc(ssid_value)
        + '"></label>'
        "<label>Password"
        '<span class="pw-wrap">'
        '<input id="pw" name="password" type="password" maxlength="64">'
        '<button type="button" class="pw-toggle" id="pwbtn" '
        'aria-label="Show password">Show</button></span></label>'
        '<label class="check"><input type="checkbox" name="hidden" value="1"'
        + hid
        + "> Hidden network</label>"
        "<h3>Pairing code</h3>"
        "<label>Code (XXXX-XXXX)"
        '<input id="pc" name="pairing_code" maxlength="9" placeholder="XXXX-XXXX"'
        ' autocapitalize="characters" autocomplete="one-time-code" required></label>'
        '<button type="submit">Join home Wi-Fi and pair</button>'
        '<p class="muted">BSSID only if the network is hidden and scan cannot see it.</p>'
        "<label>BSSID"
        '<input name="bssid" maxlength="17" placeholder="aa:bb:cc:dd:ee:ff"></label>'
        "</form></section>"
        '<p class="muted foot">WPA2 · HTTP · pairing</p>'
        "</div>" + PAIR_SCRIPT + "</body></html>"
    )
    return page


def parse_pair_form(form):
    """Return (code, wifi_dict) or raise ValueError."""
    code = normalize_pairing_code(form.get("pairing_code") or "")
    if not code:
        raise ValueError("Need the pairing code (XXXX-XXXX) from flipbuddy.app")
    ssid = (form.get("ssid_typed") or "").strip() or (form.get("ssid") or "").strip()
    if not ssid:
        raise ValueError("Pick or type a Wi-Fi name")
    wifi = {
        "ssid": ssid,
        "password": form.get("password") or "",
        "hidden": (form.get("hidden") in ("1", "on", "true", "yes")),
        "profile": "primary",
    }
    bssid = (form.get("bssid") or "").strip()
    if bssid:
        wifi["bssid"] = bssid
    return code, wifi


def _led_hw():
    """NeoPixel + VCC for unclaimed portal. Same bring-up as USB-face SoftAP."""
    from machine import Pin
    import neopixel
    from settings import NP_DATA_PIN, NUM_LEDS, configure_board_hw

    np_vcc, _adc = configure_board_hw()
    return neopixel.NeoPixel(Pin(NP_DATA_PIN), NUM_LEDS), np_vcc


class PairingPortal:
    def __init__(self, existing_ap=None):
        self.existing_ap = existing_ap
        self.ap = None
        self.flash = ""
        self.ssids = []
        self.result = None  # {code} when the form is accepted; wifi is NVS-only
        self._done = False
        self.np_obj = None
        self.np_vcc = None

    def _show_leds(self):
        from rgb import show_pairing_portal_leds

        try:
            if self.np_obj is None:
                self.np_obj, self.np_vcc = _led_hw()
            show_pairing_portal_leds(self.np_obj, self.np_vcc)
        except Exception as e:
            print("pairing leds:", e)

    def refresh_scan(self):
        try:
            sta = network.WLAN(network.STA_IF)
            was = sta.active()
            if not was:
                sta.active(True)
                time.sleep_ms(250)
            raw = sta.scan() or []
            self.ssids = scan_table_rows(raw)
        except Exception as e:
            print("pairing scan:", e)
            self.ssids = []

    async def start(self):
        import uasyncio as asyncio

        if self.existing_ap is not None:
            self.ap = self.existing_ap
        else:
            self.ap = start_softap(
                essid=ap_ssid(),
                ip=AP_IP,
                subnet=AP_SUBNET,
                authmode=network.AUTH_WPA_WPA2_PSK,
                password=get_ap_psk(),
                settle_ms=300,
                retries=3,
            )
        print("pairing SoftAP", ap_ssid(), self.ap.ifconfig())
        from credentials import psk_log_hint

        print("SoftAP PSK %s" % psk_log_hint(get_ap_psk()))
        self._show_leds()
        self.refresh_scan()
        server = await asyncio.start_server(self._http, "0.0.0.0", 80)
        asyncio.create_task(server.wait_closed())
        asyncio.create_task(self._dns())

    def shutdown(self):
        if self.ap is not None:
            with suppress(Exception):
                self.ap.active(False)
            self.ap = None
        if self.np_vcc is not None:
            with suppress(Exception):
                self.np_vcc.off()
        gc.collect()

    async def _dns(self):
        import uasyncio as asyncio
        import socket as smod

        sock = smod.socket(smod.AF_INET, smod.SOCK_DGRAM)
        sock.setblocking(False)
        sock.bind(("0.0.0.0", 53))
        while not self._done:
            try:
                data, addr = sock.recvfrom(256)
                q = DNSQuery(data)
                resp = q.response(AP_IP)
                if resp:
                    sock.sendto(resp, addr)
            except Exception:
                pass
            await asyncio.sleep_ms(50)
        with suppress(Exception):
            sock.close()

    async def _http(self, reader, writer):
        try:
            data = await reader.readline()
            if not data:
                await writer.aclose()
                return
            request_line = data.decode()
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
            if path == "/scan" and method == "POST":
                self.refresh_scan()
                self.flash = "ok: Scan complete"
            elif path == "/pair" and method == "POST":
                try:
                    code, wifi = parse_pair_form(form)
                    store_wifi_profile(
                        wifi.get("profile") or "primary",
                        wifi["ssid"],
                        wifi.get("password") or "",
                        hidden=bool(wifi.get("hidden")),
                    )
                    # House Wi-Fi is in NVS only. Claim POST must not see it.
                    self.result = {"code": code}
                    self._done = True
                    self.flash = "ok: Saved. Joining home Wi-Fi..."
                except Exception as e:
                    self.flash = str(e)
            html = generate_pairing_html(self.ssids, flash=self.flash)
            writer.write(
                b"HTTP/1.0 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n"
                b"Cache-Control: no-store\r\nConnection: close\r\n\r\n"
            )
            writer.write(html.encode())
            await writer.drain()
            await writer.aclose()
        except Exception as e:
            print("pairing HTTP:", e)
            with suppress(BaseException):
                await writer.aclose()


def _bringup():
    from credentials import get_ap_psk

    psk = get_ap_psk()
    ap = start_softap(
        essid=ap_ssid(),
        ip=AP_IP,
        subnet=AP_SUBNET,
        authmode=network.AUTH_WPA_WPA2_PSK,
        password=psk,
        settle_ms=300,
        retries=3,
    )
    from credentials import psk_log_hint

    print("pairing: SoftAP PSK %s" % psk_log_hint(psk))
    return ap


async def _finish_claim(result):
    """STA join + claim POST + store credentials. Returns True on success."""
    from http import async_http_post
    from network_helper import async_do_connect
    from credentials import load_credentials

    if not await async_do_connect():
        print("pairing: home Wi-Fi failed")
        return False
    cred = load_credentials() or {}
    api_base = load_api_url() or cred.get("api_url") or "https://api.flipbuddy.app/v1/api/"
    try:
        body = claim_body(result["code"])
    except ValueError as e:
        print("pairing: claim body", e)
        return False
    url = claim_url(api_base)
    raw = await async_http_post(url, body, timeout=12)
    parsed = parse_claim_response(raw)
    if not parsed:
        print("pairing: claim failed")
        print("pairing: url", url)
        return False
    store_credentials(parsed["device_id"], parsed["device_token"])
    if parsed.get("api_url"):
        from credentials import store_api_url

        try:
            store_api_url(parsed["api_url"])
        except ValueError:
            print("pairing: ignored api_url")
    print("pairing: claimed", parsed["device_id"])
    return True


async def _portal(ap):
    import uasyncio as asyncio

    fsm = PairingPortal(existing_ap=ap)
    await fsm.start()
    for i in range(PAIR_DURATION_S):
        if fsm._done:
            break
        await asyncio.sleep(1)
        if i % 30 == 0:
            print("pairing: t=%ds mem_free=%s" % (i, gc.mem_free()))
    result = fsm.result
    try:
        fsm.shutdown()
    except Exception as e:
        print("pairing shutdown", e)
    stop_softap()
    gc.collect()
    if not result:
        return False
    ok = await _finish_claim(result)
    if ok:
        try:
            import machine

            machine.reset()
        except Exception:
            return True
    return False


def run():
    """Entry from main.py for unclaimed cubes with ap_psk. SoftAP fail returns."""
    import uasyncio as asyncio
    from network_helper import prepare_for_softap

    while True:
        ap = None
        try:
            prepare_for_softap()
            ap = _bringup()
        except OSError as e:
            print("pairing: SoftAP failed:", e)
            stop_softap()
            return
        try:
            ok = asyncio.run(_portal(ap))
        except Exception as e:
            print("pairing: portal error:", e)
            stop_softap()
            gc.collect()
            return
        if ok:
            return
        print("pairing: retry after USB stay / new code")
        stop_softap()
        gc.collect()
