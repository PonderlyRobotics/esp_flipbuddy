import math

import uasyncio as asyncio
from util import suppress

CALIBRATION_RED = 1.0
CALIBRATION_GREEN = 1.0
CALIBRATION_BLUE = 1.0
MAX_INTENSITY = 50
DEFAULT_INTENSITY_LEVEL = 1

pinout = {
    "front": {"led": 0, "type": "neopixel"},
    "bottom": {"led": 1, "type": "neopixel"},
    "back": {"led": 2, "type": "neopixel"},
    "left": {"led": 3, "type": "neopixel"},
    "top": {"led": 4, "type": "neopixel"},
    "right": {"led": 5, "type": "neopixel"},
}


# -----------------------------------
# -- Base Class (Common Interface) --
# -----------------------------------
class FaceLEDBase:
    def __init__(
        self,
        face,
        hex_code="#11D6EC",
        intensity_level=1,
        max_intensity_steps=50,
        mode="static",
        lower_band_hex="#000000",
        duration_ms=1000,
        cycles=2,
    ):
        """
        Common initialization for a FaceLED.
        Subclasses will handle hardware-specific initialization.
        """
        # Save initial values (for reset)
        self._initial_hex_code = hex_code
        self._initial_intensity_level = intensity_level
        self._initial_lower_band_hex = lower_band_hex
        self._initial_duration_ms = duration_ms
        self._initial_cycles = cycles

        self.face = face
        self._hex_code = hex_code
        self._intensity_level = intensity_level
        self._lower_band_hex = lower_band_hex
        self._duration_ms = duration_ms
        self._cycles = cycles
        self.max_intensity_steps = max_intensity_steps
        self.max_brightness = self.calculate_max_brightness()
        self.mode = mode  # "static" or "blinking"
        self.task = None
        self.status = "INACTIVE"
        self._stop = False
        self.error_combo = []

        self.update_rgb_calibrated()

    def calculate_max_brightness(self):
        return int(1023 * self._intensity_level / self.max_intensity_steps)

    def hex_to_rgb(self, hex_code):
        hex_code = hex_code.lstrip("#")
        r = int(hex_code[0:2], 16)
        g = int(hex_code[2:4], 16)
        b = int(hex_code[4:6], 16)
        return r, g, b

    def update_rgb_calibrated(self):
        self.get_rgb_calibrated(self.hex_code, "upper")
        self.get_rgb_calibrated(self.lower_band_hex, "lower")

    def get_rgb_calibrated(self, hex_code, band):
        """
        Convert a hex code into calibrated values on a 0-1023 scale.
        """
        r, g, b = self.hex_to_rgb(hex_code)
        # e.g. zip("rgb", (r, g, b) -> [('r', 255), ('g', 87), ('b', 51)]
        rgb_scaled = {
            color: min(int(val * self.max_brightness / 255), 1023)
            for color, val in zip("rgb", (r, g, b))  # noqa: B905
        }
        for led_color, value in rgb_scaled.items():
            setattr(self, f"{led_color}_{band}_calibrated", value)

        return rgb_scaled["r"], rgb_scaled["g"], rgb_scaled["b"]

    def active(self):
        """Activate the LED effect according to the current mode."""
        self.status = "ACTIVE"
        if self.mode == "static":
            self.set_static_color()
        elif self.mode == "blinking":
            if not self.task:
                self.task = asyncio.create_task(self.periodic_blinking(2))

    async def inactive(self):
        """Deactivate the LED effect and turn it off.

        Safe against task cancellation: we may be called after (or while)
        the periodic task has been .cancel()'ed from cleanup paths.
        """
        self.status = "INACTIVE"
        self._stop = True
        if self.task:
            try:  # noqa: SIM105
                await self.task
            except asyncio.CancelledError:
                # Task was cancelled by us (or externally) - this is expected
                # during deep sleep / shutdown.
                pass
            self.task = None
        self.off()

    async def periodic_blinking(self, interval_seconds):
        """Continuously perform the blinking effect with a pause between cycles."""
        try:
            while not self._stop:
                await self.blinking_effect()
                if self._stop:
                    break
                await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            self._stop = True
            raise

    def reset_color(self):
        """Reset to the initial color and parameters."""
        self._hex_code = self._initial_hex_code
        self._intensity_level = self._initial_intensity_level
        self._lower_band_hex = self._initial_lower_band_hex
        self._duration_ms = self._initial_duration_ms
        self._cycles = self._initial_cycles
        self.max_brightness = self.calculate_max_brightness()
        self.update_rgb_calibrated()
        if self.mode == "static":
            self.set_static_color()

    # --- Properties ---
    @property
    def hex_code(self):
        return self._hex_code

    @hex_code.setter
    def hex_code(self, value):
        self._hex_code = value
        self.update_rgb_calibrated()
        if self.mode == "static":
            self.set_static_color()

    @property
    def intensity_level(self):
        return self._intensity_level

    @intensity_level.setter
    def intensity_level(self, value):
        self._intensity_level = value
        self.max_brightness = self.calculate_max_brightness()
        self.update_rgb_calibrated()
        if self.mode == "static":
            self.set_static_color()

    @property
    def lower_band_hex(self):
        return self._lower_band_hex

    @lower_band_hex.setter
    def lower_band_hex(self, value):
        self._lower_band_hex = value
        self.update_rgb_calibrated()

    @property
    def duration_ms(self):
        return self._duration_ms

    @duration_ms.setter
    def duration_ms(self, value):
        self._duration_ms = value

    @property
    def cycles(self):
        return self._cycles

    @cycles.setter
    def cycles(self, value):
        self._cycles = value

    # --- Abstract Methods (to be implemented by subclasses) ---
    def set_static_color(self):
        raise NotImplementedError(
            "set_static_color must be implemented in the subclass."
        )

    def off(self):
        raise NotImplementedError("off must be implemented in the subclass.")

    async def blinking_effect(self):
        raise NotImplementedError(
            "blinking_effect must be implemented in the subclass."
        )

    # --- Optional: Error LED (abstract, may be no-op for NeoPixel) ---
    def error_led(self, status=False, color="Blue"):
        """
        using the specified color; if False, clear the error LED list.
        After updating, the blinking parameters are updated.
        """
        raise NotImplementedError(
            "error_led must be implemented in the subclass if applicable."
        )


# -----------------------------------
# -- NeoPixel-Based Implementation --
# -----------------------------------
def ease_in_out_sin(t):
    # t should be a value between 0 and 1.
    return (1 - math.cos(math.pi * t)) / 2


def ease_in_out_quad(t):
    # Quadratic ease-in-out
    return t * t * (3 - 2 * t)


def ease_in_out_cubic(t):
    # Cubic ease-in-out
    return t * t * t * (t * (t * 6 - 15) + 10)


class FaceLEDNeoPixel(FaceLEDBase):
    def __init__(
        self,
        face,
        np_obj,
        hex_code="#11D6EC",
        intensity_level=32,
        max_intensity_steps=256,
        mode="static",
        lower_band_hex="#000000",
        duration_ms=1024,
        cycles=1,
    ):
        """
        np_obj: A neopixel.NeoPixel instance controlling all the LEDs.
        """
        super().__init__(
            face,
            hex_code,
            intensity_level,
            max_intensity_steps,
            mode,
            lower_band_hex,
            duration_ms,
            cycles,
        )
        self.np = np_obj
        # For NeoPixel, the pinout 'led' is an integer index.
        self.led_index = pinout[self.face]["led"]

    def set_static_color(self):
        if self.status == "ACTIVE":
            r_out = int(self.r_upper_calibrated / 1023 * 255)
            g_out = int(self.g_upper_calibrated / 1023 * 255)
            b_out = int(self.b_upper_calibrated / 1023 * 255)
            self.np[self.led_index] = (r_out, g_out, b_out)
            self.np.write()
        else:
            print("LED is inactive!")

    def off(self):
        self.np[self.led_index] = (0, 0, 0)
        self.np.write()

    def _get_error_led_rgb(self):
        start_color = (
            int(self.r_err_lower_calibrated / 1023 * 255),
            int(self.g_err_lower_calibrated / 1023 * 255),
            int(self.b_err_lower_calibrated / 1023 * 255),
        )
        end_color = (
            int(self.r_err_upper_calibrated / 1023 * 255),
            int(self.g_err_upper_calibrated / 1023 * 255),
            int(self.b_err_upper_calibrated / 1023 * 255),
        )
        return start_color, end_color

    async def _smooth_transition(
        self,
        start_color,
        end_color,
        duration_ms,
        error_start_color=None,
        err_end_color=None,
        steps=128,
    ):
        step_delay = duration_ms / steps
        for step in range(steps + 1):
            t = step / steps  # linear factor from 0 to 1
            eased_factor = ease_in_out_quad(
                t
            )  # apply non-linear easing - try quad for more appeal
            r_out = int(start_color[0] + eased_factor * (end_color[0] - start_color[0]))
            g_out = int(start_color[1] + eased_factor * (end_color[1] - start_color[1]))
            b_out = int(start_color[2] + eased_factor * (end_color[2] - start_color[2]))
            if self.error_combo:
                # error_start_color, err_end_color = self._get_error_led_rgb()
                err_r_out = int(
                    error_start_color[0]
                    + eased_factor * (err_end_color[0] - error_start_color[0])
                )
                err_g_out = int(
                    error_start_color[1]
                    + eased_factor * (err_end_color[1] - error_start_color[1])
                )
                err_b_out = int(
                    error_start_color[2]
                    + eased_factor * (err_end_color[2] - error_start_color[2])
                )
                for error_led in self.error_combo:
                    self.np[error_led] = (err_r_out, err_g_out, err_b_out)

            self.np[self.led_index] = (r_out, g_out, b_out)
            self.np.write()
            await asyncio.sleep_ms(int(step_delay))

    async def blinking_effect(self):
        half_duration = self.duration_ms // 2
        steps = 128
        # Precompute start and end colors in 0-255 space.
        start_color = (
            int(self.r_lower_calibrated / 1023 * 255),
            int(self.g_lower_calibrated / 1023 * 255),
            int(self.b_lower_calibrated / 1023 * 255),
        )
        end_color = (
            int(self.r_upper_calibrated / 1023 * 255),
            int(self.g_upper_calibrated / 1023 * 255),
            int(self.b_upper_calibrated / 1023 * 255),
        )
        err_start_color, err_end_color = None, None
        if self.error_combo:
            err_start_color, err_end_color = self._get_error_led_rgb()
        for _ in range(self.cycles):
            await self._smooth_transition(
                start_color,
                end_color,
                half_duration,
                err_start_color,
                err_end_color,
                steps,
            )
            await self._smooth_transition(
                end_color,
                start_color,
                half_duration,
                err_end_color,
                err_start_color,
                steps,
            )

    async def update_blinking_params(self):
        """Restart the blinking task to use updated error LED channels."""
        if self.task is not None:
            self._stop = True
            with suppress(asyncio.CancelledError):
                await self.task
            self.task = None
        self._stop = False
        self.task = asyncio.create_task(self.periodic_blinking(2))

    async def error_led(self, status=False, color_hex="#ff0040"):
        self.error_combo = []  # Clear previous error LED channels
        if status:
            for pin_tag, pin_cfg in pinout.items():
                if pin_tag not in (self.face,) and pin_cfg.get("type") == "neopixel":
                    self.error_combo.append(pin_cfg["led"])
        else:
            self.error_combo = []
        # self.get_rgb_calibrated(color_hex, "error")

        self.get_rgb_calibrated(self.lower_band_hex, "err_lower")
        self.get_rgb_calibrated(color_hex, "err_upper")
        await self.update_blinking_params()

    async def triad_led(self, view, status=False, color_hex="#ff0040"):
        print(f"triad_led called for {view}, status={status}")
        self.error_combo = []  # Clear previous error LED channels
        x = {
            "front_cutout": ("top", "right", "front"),
            "back_cutout": ("bottom", "left", "back"),
        }
        if status:
            triad_view = x.get(view, [])
            _ = [self.error_combo.append(pinout[face]["led"]) for face in triad_view]
            print(f"error_combo{self.error_combo}")
            # Start background blinking task
            if self.task:
                self._stop = True
                with suppress(asyncio.CancelledError):
                    await self.task
                self.task = None
            self._stop = False
            self.task = asyncio.create_task(self.periodic_blinking(2))
            print("triad task started")
        else:
            self.error_combo = []
            self._stop = True
            if self.task:
                with suppress(asyncio.CancelledError):
                    await self.task
                self.task = None
            print("triad task cancelled")

        self.get_rgb_calibrated(self.lower_band_hex, "err_lower")
        self.get_rgb_calibrated(color_hex, "err_upper")
        await self.update_blinking_params()

    async def periodic_blinking(self, interval_seconds):
        """Continuously perform the blinking effect with a pause between cycles."""
        try:
            while not self._stop:
                await self.blinking_effect()
                if self._stop:
                    break
                await asyncio.sleep(self.get_total_blink_time() * 2)
        except asyncio.CancelledError:
            self._stop = True
            # Let the cancellation propagate so that await task in the
            # cancellation site receives the CancelledError (as expected).
            raise

    def get_total_blink_time(self, extra_interval_seconds=0):
        """
        Returns the total time (in seconds) for one full blink effect.
        Calculation is based on:
          - duration_ms: total time for one blink cycle (fade in + fade out)
          - cycles: number of cycles in the effect
          - extra_interval_seconds: any additional sleep time after the blink effect (e.g., in periodic blinking)
        """
        total_transition_ms = self.cycles * self.duration_ms
        total_time_s = total_transition_ms / 1000.0 + extra_interval_seconds
        return total_time_s
