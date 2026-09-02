"""ESP32-S3 Super Mini overlay. Lives on LittleFS, not frozen."""

from micropython import const

# --- Identity ---  Which cube this overlay is; do not mix 427/504/602/S3 files.
HW_FAMILY = "supermini"
CHIP = "s3"
FIRMWARE_VERSION = "0.2.0"

# --- CPU / debug ---  Clock vs battery/heat; DEBUG logs; timer/wake ids if sleep is flaky.
CPU_FREQ_HZ = const(240000000)
DEBUG = False
TIMER_NUM = const(1)

# --- Pins / I2C ---  GPIO map for THIS PCB; copying another SoM's numbers breaks I2C/LEDs.
# Super Mini: MPU INT + I2C + NeoPixel data. There is no charger IC on this board.
MPU_INT_PIN = const(10)
I2C_SDA = const(11)
I2C_SCL = const(12)
NP_DATA_PIN = const(8)
NUM_LEDS = const(6)
ONBOARD_LED = const(48)

# --- LED VCC / VIN ADC ---  GPIO LED rail + VIN ADC for USB vs battery; Super Mini has no charger IC.
# NP_VCC must be high before pixels; VIN ADC is USB vs battery (no charger IC).
NP_VCC_PIN = const(7)
VIN_PIN = const(9)
USB_VOLTAGE_THRESHOLD = const(4.3)
BATTERY_FULL_V = const(4.2)
BATTERY_CUTOFF_V = const(2.8)
BATTERY_NOMINAL_V = const(3.7)
DEFAULT_BAT_CAPACITY = const(550)

# --- Product timings ---  Default sleep/upload/OTA cadence and blink; cloud config overrides.
DEFAULT_SLEEP_TIME = const(18)  # seconds
DEFAULT_UPLOAD_FRQ = const(300)  # seconds
DEFAULT_OTA = const(7)  # days
DEFAULT_INDICATOR_BLINK_DURATION = const(7000)  # ms
DEFAULT_INDICATOR_BLINK_CYCLE = const(1)
MAX_SLEEP_TIME = const(900)  # seconds
FACES = const(("front", "back", "left", "right", "top", "bottom"))

# --- SoftAP / pairing ---  Claim-portal SSID, dwell, PIN lockout; USB voltage starts AP.
SOFTAP_CAPTIVE_PORTAL_ENABLED = True
AP_SSID = "FlipBuddy"
AP_IP = "10.20.30.40"
AP_SUBNET = "255.255.255.0"
AP_DURATION_S = 300
SLEEP_MS = 18000
MAX_PIN_ATTEMPTS = 8
UNLOCK_IDLE_MS = 5 * 60 * 1000
PAIR_DURATION_S = 600

# --- OTA ---  Image-size brake and allowed hosts; too-big files are rejected to save the slot.
# Super Mini dual-OTA slot brake (0x1C0000 minus 64K); merged USB images run larger.
OTA_APP_MAX = 1769472
OTA_HOLD_COLOR = "#FFFFFF"
OTA_ALLOWED_HOSTS = ("api.flipbuddy.app", "raw.githubusercontent.com")
OTA_MIN_APP_SEGMENTS = 5
ESP_IMAGE_MAGIC = 0xE9

# --- API / credentials ---  Cloud URL allowlist, NVS keys, and sticker SoftAP PSK alphabet.
PAIRING_ALPHABET = "23456789ABCDEFGHJKMNPQRSTVWXYZ"
DEFAULT_API_URL = "https://api.flipbuddy.app/v1/api/"
DEFAULT_API = DEFAULT_API_URL
NVS_NS = "cred"
KEY = "json"
LAST_AP_KEY = "lastap"
AP_PSK_KEY = "appsk"
AP_PSK_ALPHABET = PAIRING_ALPHABET
AP_PSK_MIN_LEN = 8
AP_PSK_LEN = 8
ALLOWED_API_HOSTS = ("api.flipbuddy.app", "localhost", "127.0.0.1")
AP_PSK_FILE = "ap_psk.json"
API_URL_FILE = "api_url.txt"

# --- LED / RGB ---  Face-to-pixel map, brightness cap, and pairing/identify colors.
CALIBRATION_RED = 1.0
CALIBRATION_GREEN = 1.0
CALIBRATION_BLUE = 1.0
MAX_INTENSITY = 50
DEFAULT_INTENSITY_LEVEL = 1
TRIAD_FACES = {
    "front_cutout": ("right", "top", "front"),
    "back_cutout": ("left", "back", "bottom"),
}
ENABLE_SOFTAP_INDICATOR = True
SOFTAP_LED_COLOR = "#FFFF00"
IDENTIFY_GREEN = "#00FF00"

# --- Orientation / settle ---  Still-time before a face counts; gravity vectors match the IMU.
# Super Mini: SETTLE_MOVE_G (not LSB) and SETTLE_STILL_MS after the face lands.
SETTLE_STILL_MS = const(10000)  # wall-clock still-hold after landing on a face
SETTLE_HZ = 5
SETTLE_STABLE_SAMPLES = 50  # 10 s still at 5 Hz (host settle_step)
SETTLE_MOVE_G = 0.16  # Euclidean delta in g; motion restarts the dwell counter
SETTLE_TIMEOUT_S = 40  # headroom for rotation before the 10 s hold

# --- STA timings ---  How hard STA retries WiFi before sleep; shorter fails faster, saves battery.
SCAN_SETTLE_MS = const(250)
FAIL_FAST_MS = const(250)
SYNC_POLL_MS = const(50)
ASYNC_POLL_MS = const(100)
FAST_TIMEOUT_S = const(2)
DEFAULT_TIMEOUT_S = const(5)


def configure_board_hw():
    """LED VCC rail + VIN ADC. Super Mini has no charger IC."""
    from machine import ADC, Pin

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
