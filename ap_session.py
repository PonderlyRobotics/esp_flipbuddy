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


AP_SSID = "FlipBuddy"
AP_IP = "10.20.30.40"
AP_SUBNET = "255.255.255.0"
AP_DURATION_S = 300
SLEEP_MS = 18000


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
    ap.active(True)
    ap.config(essid=AP_SSID, authmode=network.AUTH_OPEN)
    ap.ifconfig((AP_IP, AP_SUBNET, AP_IP, AP_IP))
    print("ap_session: SoftAP OK", ap.ifconfig(), "mem_free", gc.mem_free())
    return ap


async def _portal(ap):
    """Load portal modules only after SoftAP is up."""
    import uasyncio as asyncio
    from machine import ADC, Pin

    import neopixel
    from ap_mode import ApModeFSM
    from models import Config, Tracker

    np_obj = neopixel.NeoPixel(Pin(8), 6)
    np_vcc = Pin(7, Pin.OUT)
    np_vcc.off()
    adc_vin = ADC(Pin(9), atten=ADC.ATTN_11DB)
    try:
        adc_vin.width(ADC.WIDTH_12BIT)
    except Exception:
        pass

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

    print(
        "ap_session: portal up %ds - join WiFi '%s' -> http://%s/"
        % (AP_DURATION_S, AP_SSID, AP_IP)
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
