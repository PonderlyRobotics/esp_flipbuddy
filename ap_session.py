"""
Lightweight SoftAP maintenance session.

Entered from main.py early SoftAP gate after soft_reset when RTC mark FBAP1 is set
(USB face). boot.py is not used.

Bring SoftAP up with minimal imports first (more free RAM), then load the
captive portal stack (models, ap_mode, ...). SoftAP failure returns so main can
still BootFSM / track. Success runs the portal, stops SoftAP, then deepsleeps.
"""

import gc
import time

from settings import AP_DURATION_S, AP_IP, AP_SUBNET, SLEEP_MS


def _bringup_softap():
    """Enable SoftAP with the smallest possible import set."""
    import network

    gc.collect()
    print("ap_session: mem_free before WLAN", gc.mem_free())

    ap = network.WLAN(network.AP_IF)
    try:
        if ap.active():
            ap.active(False)
            time.sleep_ms(300)
            gc.collect()
    except OSError as e:
        print("ap_session: AP down warn", e)

    gc.collect()
    print("ap_session: mem_free before active", gc.mem_free())
    from credentials import get_ap_psk, maintenance_ssid

    psk = get_ap_psk()
    ssid = maintenance_ssid()
    ap.active(True)
    ap.config(essid=ssid, authmode=network.AUTH_WPA_WPA2_PSK, password=psk)
    ap.ifconfig((AP_IP, AP_SUBNET, AP_IP, AP_IP))
    print("ap_session: SoftAP OK", ap.ifconfig(), "mem_free", gc.mem_free())
    from credentials import psk_log_hint

    print("ap_session: SoftAP PSK %s" % psk_log_hint(psk))
    return ap


async def _portal(ap):
    """Load portal modules only after SoftAP is up."""
    import uasyncio as asyncio
    from machine import Pin

    import neopixel
    from ap_mode import ApModeFSM
    from models import Config, Tracker
    from settings import NP_DATA_PIN, NUM_LEDS, configure_board_hw

    np_vcc, adc_vin = configure_board_hw()
    np_obj = neopixel.NeoPixel(Pin(NP_DATA_PIN), NUM_LEDS)
    from rgb import (
        ENABLE_SOFTAP_INDICATOR,
        SOFTAP_LED_COLOR,
        set_cutout_triad_static,
    )

    if ENABLE_SOFTAP_INDICATOR:
        np_vcc.on()
        set_cutout_triad_static(np_obj, "back_cutout", SOFTAP_LED_COLOR)
    else:
        np_vcc.off()

    config = Config()
    tracker = Tracker(np_obj)
    fsm = ApModeFSM(
        config,
        tracker,
        adc_vin=adc_vin,
        existing_ap=ap,
        np_obj=np_obj,
        np_vcc=np_vcc,
    )
    await fsm.run()

    from credentials import maintenance_ssid

    print(
        "ap_session: portal up %ds - join WiFi '%s' (WPA2) -> http://%s/"
        % (AP_DURATION_S, maintenance_ssid(), AP_IP)
    )
    for i in range(AP_DURATION_S):
        await asyncio.sleep(1)
        if i % 30 == 0:
            print("ap_session: t=%ds mem_free=%s" % (i, gc.mem_free()))

    try:
        fsm.shutdown()
    except Exception as e:
        print("ap_session: shutdown", e)


def _stop_ap(ap):
    """Ensure SoftAP is off so next boot can own STA for NTP/upload."""
    try:
        if ap is not None:
            ap.active(False)
    except Exception:
        pass
    try:
        import network

        network.WLAN(network.AP_IF).active(False)
    except Exception:
        pass
    gc.collect()


def run():
    """Entry from main early gate. SoftAP fail returns; success deepsleeps."""
    ap = None
    try:
        ap = _bringup_softap()
    except OSError as e:
        print("ap_session: SoftAP failed:", e, "mem_free", gc.mem_free())
        print("ap_session: hand back to main.py")
        _stop_ap(ap)
        return

    try:
        import uasyncio as asyncio

        asyncio.run(_portal(ap))
    except Exception as e:
        print("ap_session: portal error:", e)
        _stop_ap(ap)
        gc.collect()
        return

    _stop_ap(ap)
    print("ap_session: portal done -> deepsleep %dms" % SLEEP_MS)
    try:
        from machine import deepsleep

        deepsleep(SLEEP_MS)
    except Exception:
        return
