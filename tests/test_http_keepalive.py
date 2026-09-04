"""HTTP/1.1 keep-alive HttpSession (host pytest)."""

from __future__ import annotations

import asyncio
import time as real_time

import network

import http as http_mod


def _http_ok(body: bytes = b'{"ok":true}') -> bytes:
    return (
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: application/json\r\n"
        b"Content-Length: %d\r\n"
        % len(body)
        + b"Connection: keep-alive\r\n"
        + b"\r\n"
        + body
    )


class FakeWriter:
    def __init__(self):
        self.chunks = []
        self.closed = False

    def write(self, data):
        if isinstance(data, str):
            data = data.encode()
        self.chunks.append(bytes(data))

    async def drain(self):
        return None

    def close(self):
        self.closed = True

    async def wait_closed(self):
        return None

    @property
    def blob(self):
        return b"".join(self.chunks)


class FakeReader:
    def __init__(self, payload: bytes):
        self._data = payload
        self._i = 0

    async def readline(self):
        if self._i >= len(self._data):
            return b""
        j = self._data.find(b"\n", self._i)
        if j < 0:
            chunk = self._data[self._i :]
            self._i = len(self._data)
            return chunk
        j += 1
        chunk = self._data[self._i : j]
        self._i = j
        return chunk

    async def readexactly(self, n):
        chunk = self._data[self._i : self._i + n]
        self._i += n
        return chunk

    async def read(self, n):
        chunk = self._data[self._i : self._i + n]
        self._i += n
        return chunk


class HangReader:
    async def readline(self):
        await asyncio.sleep(5)
        return b""

    async def readexactly(self, n):
        await asyncio.sleep(5)
        return b""

    async def read(self, n):
        await asyncio.sleep(5)
        return b""


def _force_sta_up(monkeypatch):
    monkeypatch.setattr(network.WLAN, "isconnected", lambda self: True)


async def _session_get_then_post(monkeypatch, opens):
    _force_sta_up(monkeypatch)
    body1 = b'{"settings":{"active":true},"live_ok_until":1}'
    body2 = b'{"new_device_token":"x"}'
    reader = FakeReader(_http_ok(body1) + _http_ok(body2))
    writer = FakeWriter()

    async def fake_open(host, port, ssl=False, server_hostname=None):
        opens.append(
            {
                "host": host,
                "port": port,
                "ssl": ssl,
                "server_hostname": server_hostname,
            }
        )
        return reader, writer

    monkeypatch.setattr(asyncio, "open_connection", fake_open)
    sess = http_mod.HttpSession()
    got = await sess.request(
        "GET",
        "https://api.flipbuddy.app/v1/api/sensor/data/dev/",
        headers={"Device-ID": "dev", "Device-Token": "tok"},
    )
    posted = await sess.request(
        "POST",
        "https://api.flipbuddy.app/v1/api/sensor/data/",
        headers={"Device-ID": "dev", "Device-Token": "tok"},
        data={"faces": []},
    )
    return sess, writer, got, posted


def test_second_request_does_not_open_connection(monkeypatch):
    opens = []
    sess, writer, got, posted = asyncio.run(_session_get_then_post(monkeypatch, opens))
    try:
        assert got == '{"settings":{"active":true},"live_ok_until":1}'
        assert posted == '{"new_device_token":"x"}'
        assert len(opens) == 1
        assert opens[0]["ssl"] is True
        assert opens[0]["server_hostname"] == "api.flipbuddy.app"
        blob = writer.blob.decode()
        assert "HTTP/1.1" in blob
        assert "Connection: keep-alive" in blob
        assert blob.count("GET /v1/api/sensor/data/dev/ HTTP/1.1") == 1
        assert blob.count("POST /v1/api/sensor/data/ HTTP/1.1") == 1
        assert "HTTP/1.0" not in blob
        assert "Connection: close" not in blob
    finally:
        asyncio.run(sess.close())


def test_post_ff_returns_without_waiting_full_timeout(monkeypatch):
    _force_sta_up(monkeypatch)
    writer = FakeWriter()
    opens = []

    async def fake_open(host, port, ssl=False, server_hostname=None):
        opens.append(1)
        return HangReader(), writer

    monkeypatch.setattr(asyncio, "open_connection", fake_open)
    sess = http_mod.HttpSession()

    async def run():
        await sess.open("https://api.flipbuddy.app/v1/api/")
        t0 = real_time.monotonic()
        out = await sess.post_ff(
            "https://api.flipbuddy.app/v1/api/sensor/live_event/",
            {"type": "orientation_preview", "orientation": "left"},
            timeout_ms=80,
        )
        elapsed = real_time.monotonic() - t0
        return out, elapsed

    try:
        out, elapsed = asyncio.run(run())
        assert out is None
        assert elapsed < 1.0
        assert len(opens) == 1
        assert writer.closed is True
    finally:
        asyncio.run(sess.close())


def test_post_ff_does_not_open_if_session_closed(monkeypatch):
    _force_sta_up(monkeypatch)
    opens = []

    async def fake_open(host, port, ssl=False, server_hostname=None):
        opens.append(1)
        return FakeReader(_http_ok()), FakeWriter()

    monkeypatch.setattr(asyncio, "open_connection", fake_open)
    sess = http_mod.HttpSession()

    async def run():
        return await sess.post_ff(
            "https://api.flipbuddy.app/v1/api/sensor/live_event/",
            {"type": "orientation_preview"},
            timeout_ms=50,
        )

    out = asyncio.run(run())
    assert out is None
    assert opens == []


def test_async_http_post_stays_http10_close(monkeypatch):
    """Pairing / OTA keep Connection: close (not the wake keep-alive session)."""
    _force_sta_up(monkeypatch)
    writer = FakeWriter()
    body = b'{"ok":1}'
    reader = FakeReader(
        b"HTTP/1.0 200 OK\r\nContent-Length: %d\r\n\r\n" % len(body) + body
    )
    opens = []

    async def fake_open(host, port, ssl=False, server_hostname=None):
        opens.append(1)
        return reader, writer

    monkeypatch.setattr(asyncio, "open_connection", fake_open)
    out = asyncio.run(
        http_mod.async_http_post(
            "https://api.flipbuddy.app/v1/api/pairing/",
            {"chip_id": "abc"},
        )
    )
    assert out == '{"ok":1}'
    blob = writer.blob.decode()
    assert "HTTP/1.0" in blob
    assert "Connection: close" in blob
    assert writer.closed is True


def _http_204():
    """Django live_event success: 204, no Content-Length, keep-alive."""
    return b"HTTP/1.1 204 No Content\r\nConnection: keep-alive\r\n\r\n"


def test_post_ff_204_without_content_length_reuses_socket(monkeypatch):
    _force_sta_up(monkeypatch)
    writer = FakeWriter()
    reader = FakeReader(_http_204() + _http_204())
    sess = http_mod.HttpSession()
    sess.reader = reader
    sess.writer = writer
    sess.host = "api.flipbuddy.app"
    sess.port = 443
    url = "https://api.flipbuddy.app/v1/api/sensor/live_event/"

    async def run():
        await sess.post_ff(url, {"type": "orientation_preview", "orientation": "front"})
        still_after_first = sess.is_open()
        await sess.post_ff(url, {"type": "orientation_preview", "orientation": "right"})
        return still_after_first, sess.is_open(), writer.closed, writer.blob.count(b"POST ")

    still_after_first, still, closed, posts = asyncio.run(run())
    assert still_after_first is True
    assert still is True
    assert closed is False
    assert posts == 2


def test_post_ff_204_connection_close_drops_socket(monkeypatch):
    _force_sta_up(monkeypatch)
    writer = FakeWriter()
    sess = http_mod.HttpSession()
    sess.reader = FakeReader(b"HTTP/1.1 204 No Content\r\nConnection: close\r\n\r\n")
    sess.writer = writer
    sess.host = "api.flipbuddy.app"
    sess.port = 443

    async def run():
        await sess.post_ff(
            "https://api.flipbuddy.app/v1/api/sensor/live_event/",
            {"type": "orientation_preview", "orientation": "right"},
        )
        return sess.is_open()

    assert asyncio.run(run()) is False
    assert writer.closed is True


def test_cloud_session_singleton_reuses_instance():
    http_mod.reset_cloud_session()
    a = http_mod.cloud_session()
    b = http_mod.cloud_session()
    assert a is b
    http_mod.reset_cloud_session()
