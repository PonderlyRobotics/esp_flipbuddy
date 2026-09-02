"""ESP32-S3 Super Mini board overlay. Lives on LittleFS, not frozen."""

from micropython import const

HW_FAMILY = "supermini"
CHIP = "s3"

NP_VCC_PIN = const(7)
NP_DATA_PIN = const(8)
VIN_PIN = const(9)
MPU_INT_PIN = const(10)
I2C_SDA = const(11)
I2C_SCL = const(12)
NUM_LEDS = const(6)
USB_VOLTAGE_THRESHOLD = const(4.3)


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
