import network
import uasyncio as asyncio
import ujson as json
from credentials import load_credentials, store_credentials
from util import suppress



async def async_http_post(url, data, headers=None, timeout=5):
    """Perform async HTTP POST request using asyncio streams."""
    print("Requesting URL:", url)

    # Check network
    wlan = network.WLAN(network.STA_IF)
    if not wlan.isconnected():
        print("No network connection")
        return None

    # Parse URL
    if url.startswith("https://"):
        proto = "https"
        url = url[8:]
    else:
        proto = "http"
        url = url[7:]

    if "/" in url:
        host, path = url.split("/", 1)
        path = "/" + path
    else:
        host = url
        path = "/"

    if ":" in host:
        host, port_str = host.split(":", 1)
        port = int(port_str)
    else:
        port = 443 if proto == "https" else 80

    print(f"Parsed: {proto}://{host}:{port}{path}")

    try:
        # Use asyncio.open_connection which handles non-blocking socket creation and SSL
        print(f"Connecting to {host}:{port}...")
        if proto == "https":
            # server_hostname is required for SNI
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port, ssl=True, server_hostname=host),
                timeout,
            )
        else:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout
            )

        print("Connected")

        # Prepare request (HTTP/1.0 to match urequests behavior)
        body_bytes = b"" if data is None else json.dumps(data).encode("utf-8")

        request_headers = f"POST {path} HTTP/1.0\r\n"
        request_headers += f"Host: {host}\r\n"
        request_headers += "Connection: close\r\n"
        request_headers += "Content-Type: application/json\r\n"
        request_headers += f"Content-Length: {len(body_bytes)}\r\n"

        if headers:
            for k, v in headers.items():
                if k.lower() not in [
                    "host",
                    "content-length",
                    "content-type",
                    "connection",
                ]:
                    request_headers += f"{k}: {v}\r\n"

        request_headers += "\r\n"

        print("Sending request headers...")
        writer.write(request_headers.encode("utf-8"))
        await writer.drain()

        print(f"Sending body ({len(body_bytes)} bytes)...")
        # Send body in chunks
        chunk_size = 1024
        for i in range(0, len(body_bytes), chunk_size):
            writer.write(body_bytes[i : i + chunk_size])
            await writer.drain()

        print("Request sent")

        # Read response
        print("Reading response...")
        response = b""
        content_length = -1

        while True:
            try:
                line = await asyncio.wait_for(reader.readline(), timeout)
                if not line or line == b"\r\n":
                    break
                response += line
                if line.lower().startswith(b"content-length:"):
                    with suppress(BaseException):
                        content_length = int(line.split(b":")[1].strip())
            except asyncio.TimeoutError:
                print("Header read timeout")
                break

        # Read body if Content-Length is known
        if content_length > 0:
            try:
                body = await asyncio.wait_for(
                    reader.readexactly(content_length), timeout
                )
                response += b"\r\n" + body
            except asyncio.TimeoutError:
                print("Body read timeout")
            except Exception as e:
                print("Body read error:", e)
        else:
            # Fallback for no Content-Length or chunked (simplified)
            try:
                rest = await asyncio.wait_for(reader.read(1024), timeout)
                response += b"\r\n" + rest
            except Exception:
                pass

        print("Response received, len:", len(response))

        writer.close()
        await writer.wait_closed()

        # Parse response
        if not response:
            return None

        header_end = response.find(b"\r\n\r\n")
        if header_end == -1:
            return None

        status_line = response[: response.find(b"\r\n")].decode()
        print("Status:", status_line)

        if "200" in status_line:
            return response[header_end + 4 :].decode()
        return None

    except Exception as e:
        print("Async HTTP failed:", e)
        return None


async def async_rotate_device_token(url):
    """Request a new token asynchronously if the current one has expired.

    Returns the new device_token string when the server issues one, else None.
    Caller should update any in-memory auth headers with that value.
    """
    credentials = load_credentials()
    if not credentials:
        print("No credentials found. Device is not registered.")
        return None

    headers = {
        "Device-ID": credentials["device_id"],
        "Device-Token": credentials["device_token"],
        "Content-Type": "application/json",
    }

    response = await async_http_post(url, None, headers)  # No body for rotate
    if response:
        data = json.loads(response)
        if "new_device_token" in data:
            new_token = data["new_device_token"]
            print("Token rotated successfully!")
            store_credentials(credentials["device_id"], new_token)
            return new_token
        print("Token is still valid.")
    return None


async def async_post_request(url, data, extra_header=None, timeout=5):
    """Make an async POST request to the specified URL with the given data."""
    headers = {
        "Content-Type": "application/json",
    }
    if extra_header:
        headers.update(extra_header)

    response = await async_http_post(url, data, headers, timeout)
    if response:
        print("Request successful!")
        print("Response:", response)
        return response  # Return the response body
    else:
        print("Request failed")
        return None


async def async_http_get(url, headers=None, timeout=8):
    print("GET requesting URL:", url)

    wlan = network.WLAN(network.STA_IF)
    if not wlan.isconnected():
        print("No network connection")
        return None

    # Parse URL (same as POST)
    if url.startswith("https://"):
        proto = "https"
        url = url[8:]
    else:
        proto = "http"
        url = url[7:]

    if "/" in url:
        host, path = url.split("/", 1)
        path = "/" + path
    else:
        host = url
        path = "/"

    if ":" in host:
        host, port_str = host.split(":", 1)
        port = int(port_str)
    else:
        port = 443 if proto == "https" else 80

    try:
        if proto == "https":
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port, ssl=True, server_hostname=host),
                timeout,
            )
        else:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout
            )

        request = f"GET {path} HTTP/1.0\r\n"
        request += f"Host: {host}\r\n"
        request += "Connection: close\r\n"
        if headers:
            for k, v in headers.items():
                if k.lower() not in ["host", "connection"]:
                    request += f"{k}: {v}\r\n"
        request += "\r\n"

        writer.write(request.encode("utf-8"))
        await writer.drain()

        # Read response (same logic as POST)
        response = b""
        content_length = -1
        while True:
            try:
                line = await asyncio.wait_for(reader.readline(), timeout)
                if not line or line == b"\r\n":
                    break
                response += line
                if line.lower().startswith(b"content-length:"):
                    with suppress(BaseException):
                        content_length = int(line.split(b":")[1].strip())
            except asyncio.TimeoutError:
                break

        if content_length > 0:
            body = await asyncio.wait_for(reader.readexactly(content_length), timeout)
            response += b"\r\n" + body
        else:
            rest = await asyncio.wait_for(reader.read(2048), timeout)
            response += b"\r\n" + rest

        writer.close()
        await writer.wait_closed()

        header_end = response.find(b"\r\n\r\n")
        if header_end == -1:
            return None

        status_line = response[: response.find(b"\r\n")].decode()
        print("GET Status:", status_line)
        if "200" in status_line:
            return response[header_end + 4 :].decode("utf-8")
        else:
            body = response[header_end + 4 :].decode("utf-8")
            print(f"GET failed ({status_line}):")
            print(body)
            return None

    except Exception as e:
        print("Async HTTP GET failed:", e)
        return None


async def get_request(url, params=None, extra_header=None):
    headers = extra_header or {}
    if params:
        q = "&".join(f"{k}={v}" for k, v in params.items())
        url += "?" + q if "?" not in url else "&" + q
    resp = await async_http_get(url, headers)
    if resp:
        try:
            return json.loads(resp)
        except Exception:
            return resp
    return None
