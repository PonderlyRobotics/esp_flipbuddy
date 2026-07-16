import utime as time


class suppress:
    """Minimal stand-in for contextlib.suppress (not in stock MicroPython)."""

    def __init__(self, *exceptions):
        self.exceptions = exceptions

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return exc_type is not None and issubclass(exc_type, self.exceptions)


def time_iso(local_time):
    """Convert a time tuple to an ISO 8601 string format."""
    year, month, day, hour, minute, second, *_ = local_time
    return f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:{second:02d}Z"


def str_to_time(datetime_str):
    """Convert an ISO 8601 string format to a time tuple."""
    date_part, time_part = datetime_str.rstrip("Z").split("T")
    year, month, day = map(int, date_part.split("-"))
    hour, minute, second = map(int, time_part.split(":"))
    return (
        year,
        month,
        day,
        hour,
        minute,
        second,
        0,
        0,
        -1,
    )  # compatible with time.mktime()


def str_to_epoch(datetime_str):
    """Convert an ISO 8601 string to Unix timestamp (epoch time)."""
    return time.mktime(str_to_time(datetime_str))


def read_battery_voltage(
    adc,
    divider_ratio: float = 2.0,
    # TODO:Find a better way to do it right, this is band-aid for now
    diode_compensation: float = 0.5,  # BAT60B typical drop 0.28 + measured drop 0.22
    cutoff_voltage: float = 3.30,
    capacity_mah: int = 550,
    samples: int = 10,
):
    """
    Read LiPo battery voltage on Super Mini ESP32-S3.
    Measures via VBUS and compensates for BAT60B diode drop in software.
    """
    total_uv = 0
    for _ in range(samples):
        total_uv += adc.read_uv()
        time.sleep_ms(4)
    raw_uv = total_uv // samples

    # Convert + apply divider + diode compensation
    v = raw_uv * 1e-6 * divider_ratio + diode_compensation
    v = min(4.25, max(0.0, v))

    # Match curve for small 3.7V LiPo pouch cells
    curve = [
        (4.20, 100),
        (4.15, 96),
        (4.10, 91),
        (4.05, 86),
        (4.00, 80),
        (3.95, 74),
        (3.90, 68),
        (3.85, 61),
        (3.80, 53),
        (3.75, 45),
        (3.70, 37),
        (3.65, 28),
        (3.60, 20),
        (3.55, 13),
        (3.50, 8),
        (3.45, 4),
        (3.40, 2),
        (cutoff_voltage, 0),
    ]

    percent = 0.0
    for i in range(len(curve) - 1):
        v_high, p_high = curve[i]
        v_low, p_low = curve[i + 1]
        if v >= v_high:
            percent = p_high
            break
        if v >= v_low:
            percent = p_low + (p_high - p_low) * ((v - v_low) / (v_high - v_low))
            break

    percent = round(max(0.0, min(100.0, percent)), 1)
    remaining_mah = round(capacity_mah * percent / 100, 1)

    return {
        "raw_voltage_uv": raw_uv,
        "adjusted_voltage_v": round(v, 3),
        "battery_percentage": percent,
        "battery_capacity_remaining_mah": remaining_mah,
    }


def rgb_self_test(np):
    """Given a neopixel object of length n, do self test on LED cells."""
    n = np.n

    # cycle
    for i in range(4 * n):
        for j in range(n):
            np[j] = (0, 0, 0)
        np[i % n] = (255, 255, 255)
        np.write()
        time.sleep_ms(25)

    # bounce
    for i in range(4 * n):
        for j in range(n):
            np[j] = (0, 0, 128)
        if (i // n) % 2 == 0:
            np[i % n] = (0, 0, 0)
        else:
            np[n - 1 - (i % n)] = (0, 0, 0)
        np.write()
        time.sleep_ms(60)

    # fade in/out
    for i in range(0, 4 * 256, 8):
        for j in range(n):
            val = i & 0xFF if (i // 256) % 2 == 0 else 255 - (i & 0xFF)
            np[j] = (val, 0, 0)
        np.write()

    # clear
    for i in range(n):
        np[i] = (0, 0, 0)
    np.write()
