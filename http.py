import network
import uasyncio as asyncio
import ujson as json
from credentials import load_credentials, store_credentials
from settings import PREVIEW_HTTP_MS
from util import suppress


class HttpAuthError:
    """401/403 from the API. Falsy so existing `if response:` paths stay failed."""

    def __init__(self, status):
        self.status = int(status)

    def __bool__(self):
        return False

    def __repr__(self):
        return "HttpAuthError(%s)" % self.status


def is_http_auth_error(value):
    return isinstance(value, HttpAuthError)


def http_result_for_status(code, body):
    """Map HTTP status to body, HttpAuthError (401/403), or None.

    204 (live_event) returns empty string so callers can tell success from failure.
    """
    s = str(code or "")
    if s in ("200", "201"):
        return body
    if s == "204":
        return ""
    if s in ("401", "403"):
        return HttpAuthError(int(s))
    return None


def _status_code_from_line(status_line):
    parts = (status_line or "").split()
    return parts[1] if len(parts) > 1 else ""


def parse_https_url(url):
    """Return (host, port, path) for https URLs, else None."""
    raw = str(url or "")
    if not raw.startswith("https://"):
        return None
    rest = raw[8:]
    if "/" in rest:
        host, path = rest.split("/", 1)
        path = "/" + path
    else:
        host, path = rest, "/"
    port = 443
    if ":" in host:
        host, port_s = host.split(":", 1)
        try:
            port = int(port_s)
        except ValueError:
            return None
    if not host:
        return None
    return host, port, path


def _sta_up():
    try:
        return bool(network.WLAN(network.STA_IF).isconnected())
    except Exception:
        return False


def _extra_headers(headers, skip):
    if not headers:
        return ""
    out = ""
    skip_l = skip
    for k, v in headers.items():
        if str(k).lower() in skip_l:
            continue
        out += "%s: %s\r\n" % (k, v)
    return out


class HttpSession:
    """One TLS socket per wake. HTTP/1.1 keep-alive, serial request/response."""

    def __init__(self):
        self.host = None
        self.port = 443
        self.reader = None
        self.writer = None

    def is_open(self):
        return self.writer is not None

    async def open(self, url, timeout=8):
        parsed = parse_https_url(url)
        if not parsed:
            print("Refusing non-HTTPS API URL")
            return False
        if not _sta_up():
            print("No network connection")
            return False
        host, port, _path = parsed
        if self.writer is not None and self.host == host and self.port == port:
            return True
        await self.close()
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port, ssl=True, server_hostname=host),
                timeout,
            )
        except Exception as e:
            print("HttpSession open failed:", e)
            return False
        self.host = host
        self.port = port
        self.reader = reader
        self.writer = writer
        return True

    async def close(self):
        writer = self.writer
        self.reader = None
        self.writer = None
        self.host = None
        self.port = 443
        if writer is None:
            return
        with suppress(Exception):
            writer.close()
        with suppress(Exception):
            await writer.wait_closed()

    async def request(self, method, url, headers=None, data=None, timeout=8):
        """Drain the full response before the next write. Returns body / HttpAuthError / None."""
        if not _sta_up():
            print("No network connection")
            return None
        parsed = parse_https_url(url)
        if not parsed:
            print("Refusing non-HTTPS API URL")
            return None
        host, port, path = parsed
        if self.writer is None or self.host != host or self.port != port:
            if not await self.open(url, timeout=timeout):
                return None
        body_bytes = b"" if data is None else json.dumps(data).encode("utf-8")
        req = "%s %s HTTP/1.1\r\n" % (method, path)
        req += "Host: %s\r\n" % host
        req += "Connection: keep-alive\r\n"
        req += "Content-Length: %d\r\n" % len(body_bytes)
        if data is not None:
            req += "Content-Type: application/json\r\n"
        req += _extra_headers(
            headers,
            ("host", "connection", "content-length", "content-type"),
        )
        req += "\r\n"
        try:
            self.writer.write(req.encode("utf-8"))
            await self.writer.drain()
            if body_bytes:
                chunk = 1024
                for i in range(0, len(body_bytes), chunk):
                    self.writer.write(body_bytes[i : i + chunk])
                    await self.writer.drain()
            code, body, conn_close = await self._read_response(timeout)
        except Exception as e:
            print("HttpSession request failed:", e)
            await self.close()
            return None
        if conn_close:
            await self.close()
        if code is None:
            return None
        return http_result_for_status(str(code), body)

    async def post_ff(self, url, data, headers=None, timeout_ms=None):
        """Preview POST on the warm socket. Write fully, then short read. Never reopen.

        Do not wrap request() in wait_for: cancelling mid-drain drops the POST
        before Cloudflare sees it (serial still printed success).
        """
        if self.writer is None or self.reader is None:
            return None
        if timeout_ms is None:
            timeout_ms = PREVIEW_HTTP_MS
        try:
            ms = int(timeout_ms)
        except (TypeError, ValueError):
            ms = PREVIEW_HTTP_MS
        if ms < 1:
            ms = 1
        timeout = max(ms / 1000.0, 0.05)
        parsed = parse_https_url(url)
        if not parsed:
            print("Refusing non-HTTPS API URL")
            return None
        host, port, path = parsed
        if self.host != host or self.port != port:
            return None
        body_bytes = b"" if data is None else json.dumps(data).encode("utf-8")
        req = "POST %s HTTP/1.1\r\n" % path
        req += "Host: %s\r\n" % host
        req += "Connection: keep-alive\r\n"
        req += "Content-Length: %d\r\n" % len(body_bytes)
        req += "Content-Type: application/json\r\n"
        req += _extra_headers(
            headers,
            ("host", "connection", "content-length", "content-type"),
        )
        req += "\r\n"
        try:
            self.writer.write(req.encode("utf-8"))
            await asyncio.wait_for(self.writer.drain(), timeout)
            if body_bytes:
                chunk = 1024
                for i in range(0, len(body_bytes), chunk):
                    self.writer.write(body_bytes[i : i + chunk])
                    await asyncio.wait_for(self.writer.drain(), timeout)
            code, body, conn_close = await self._read_response(timeout)
        except asyncio.TimeoutError:
            print("preview POST timeout")
            await self.close()
            return None
        except Exception as e:
            print("HttpSession post_ff failed:", e)
            await self.close()
            return None
        if conn_close:
            await self.close()
        if code is None:
            return None
        return http_result_for_status(str(code), body)

    async def _read_response(self, timeout):
        reader = self.reader
        if reader is None:
            return None, None, True
        status = ""
        content_length = -1
        conn_close = False
        chunked = False
        while True:
            line = await asyncio.wait_for(reader.readline(), timeout)
            if not line or line == b"\r\n":
                break
            if not status:
                status = line.decode()
            low = line.lower()
            if low.startswith(b"content-length:"):
                with suppress(BaseException):
                    content_length = int(line.split(b":", 1)[1].strip())
            if low.startswith(b"connection:") and b"close" in low:
                conn_close = True
            if low.startswith(b"transfer-encoding:") and b"chunked" in low:
                chunked = True
        code_s = _status_code_from_line(status)
        try:
            code = int(code_s) if code_s else 0
        except ValueError:
            code = 0
        # 204/205/304 have no body. Django live_event is 204 without Content-Length.
        # Treating that as "unknown length" used to read until timeout and close.
        no_body = code in (204, 205, 304)
        body = b""
        if no_body:
            if chunked:
                body = await self._read_chunked(timeout)
            elif content_length > 0:
                body = await asyncio.wait_for(
                    reader.readexactly(content_length), timeout
                )
        elif chunked:
            body = await self._read_chunked(timeout)
            conn_close = True
        elif content_length > 0:
            body = await asyncio.wait_for(reader.readexactly(content_length), timeout)
        elif content_length == 0:
            body = b""
        else:
            with suppress(Exception):
                rest = await asyncio.wait_for(reader.read(4096), timeout)
                if rest:
                    body += rest
            conn_close = True
        try:
            text = body.decode("utf-8")
        except Exception:
            text = body.decode("utf-8", "replace") if body else ""
        return code, text, conn_close

    async def _read_chunked(self, timeout):
        reader = self.reader
        body = b""
        while True:
            size_line = await asyncio.wait_for(reader.readline(), timeout)
            if not size_line:
                break
            size_s = size_line.strip().split(b";", 1)[0]
            if not size_s:
                continue
            size = int(size_s, 16)
            if size == 0:
                with suppress(Exception):
                    await asyncio.wait_for(reader.readline(), timeout)
                break
            body += await asyncio.wait_for(reader.readexactly(size), timeout)
            with suppress(Exception):
                await asyncio.wait_for(reader.readline(), timeout)
        return body


_cloud = None


def cloud_session():
    global _cloud
    if _cloud is None:
        _cloud = HttpSession()
    return _cloud


def reset_cloud_session():
    global _cloud
    _cloud = None


async def close_cloud_session():
    global _cloud
    if _cloud is None:
        return
    await _cloud.close()


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
    elif url.startswith("http://"):
        print("Refusing cleartext HTTP API")
        return None
    else:
        print("Refusing non-HTTPS API URL")
        return None

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

        code = _status_code_from_line(status_line)
        body = response[header_end + 4 :].decode()
        return http_result_for_status(code, body)

    except Exception as e:
        print("Async HTTP failed:", e)
        return None


async def async_rotate_device_token(url, session=None):
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

    if session is not None:
        response = await session.request("POST", url, headers=headers, data=None)
    else:
        response = await async_http_post(url, None, headers)  # No body for rotate
    if is_http_auth_error(response):
        return response
    if response:
        data = json.loads(response)
        if "new_device_token" in data:
            new_token = data["new_device_token"]
            print("Token rotated successfully!")
            store_credentials(credentials["device_id"], new_token)
            return new_token
        print("Token is still valid.")
    return None


async def async_post_request(url, data, extra_header=None, timeout=5, session=None):
    """Make an async POST request to the specified URL with the given data."""
    headers = {
        "Content-Type": "application/json",
    }
    if extra_header:
        headers.update(extra_header)

    if session is not None:
        response = await session.request(
            "POST", url, headers=headers, data=data, timeout=timeout
        )
    else:
        response = await async_http_post(url, data, headers, timeout)
    if is_http_auth_error(response):
        print("Request failed (auth %s)" % response.status)
        return response
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
    elif url.startswith("http://"):
        print("Refusing cleartext HTTP API")
        return None
    else:
        print("Refusing non-HTTPS API URL")
        return None

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
        code = _status_code_from_line(status_line)
        body = response[header_end + 4 :].decode("utf-8")
        result = http_result_for_status(code, body)
        if code not in ("200", "201"):
            print(f"GET failed ({status_line}):")
            print(body)
        return result

    except Exception as e:
        print("Async HTTP GET failed:", e)
        return None


async def get_request(url, params=None, extra_header=None):
    headers = extra_header or {}
    if params:
        q = "&".join(f"{k}={v}" for k, v in params.items())
        url += "?" + q if "?" not in url else "&" + q
    resp = await async_http_get(url, headers)
    if is_http_auth_error(resp):
        return resp
    if resp:
        try:
            return json.loads(resp)
        except Exception:
            return resp
    return None
