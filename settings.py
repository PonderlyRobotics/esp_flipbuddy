"""ESP32-S3 Super Mini overlay. Lives on LittleFS, not frozen."""

from micropython import const

# --- Identity ---  Super Mini overlay; do not copy another board's pin numbers.
HW_FAMILY = "supermini"
CHIP = "s3"
FIRMWARE_VERSION = "0.2.1"

# --- CPU / debug ---
CPU_FREQ_HZ = const(240000000)
DEBUG = False
TIMER_NUM = const(1)

# --- Pins / I2C ---  GPIO map for this Super Mini PCB.
MPU_INT_PIN = const(10)
I2C_SDA = const(11)
I2C_SCL = const(12)
NP_DATA_PIN = const(8)
NUM_LEDS = const(6)
ONBOARD_LED = const(48)

# --- LED VCC / VIN ADC ---  NP_VCC must be high before pixels; VIN ADC is USB vs battery.
NP_VCC_PIN = const(7)
VIN_PIN = const(9)
USB_VOLTAGE_THRESHOLD = const(4.3)
BATTERY_FULL_V = const(4.2)
BATTERY_CUTOFF_V = const(2.8)
BATTERY_NOMINAL_V = const(3.7)
DEFAULT_BAT_CAPACITY = const(550)

# --- Product timings ---
DEFAULT_SLEEP_TIME = const(18)  # seconds
DEFAULT_UPLOAD_FRQ = const(300)  # seconds
DEFAULT_OTA = const(7)  # days
DEFAULT_INDICATOR_BLINK_DURATION = const(7000)  # ms
DEFAULT_INDICATOR_BLINK_CYCLE = const(1)
MAX_SLEEP_TIME = const(900)  # seconds
FACES = const(("front", "back", "left", "right", "top", "bottom"))

# --- SoftAP / pairing ---
SOFTAP_CAPTIVE_PORTAL_ENABLED = True
AP_SSID = "FlipBuddy"
AP_IP = "10.20.30.40"
AP_SUBNET = "255.255.255.0"
AP_DURATION_S = 300
SLEEP_MS = 18000
MAX_PIN_ATTEMPTS = 8
UNLOCK_IDLE_MS = 5 * 60 * 1000
PAIR_DURATION_S = 600

# --- OTA ---  Super Mini dual-OTA slot brake (0x1C0000 minus 64K); merged USB images run larger.
OTA_APP_MAX = 1769472
OTA_HOLD_COLOR = "#FFFFFF"
OTA_ALLOWED_HOSTS = ("api.flipbuddy.app", "raw.githubusercontent.com")
OTA_MIN_APP_SEGMENTS = 5
ESP_IMAGE_MAGIC = 0xE9

# --- API / credentials ---  Cloud URL allowlist, NVS keys, and host SoftAP PSK alphabet.
PAIRING_ALPHABET = "23456789ABCDEFGHJKMNPQRSTVWXYZ"
DEFAULT_API_URL = "https://api.flipbuddy.app/v1/api/"
DEFAULT_API = DEFAULT_API_URL
NVS_NS = "cred"
KEY = "json"
LAST_AP_KEY = "lastap"
LIVE_OK_KEY = "liveok"
AP_PSK_KEY = "appsk"
AP_PSK_ALPHABET = PAIRING_ALPHABET
AP_PSK_MIN_LEN = 8
AP_PSK_LEN = 8
ALLOWED_API_HOSTS = ("api.flipbuddy.app", "localhost", "127.0.0.1")
AP_PSK_FILE = "ap_psk.json"
API_URL_FILE = "api_url.txt"

# --- LED / RGB ---  DIN 0..5: front, bottom, back, left, top, right.
CALIBRATION_RED = 1.0
CALIBRATION_GREEN = 1.0
CALIBRATION_BLUE = 1.0
MAX_INTENSITY = 50
DEFAULT_INTENSITY_LEVEL = 1
TX_DIM_FACTOR = 0.25
LED_PINOUT = {
    "front": {"led": 0, "type": "neopixel"},
    "bottom": {"led": 1, "type": "neopixel"},
    "back": {"led": 2, "type": "neopixel"},
    "left": {"led": 3, "type": "neopixel"},
    "top": {"led": 4, "type": "neopixel"},
    "right": {"led": 5, "type": "neopixel"},
}
# front_cutout: USB-C port + stop (top/front/right).
# back_cutout: SoftAP corner; yellow triad stays left/back/bottom.
TRIAD_FACES = {
    "front_cutout": ("top", "front", "right"),
    "back_cutout": ("left", "back", "bottom"),
}
USB_CUTOUT = "front_cutout"
SOFTAP_CUTOUT = "back_cutout"
ENABLE_SOFTAP_INDICATOR = True
SOFTAP_LED_COLOR = "#FFFF00"
IDENTIFY_GREEN = "#00FF00"

# --- Orientation / settle ---  SETTLE_MOVE_G is in g, not LSB.
SETTLE_STILL_MS = const(10000)  # wall-clock still-hold after landing on a face
SETTLE_HZ = 5
SETTLE_STABLE_SAMPLES = 50  # 10 s still at 5 Hz (host settle_step)
SETTLE_MOVE_G = 0.16  # Euclidean delta in g; motion restarts the dwell counter
SETTLE_TIMEOUT_S = 40  # headroom for rotation before the 10 s hold

# --- STA timings ---
SCAN_SETTLE_MS = const(250)
FAIL_FAST_MS = const(250)
SYNC_POLL_MS = const(50)
ASYNC_POLL_MS = const(100)
FAST_TIMEOUT_S = const(2)
DEFAULT_TIMEOUT_S = const(5)
PREVIEW_HTTP_MS = const(300)


def overlay_face_from_tilt(
    tilt_x,
    tilt_y,
    tilt_z,
    x,
    y,
    z,
    roll,
    pitch,
    margin=0.2,
    angle_margin=10,
):
    """Face names match LED_PINOUT. USB-up pose is front_cutout (stop)."""
    if (115 <= roll <= 145) and (-50 <= pitch <= -30):
        return USB_CUTOUT
    if (-60 <= roll <= -20) and (20 <= pitch <= 40):
        return SOFTAP_CUTOUT
    if -margin <= x <= margin and -margin <= y <= margin:
        return "left" if z > 0 else "right"
    if -margin <= y <= margin and -margin <= z <= margin:
        return "bottom" if x > 0 else "top"
    if -margin <= x <= margin and -margin <= z <= margin:
        return "front" if y > 0 else "back"
    if abs(tilt_x) > 90 or abs(tilt_y) > 90 or abs(tilt_z) > 90:
        return "out_margin"
    if abs(roll) > angle_margin or abs(pitch) > angle_margin:
        return "out_margin"
    return "unknown"


def apply_orientation_overlay():
    """Patch frozen rgb.pinout / mpu6050.face_from_tilt from this LittleFS file."""
    try:
        import rgb

        pinout = getattr(rgb, "pinout", None)
        if pinout is not None and pinout is not LED_PINOUT:
            pinout.clear()
            pinout.update(LED_PINOUT)
    except Exception:
        pass
    try:
        import mpu6050

        mpu6050.face_from_tilt = overlay_face_from_tilt
    except Exception:
        pass


def configure_board_hw():
    """LED VCC rail + VIN ADC. Also apply Super Mini face names onto frozen helpers."""
    from machine import ADC, Pin

    apply_orientation_overlay()
    np_vcc = Pin(NP_VCC_PIN, Pin.OUT, Pin.PULL_DOWN, drive=Pin.DRIVE_2)
    np_vcc.off()
    try:
        Pin(NP_DATA_PIN, Pin.OUT).value(0)
    except Exception:
        pass
    adc_vin = ADC(Pin(VIN_PIN), atten=ADC.ATTN_11DB)
    try:
        adc_vin.width(ADC.WIDTH_12BIT)
    except Exception:
        pass
    return np_vcc, adc_vin
