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
"""

import socket

import machine
import network
import uasyncio as asyncio
import utime as time
from models import BaseFSM, Transition
from network import AP_IF, WLAN
from util import read_battery_voltage, suppress

IS_UASYNCIO_V3 = hasattr(asyncio, "__version__") and asyncio.__version__ >= (3,)

AP_SSID = "FlipBuddy"
AP_IP = "10.20.30.40"
AP_SUBNET = "255.255.255.0"
# Match main.py: readings above this usually mean USB power on the VIN sense path.
USB_VOLTAGE_THRESHOLD = 4.3


class DNSQuery:
    def __init__(self, data):
        self.data = data
        self.domain = ""
        try:
            tipo = (data[2] >> 3) & 15  # Opcode bits
            if tipo == 0:  # Standard query
                ini = 12
                lon = data[ini]
                while lon != 0:
                    self.domain += data[ini + 1 : ini + lon + 1].decode("utf-8") + "."
                    ini += lon + 1
                    lon = data[ini]
        except Exception as e:
            print(f"-------- {e}")
        print("DNSQuery domain:" + self.domain)

    def response(self, ip):
        print(f"DNSQuery response: {self.domain} ==> {ip}")
        if self.domain:
            packet = self.data[:2] + b"\x81\x80"
            packet += (
                self.data[4:6] + self.data[4:6] + b"\x00\x00\x00\x00"
            )  # Questions and Answers Counts
            packet += self.data[12:]  # Original Domain Name Question
            packet += b"\xc0\x0c"  # Pointer to domain name
            packet += b"\x00\x01\x00\x01\x00\x00\x00\x3c\x00\x04"  # Response type, ttl and resource data length -> 4 bytes
            packet += bytes(int(x) for x in ip.split("."))  # 4bytes of IP
        return packet


class ApModeFSM(BaseFSM):
    def __init__(self, config, tracker, adc_vin=None):
        self.config = config
        self.tracker = tracker
        self.adc_vin = adc_vin
        self.state = "START_AP"
        self.ap = None
        self.server = None
        self.rules = {
            "START_AP": [
                Transition("SERVE_WEB", lambda: True, lambda: self.start_ap()),
            ],
            "SERVE_WEB": [],
        }

    async def start_ap(self):
        print("Starting Access Point...")
        self.ap = WLAN(AP_IF)
        self.ap.active(True)
        self.ap.ifconfig((AP_IP, AP_SUBNET, AP_IP, AP_IP))
        self.ap.config(essid=AP_SSID, authmode=network.AUTH_OPEN)
        print("Network config:", self.ap.ifconfig())

        # Start HTTP server
        server = await asyncio.start_server(self.handle_http_connection, "0.0.0.0", 80)
        asyncio.create_task(server.wait_closed())  # Keep it running

        # Start DNS server
        asyncio.create_task(self.run_dns_server())

        print("Servers started")

    async def handle_http_connection(self, reader, writer):
        try:
            # Get HTTP request line
            data = await reader.readline()
            if not data:
                await writer.aclose()
                return
            request_line = data.decode()
            addr = writer.get_extra_info("peername")
            print(f"Received {request_line.strip()} from {addr}")

            # Read headers (consume them)
            while True:
                line = await reader.readline()
                if not line or line == b"\r\n":
                    break

            # Parse request
            parts = request_line.split()
            if len(parts) >= 2:
                path = parts[1]

                if path == "/" or path == "/index.html":
                    response = (
                        "HTTP/1.1 200 OK\r\nContent-type: text/html\r\nConnection: close\r\n\r\n"
                        + self.generate_html()
                    )
                    await writer.awrite(response)
                elif path == "/reset":
                    print("Resetting device...")
                    response = "HTTP/1.1 200 OK\r\nContent-type: text/plain\r\nConnection: close\r\n\r\nResetting..."
                    await writer.awrite(response)
                    await writer.drain()
                    await writer.aclose()
                    # Small delay to ensure response is sent before reset
                    await asyncio.sleep(1)
                    machine.reset()
                    return  # Stop execution here
                else:
                    # Capture Portal Catch-all: Redirect to the main page
                    print(f"Redirecting {path} to http://{AP_IP}/")
                    response = f"HTTP/1.1 302 Found\r\nLocation: http://{AP_IP}/\r\nConnection: close\r\n\r\n"
                    await writer.awrite(response)

            await writer.drain()
            await writer.aclose()
        except Exception as e:
            print(f"HTTP Server Error: {e}")
            with suppress(BaseException):
                await writer.aclose()

    async def run_dns_server(self):
        udps = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udps.setblocking(False)
        udps.bind(("", 53))

        print("DNS Server listening on :53")

        while True:
            try:
                try:
                    data, addr = udps.recvfrom(512)
                except OSError:
                    await asyncio.sleep(0.1)
                    continue

                print(f"DNS query from {addr}")
                query = DNSQuery(data)
                response = query.response(AP_IP)
                if response:
                    udps.sendto(response, addr)
                    print(f"DNS -> {query.domain.strip('.')} resolved to {AP_IP}")

            except Exception as e:
                print("DNS server error:", e)
                await asyncio.sleep(1)

        udps.close()

    def _device_datetime_label(self):
        """Human-readable device RTC time (UTC wall clock when NTP has run)."""
        y, mo, d, h, mi, s, *_ = time.localtime()
        return f"{y:04d}-{mo:02d}-{d:02d} {h:02d}:{mi:02d}:{s:02d} UTC"

    def _battery_status(self):
        """Live ADC sample for the AP landing top bar."""
        if self.adc_vin is None:
            return {
                "label": "Battery: n/a",
                "percent": None,
                "voltage": None,
                "usb": False,
            }
        try:
            batt = read_battery_voltage(self.adc_vin)
            voltage = batt["adjusted_voltage_v"]
            percent = batt["battery_percentage"]
            usb = voltage > USB_VOLTAGE_THRESHOLD
            if usb:
                label = f"USB · {voltage:.2f} V · {percent:.0f}%"
            else:
                label = f"{percent:.0f}% · {voltage:.2f} V"
            return {
                "label": label,
                "percent": percent,
                "voltage": voltage,
                "usb": usb,
            }
        except Exception as e:
            print(f"Battery read error: {e}")
            return {
                "label": "Battery: error",
                "percent": None,
                "voltage": None,
                "usb": False,
            }

    def generate_html(self):
        dt_label = self._device_datetime_label()
        batt = self._battery_status()
        batt_label = batt["label"]
        batt_class = "batt-usb" if batt["usb"] else "batt-ok"
        if batt["percent"] is not None and not batt["usb"] and batt["percent"] < 20:
            batt_class = "batt-low"

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>FlipBuddy Activity Setup</title>
            <style>
                body {{ font-family: Arial, sans-serif; text-align: center; margin: 0; padding: 0; background: #f6f7f9; color: #1a1a1a; }}
                .top-bar {{
                    display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between;
                    gap: 8px 12px; padding: 10px 14px; background: #111827; color: #f9fafb;
                    font-size: 14px; box-sizing: border-box;
                }}
                .top-bar .brand {{ font-weight: bold; letter-spacing: 0.02em; }}
                .top-bar .status {{ display: flex; flex-wrap: wrap; gap: 10px 16px; align-items: center; flex: 1; justify-content: center; }}
                .top-bar .stat {{ white-space: nowrap; }}
                .top-bar .stat-label {{ opacity: 0.7; margin-right: 4px; font-size: 12px; text-transform: uppercase; }}
                .batt-ok {{ color: #86efac; }}
                .batt-low {{ color: #fca5a5; }}
                .batt-usb {{ color: #93c5fd; }}
                .reset-btn {{
                    background: #dc2626; color: white; border: none; padding: 8px 12px;
                    cursor: pointer; font-size: 14px; text-decoration: none; border-radius: 4px;
                    white-space: nowrap;
                }}
                .content {{ padding: 16px 12px 32px; }}
                .face {{ margin: 12px; padding: 20px; border: 1px solid #ccc; display: inline-block; border-radius: 8px; min-width: 120px; }}
                pre {{ text-align: left; display: inline-block; max-width: 95%; overflow: auto; background: #fff; padding: 12px; border-radius: 8px; border: 1px solid #e5e7eb; }}
            </style>
        </head>
        <body>
            <div class="top-bar">
                <span class="brand">FlipBuddy</span>
                <div class="status">
                    <span class="stat"><span class="stat-label">Time</span>{dt_label}</span>
                    <span class="stat {batt_class}"><span class="stat-label">Battery</span>{batt_label}</span>
                </div>
                <a href="/reset" class="reset-btn">&#x2716; Reset Device</a>
            </div>
            <div class="content">
            <h1>FlipBuddy Cube Faces</h1>
        """
        faces = ["front", "back", "left", "right", "top", "bottom"]
        for face in faces:
            face_obj = getattr(self.tracker, face)
            html += f"""
            <div class="face" style="background-color: {face_obj.led_color};">
                <h2>{face}</h2>
                <p>Activity: {face_obj.activity_name}</p>
            </div>
            """
        html += """
            <h2>Activity Records</h2>
            <pre>
        """
        tracking_log = self.tracker.running.get("tracking_log", {})
        for face, logs in tracking_log.items():
            html += f"{face}: {logs}\n"
        html += """
            </pre>
            </div>
        </body>
        </html>
        """
        return html

    async def run(self):
        await self.start_ap()
