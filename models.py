from binascii import hexlify
from hashlib import sha256

import ujson as json
import utime as time
from esp32 import NVS
from rgb import FaceLEDNeoPixel
from util import str_to_epoch, suppress, time_iso


def to_serializable(obj):
    """Recursively convert objects to JSON serializable format."""
    if isinstance(obj, Face):
        return obj.to_dict()
    elif isinstance(obj, list):
        return [to_serializable(item) for item in obj]
    elif isinstance(obj, dict):
        return {key: to_serializable(value) for key, value in obj.items()}
    return obj


def from_serializable(data):
    """Recursively convert dictionaries"""
    if isinstance(data, list):
        return [from_serializable(item) for item in data]
    elif isinstance(data, dict):
        return {key: from_serializable(value) for key, value in data.items()}
    return data


class FileSystem:
    default = None
    running = None
    startup = None
    _namespace = "storage"
    _key = "data"

    def __init__(self):
        self.nvs = NVS(self._namespace)
        self.running = self.deepcopy(self.default)
        self.running["last_changed"] = time_iso(time.localtime())
        self.load()  # try to restore saved state

    def save(self):
        try:
            blob = json.dumps(to_serializable(self.running))
            self.nvs.set_blob(self._key, blob)
            self.nvs.commit()  # atomic
        except Exception as e:
            print(f"WARN: NVS save failed: {e}")
            return None
        else:
            self.startup = self.deepcopy(self.running)
        return self.startup

    def load(self):
        buffer = bytearray(4000)
        try:
            size = self.nvs.get_blob(self._key, buffer)
            if size > 0:
                blob = buffer[:size].decode("utf-8")
                loaded = json.loads(blob)
                self.startup = from_serializable(loaded)
                self.running = self.deepcopy(self.startup)
                print(f"INFO: Loaded {self._namespace} from NVS")
            else:
                self.startup = self.deepcopy(self.running)
        except OSError as e:
            print(f"WARN: NVS load failed ({e}), using defaults")
            self.startup = self.deepcopy(self.running)
        return self.startup

    def apply(self, config):
        self.running = self.deepcopy(config)
        self.running["last_changed"] = time_iso(time.localtime())
        return self.running

    def deepcopy(self, obj):
        if isinstance(obj, dict):
            return {k: self.deepcopy(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.deepcopy(i) for i in obj]
        return obj


class Transition:
    def __init__(self, next_state, condition=None, action=None):
        self.next_state = next_state
        self.condition = condition or (lambda: True)
        self.action = action or (lambda: None)  # must be callable returning coroutine


class BaseFSM:
    def __init__(self):
        self.state = None
        self.rules = {}

    async def run_fsm(self):
        """
        Run the finite state machine until no more transitions are possible.
        """
        while True:
            transitions = self.rules.get(self.state, [])
            if not transitions:
                break
            print(f"[FSM:{self.__class__.__name__}] State: {self.state}")
            for transition in transitions:
                if not await self._evaluate(transition.condition):
                    continue
                result = self._execute(transition.action)
                with suppress(TypeError):
                    await result
                old_state = self.state
                self.state = transition.next_state
                print(f"   → {self.state}  (from {old_state})")
                break
            else:
                break

    async def _evaluate(self, thing):
        result = thing() if callable(thing) else thing

        try:
            await result
            return True
        except TypeError:
            return bool(result)

    def _execute(self, thing):
        result = thing() if callable(thing) else thing
        return result


class Config(FileSystem):
    _namespace = "config"
    _key = "cfg"
    default = {
        "last_changed": "",
        "hash_type": "sha256",
        "hash_digest": "",
        "calibration": {
            "mean": "",
            "stddev": "",
        },
        "settings": {
            "ota_enabled": True,
            "orientation_check_frequency": 10,
            "remote_server": "https://api.flipbuddy.app",
            "ap_mode_enabled": True,
        },
        "device": {},
    }
    running = None
    startup = None
    _fs_name = "config"
    _fs_file = "startup_config"

    def __init__(self):
        super().__init__()
        # Integrity check: if the stored hash doesn't match what we compute from the
        # loaded data, treat the NVS entry as corrupt and reset to defaults.
        stored_hash = (self.startup or {}).get("hash_digest")
        self.apply(self.startup)
        if stored_hash and self.running.get("hash_digest") != stored_hash:
            print(
                "WARN: Config hash mismatch on load (possible NVS corruption) — resetting"
            )
            self.running = self.deepcopy(self.default)
            self.apply(self.running)
            self.save()

    def apply(self, config):
        self.running = self.deepcopy(config)
        self.running["hash_digest"] = self.hash_digest()
        self.running["last_changed"] = time_iso(time.localtime())
        return self.running

    def hash_digest(self):
        return hexlify(
            sha256(
                "||".join(
                    f"{key}@{value}" for key, value in self.running["settings"].items()
                ).encode("utf-8")
            ).digest()
        ).decode("utf-8")

    def apply_remote_config(self, config):
        try:
            running_device = self.running["device"]
            running_settings = self.running["settings"]
        except KeyError as e:
            self.running[e.args[0]] = {}

        try:
            if config.get("settings"):
                running_settings.update(
                    {
                        "orientation_check_frequency": config["settings"][
                            "orientation_check_frequency"
                        ],
                        "ota_enabled": config["settings"]["ota_enabled"],
                        "remote_server": config["settings"]["remote_server"],
                    }
                )

            if config.get("device"):
                running_device.update(
                    {
                        "config": {
                            "name": config["device"]["config"]["name"],
                            "date_updated": config["device"]["config"]["date_updated"],
                            "hash_algorithm": config["device"]["config"][
                                "hash_algorithm"
                            ],
                        },
                        "device": {
                            "name": config["device"]["name"],
                            "id": config["device"]["id"],
                        },
                    }
                )
        except:
            print(f"----> {config}")
            raise


class Face:
    def __init__(
        self,
        orientation,
        activity_name,
        led_pin,
        led_color,
        led_class,
        np_obj,
        activity_id,
        stop_face,
    ) -> None:
        self.orientation = orientation
        self.activity_name = activity_name
        self.activity_id = activity_id
        self.led_pin = led_pin
        self.led_color = led_color
        self.stop_face = stop_face
        self.tracking = False
        self.started = ""
        self.finished = ""
        self.last_checked = ""
        # setattr(Face, orientation, self)
        self.led = led_class(
            self.led_pin,
            np_obj,
            mode="blinking",
            hex_code=self.led_color,
            duration_ms=1024 * 1.618,
            cycles=1,
        )

    def __str__(self):
        """Readable string representation of the Face object."""
        return (
            f"Face({self.orientation}, {self.activity_name}, LED: {self.led_color}, "
            f"Tracking: {self.tracking} Started: {self.started!r}, "
            f"Finished: {self.finished!r})"
        )

    def to_dict(self):
        """Convert Face instance to a dictionary."""
        return {
            "orientation": self.orientation,
            "activity_name": self.activity_name,
            "activity_id": self.activity_id,
            "led_pin": self.led_pin,
            "led_color": self.led_color,
            "stop_face": self.stop_face,
            "tracking": self.tracking,
            "started": self.started,
            "finished": self.finished,
            "last_checked": self.last_checked,
        }

    @classmethod
    def from_dict(cls, data, led_class, np_obj):
        """Create Face instance from a dictionary."""
        instance = cls(
            orientation=data["orientation"],
            activity_name=data["activity_name"],
            activity_id=data.get("activity_id"),
            led_pin=data["led_pin"],
            led_color=data["led_color"],
            stop_face=data.get("stop_face"),
            led_class=led_class,
            np_obj=np_obj,
        )
        instance.tracking = data.get("tracking", False)
        instance.started = data.get("started", "")
        instance.finished = data.get("finished", "")
        instance.last_checked = data.get("last_checked", "")
        return instance


class Tracker(FileSystem):
    _namespace = "tracker"
    _key = "trk"
    # 'color': '', 'orientation': 'bottom', 'activity': '', 'stop_face': False, 'id': '', 'tracking': ''
    default = {
        "last_changed": "",
        "profile": "default",
        "hash_type": "sha256",
        "hash_digest": "",
        "active_face": "",
        "last_config_uploaded": "",
        "last_config_upload_result": "",
        # Empty activity map by design — assign faces via free dashboard (or edit source).
        "faces": [
            {
                "orientation": "back",
                "activity_name": "",
                "activity_id": "",
                "led_pin": "back",
                "led_color": "#EC1169",
                "tracking": False,
                "stop_face": False,
                "started": "",
                "finished": "",
                "last_checked": "",
            },
            {
                "orientation": "top",
                "activity_name": "",
                "activity_id": "",
                "led_pin": "top",
                "led_color": "#EC1169",
                "tracking": False,
                "stop_face": False,
                "started": "",
                "finished": "",
                "last_checked": "",
            },
            {
                "orientation": "front",
                "activity_name": "",
                "activity_id": "",
                "led_pin": "front",
                "led_color": "#EC1169",
                "tracking": False,
                "stop_face": False,
                "started": "",
                "finished": "",
                "last_checked": "",
            },
            {
                "orientation": "left",
                "activity_name": "",
                "activity_id": "",
                "led_pin": "left",
                "led_color": "#EC1169",
                "tracking": False,
                "stop_face": False,
                "started": "",
                "finished": "",
                "last_checked": "",
            },
            {
                "orientation": "right",
                "activity_name": "",
                "activity_id": "",
                "led_pin": "right",
                "led_color": "#EC1169",
                "tracking": False,
                "stop_face": False,
                "started": "",
                "finished": "",
                "last_checked": "",
            },
            {
                "orientation": "bottom",
                "activity_name": "",
                "activity_id": "",
                "led_pin": "bottom",
                "led_color": "#EC1169",
                "tracking": False,
                "stop_face": False,
                "started": "",
                "finished": "",
                "last_checked": "",
            },
            {
                "orientation": "front_cutout",
                "activity_name": "",
                "activity_id": "",
                "led_pin": "bottom",
                "led_color": "#11D6EC",
                "tracking": False,
                "stop_face": False,
                "started": "",
                "finished": "",
                "last_checked": "",
            },
            {
                "orientation": "back_cutout",
                "activity_name": "",
                "activity_id": "",
                "led_pin": "top",
                "led_color": "#11D6EC",
                "tracking": False,
                "stop_face": False,
                "started": "",
                "finished": "",
                "last_checked": "",
            },
            {
                "orientation": "out_margin",
                "activity_name": "error",
                "activity_id": "",
                "led_pin": "top",
                "led_color": "#FF0000",
                "tracking": False,
                "stop_face": False,
                "started": "",
                "finished": "",
                "last_checked": "",
            },
        ],
        "tracking_log": {},
    }

    running = None
    startup = None
    _fs_name = "tracker"
    _fs_file = "saved_tracker"
    active_face = ""
    previous_face = ""

    def __init__(self, np_obj):
        self.np_obj = np_obj
        super().__init__()
        # Integrity check using the assignment hash (see hash_digest for excluded transients).
        stored_hash = (self.startup or {}).get("hash_digest")
        self.apply(self.startup)
        self.parse_faces()
        if stored_hash and self.running.get("hash_digest") != stored_hash:
            print(
                "WARN: Tracker hash mismatch on load (possible NVS corruption) — resetting"
            )
            self.running = self.deepcopy(self.default)
            self.apply(self.running)
            self.parse_faces()
            self.save()

    def apply(self, config):
        self.running = self.deepcopy(config)
        self.running["faces"] = [
            f
            if isinstance(f, Face)
            else Face.from_dict(f, FaceLEDNeoPixel, self.np_obj)
            for f in self.running["faces"]
        ]
        self.running["hash_digest"] = self.hash_digest()
        self.running["last_changed"] = time_iso(time.localtime())
        self.active_face = self.running["active_face"]
        self.parse_faces()
        return self.running

    def hash_digest(self):
        # Only hash "assignment" / profile data from the server.
        # Exclude transient runtime fields so the hash is stable for change detection.
        transient = {"last_checked", "tracking", "started", "finished"}
        return hexlify(
            sha256(
                "||".join(
                    f"{key}@{value}"
                    for face_config in self.running["faces"]
                    for key, value in face_config.to_dict().items()
                    if key not in transient
                ).encode("utf-8")
            ).digest()
        ).decode("utf-8")

    def parse_faces(self):
        for face in self.running["faces"]:
            setattr(self, face.orientation, face)

    # This is to make sure we create ACL Anti Corruption Layer
    def apply_remote_config(self, config):
        for face in config["faces"]:
            # This is to only apply faces which have remote activity assigned
            if face["id"] or face["stop_face"]:
                face_obj = getattr(self, face["orientation"])
                face_obj.activity_name = face["activity"]
                face_obj.activity_id = face["id"]
                face_obj.led_color = (
                    face["color"] if face["color"] else face_obj.led_color
                )
                face_obj.stop_face = face["stop_face"]

    async def stop_all(self):
        for face in self.running["faces"]:
            await self.stop_tracking(face)

    def set_active_face(self, face_name):
        self.active_face = self.running["active_face"] = face_name

    async def stop_tracking(self, face):
        if face.tracking:
            face.tracking = False
            face.finished = time_iso(time.localtime())
            # Only log activities that lasted at least 1 minute
            duration = time.time() - str_to_epoch(face.started)
            if duration >= 60:
                self.tracking_log(face)
        print("stopping: " + str(face))
        await face.led.inactive()

    async def start_tracking(self, face):
        if face.orientation != self.active_face and self.active_face != "":
            print(
                f"\t--------- Flipped {self.active_face} -> {face.orientation} ----------"
            )
            previous_face = getattr(self, self.active_face)
            self.previous_face = previous_face.orientation
            await self.stop_tracking(previous_face)
        self.set_active_face(face.orientation)
        print("init: " + str(face))
        # face.led.active()
        face.last_checked = time_iso(time.localtime())
        if face.tracking:
            return
        face.tracking = True
        face.started = time_iso(time.localtime())

    def tracking_log(self, face: dict[str, str | bool]):
        log_entry = [
            face.orientation,
            face.activity_id,
            face.started,
            face.finished,
        ]
        if face.activity_id != "":
            try:
                face_log = self.running["tracking_log"][face.orientation]
            except KeyError:
                self.running["tracking_log"][face.orientation] = []
                face_log = self.running["tracking_log"][face.orientation]
            finally:
                face_log.append(",".join(log_entry))

    def upload_config(self, config):
        self.running["tracking_log"] = {}
        self.running["last_config_uploaded"] = time_iso(time.localtime())
        self.running["last_config_upload_result"] = "success"
        self.save()
        time.sleep_ms(100)
