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
from models import BaseFSM, Transition
from network import AP_IF, WLAN
from util import suppress

IS_UASYNCIO_V3 = hasattr(asyncio, "__version__") and asyncio.__version__ >= (3,)

AP_SSID = "FlipBuddy"
AP_IP = "10.20.30.40"
AP_SUBNET = "255.255.255.0"


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
    def __init__(self, config, tracker):
        self.config = config
        self.tracker = tracker
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

    def generate_html(self):
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>FlipBuddy Activity Setup</title>
            <style>
                body { font-family: Arial, sans-serif; text-align: center; position: relative; }
                .face { margin: 20px; padding: 20px; border: 1px solid #ccc; display: inline-block; }
                .reset-btn { position: absolute; top: 10px; right: 10px; background: red; color: white; border: none; padding: 10px; cursor: pointer; font-size: 16px; }
            </style>
        </head>
        <body>
            <a href="/reset" class="reset-btn">&#x2716; Reset Device</a>
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
        </body>
        </html>
        """
        return html

    async def run(self):
        await self.start_ap()
