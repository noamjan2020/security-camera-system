from __future__ import annotations

import asyncio
from dataclasses import dataclass
import importlib.util
import json
import logging
from threading import Event, Lock, Thread
import time
from typing import Any, Callable
from urllib.parse import urlparse
import uuid

import cv2
import numpy as np

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class IceServerSpec:
    urls: tuple[str, ...]
    username: str = ""
    credential: str = ""


@dataclass(frozen=True, slots=True)
class StreamRequest:
    session_id: str
    signaling_url: str
    ice_servers: tuple[IceServerSpec, ...]
    max_fps: int


def dependencies_available() -> bool:
    return all(importlib.util.find_spec(name) is not None for name in ("aiortc", "av", "websockets"))


def parse_stream_request(payload: dict[str, Any], default_fps: int = 15) -> StreamRequest:
    session_id = str(payload.get("session_id", "")).strip()
    try:
        parsed_id = uuid.UUID(session_id)
    except (ValueError, AttributeError) as exc:
        raise ValueError("session_id must be a UUID") from exc

    signaling_url = str(payload.get("signaling_url", "")).strip()
    parsed_url = urlparse(signaling_url)
    if parsed_url.scheme.lower() != "wss" or not parsed_url.hostname or parsed_url.username or parsed_url.password:
        raise ValueError("signaling_url must be an authenticated WSS endpoint")
    if parsed_url.fragment:
        raise ValueError("signaling_url must not contain a fragment")

    raw_servers = payload.get("ice_servers") or []
    if not isinstance(raw_servers, list) or len(raw_servers) > 8:
        raise ValueError("ice_servers must be a list with at most 8 entries")
    servers: list[IceServerSpec] = []
    for raw in raw_servers:
        if not isinstance(raw, dict):
            raise ValueError("Each ICE server must be an object")
        raw_urls = raw.get("urls")
        if isinstance(raw_urls, str):
            urls = [raw_urls]
        elif isinstance(raw_urls, list):
            urls = [str(value).strip() for value in raw_urls]
        else:
            raise ValueError("ICE server urls are required")
        if not urls or len(urls) > 8:
            raise ValueError("Each ICE server must have 1 to 8 URLs")
        for value in urls:
            if len(value) > 512 or not value.lower().startswith(("stun:", "stuns:", "turn:", "turns:")):
                raise ValueError("Invalid ICE server URL")
        username = str(raw.get("username", ""))[:512]
        credential = str(raw.get("credential", ""))[:1024]
        if any(value.lower().startswith(("turn:", "turns:")) for value in urls) and (not username or not credential):
            raise ValueError("TURN servers require temporary credentials")
        servers.append(IceServerSpec(tuple(urls), username, credential))

    max_fps = int(payload.get("max_fps", default_fps))
    if max_fps < 2 or max_fps > 30:
        raise ValueError("max_fps must be between 2 and 30")
    return StreamRequest(str(parsed_id), signaling_url, tuple(servers), max_fps)


class WebRtcPublisherManager:
    """Optional one-viewer WebRTC publisher, loaded only while Live View is open."""

    def __init__(
        self,
        frame_provider: Callable[[], np.ndarray | None],
        enabled_provider: Callable[[], bool],
        access_token: str,
        device_id: str,
        max_width: int = 1280,
        max_height: int = 720,
        max_session_seconds: int = 330,
    ):
        self.frame_provider = frame_provider
        self.enabled_provider = enabled_provider
        self.access_token = access_token
        try:
            self.device_id = str(uuid.UUID(device_id))
        except (ValueError, AttributeError) as exc:
            raise ValueError("WebRTC publisher device_id must be a UUID") from exc
        self.max_width = max(320, min(1920, int(max_width)))
        self.max_height = max(240, min(1080, int(max_height)))
        self.max_session_seconds = max(30, min(900, int(max_session_seconds)))
        self._lock = Lock()
        self._stop = Event()
        self._thread: Thread | None = None
        self._session_id: str | None = None
        self._last_error = ""

    @property
    def available(self) -> bool:
        return dependencies_available() and bool(self.access_token)

    @property
    def active(self) -> bool:
        with self._lock:
            return bool(self._thread and self._thread.is_alive())

    @property
    def session_id(self) -> str | None:
        with self._lock:
            return self._session_id

    @property
    def last_error(self) -> str:
        with self._lock:
            return self._last_error

    def start(self, payload: dict[str, Any]) -> StreamRequest:
        request = parse_stream_request(payload)
        if not self.available:
            raise RuntimeError("Optional WebRTC dependencies are not installed or cloud authentication is unavailable")
        self.stop()
        self._stop.clear()
        with self._lock:
            self._session_id = request.session_id
            self._last_error = ""
            self._thread = Thread(
                target=self._thread_main,
                args=(request,),
                name="webrtc-publisher",
                daemon=True,
            )
            self._thread.start()
        logger.info(
            "WebRTC publisher starting",
            extra={"session_id": request.session_id, "ice_server_groups": len(request.ice_servers), "max_fps": request.max_fps},
        )
        return request

    def stop(self, session_id: str | None = None) -> bool:
        with self._lock:
            if session_id is not None and self._session_id != session_id:
                return False
            thread = self._thread
        self._stop.set()
        import threading
        if thread and thread.is_alive() and thread.ident != threading.get_ident():
            thread.join(timeout=8)
        with self._lock:
            if self._thread is thread:
                self._thread = None
                self._session_id = None
        if thread:
            logger.info("WebRTC publisher stopped", extra={"session_id": session_id})
        return bool(thread)

    def _thread_main(self, request: StreamRequest) -> None:
        try:
            asyncio.run(self._run(request))
        except Exception as exc:
            with self._lock:
                self._last_error = str(exc)
            logger.exception("WebRTC publisher failed", extra={"session_id": request.session_id})
        finally:
            with self._lock:
                if self._session_id == request.session_id:
                    self._session_id = None
                self._thread = None

    async def _run(self, request: StreamRequest) -> None:
        from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
        from av import VideoFrame
        from websockets.asyncio.client import connect

        manager = self

        class CameraVideoTrack(VideoStreamTrack):
            async def recv(self):  # type: ignore[no-untyped-def]
                pts, time_base = await self.next_timestamp()
                started = time.monotonic()
                frame = manager.frame_provider()
                if frame is None:
                    frame = np.zeros((360, 640, 3), dtype=np.uint8)
                height, width = frame.shape[:2]
                scale = min(1.0, manager.max_width / max(width, 1), manager.max_height / max(height, 1))
                if scale < 1.0:
                    frame = cv2.resize(frame, (max(2, int(width * scale)), max(2, int(height * scale))), interpolation=cv2.INTER_AREA)
                video = VideoFrame.from_ndarray(frame, format="bgr24")
                video.pts = pts
                video.time_base = time_base
                remaining = (1.0 / request.max_fps) - (time.monotonic() - started)
                if remaining > 0:
                    await asyncio.sleep(remaining)
                return video

        rtc_servers = [
            RTCIceServer(urls=list(server.urls), username=server.username or None, credential=server.credential or None)
            for server in request.ice_servers
        ]
        pc = RTCPeerConnection(RTCConfiguration(iceServers=rtc_servers))
        pc.addTrack(CameraVideoTrack())
        offer_lock = asyncio.Lock()
        offer_sent = False
        started_at = time.monotonic()

        @pc.on("connectionstatechange")
        async def connection_state_changed() -> None:
            logger.info(
                "WebRTC connection state changed",
                extra={"session_id": request.session_id, "connection_state": pc.connectionState},
            )
            if pc.connectionState in {"failed", "closed"}:
                manager._stop.set()

        async def wait_ice_complete() -> None:
            deadline = time.monotonic() + 12
            while pc.iceGatheringState != "complete" and time.monotonic() < deadline:
                await asyncio.sleep(0.05)

        async def send_offer(socket: Any) -> None:
            nonlocal offer_sent
            async with offer_lock:
                if offer_sent or manager._stop.is_set():
                    return
                offer = await pc.createOffer()
                await pc.setLocalDescription(offer)
                await wait_ice_complete()
                description = pc.localDescription
                if description is None:
                    raise RuntimeError("WebRTC local offer was not created")
                message = {
                    "sessionId": request.session_id,
                    "type": "offer",
                    "requestId": uuid.uuid4().hex,
                    "payload": {"type": description.type, "sdp": description.sdp},
                }
                await socket.send(json.dumps(message, separators=(",", ":")))
                offer_sent = True
                logger.info("WebRTC offer sent", extra={"session_id": request.session_id})

        headers = {"Authorization": f"Bearer {self.access_token}"}
        async with connect(
            request.signaling_url,
            additional_headers=headers,
            compression=None,
            max_size=32 * 1024,
            max_queue=8,
            open_timeout=12,
            ping_interval=20,
            ping_timeout=20,
        ) as socket:
            await socket.send(json.dumps({
                "sessionId": request.session_id,
                "type": "join",
                "requestId": uuid.uuid4().hex,
                "payload": {"role": "publisher", "deviceId": self.device_id},
            }, separators=(",", ":")))
            logger.info("WebRTC publisher joined signaling", extra={"session_id": request.session_id})

            while not self._stop.is_set():
                if not self.enabled_provider():
                    logger.warning("WebRTC stopped because camera privacy state changed", extra={"session_id": request.session_id})
                    break
                if time.monotonic() - started_at > self.max_session_seconds:
                    logger.info("WebRTC session reached time limit", extra={"session_id": request.session_id})
                    break
                try:
                    raw = await asyncio.wait_for(socket.recv(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                if not isinstance(raw, str) or len(raw) > 32 * 1024:
                    raise RuntimeError("Invalid signaling payload")
                message = json.loads(raw)
                if message.get("sessionId") != request.session_id:
                    continue
                signal_type = str(message.get("type", ""))
                if signal_type == "joined" and int(message.get("peers", 0)) >= 2:
                    await send_offer(socket)
                elif signal_type == "peer_joined":
                    await send_offer(socket)
                elif signal_type == "answer":
                    payload = message.get("payload") or {}
                    if payload.get("type") != "answer" or not isinstance(payload.get("sdp"), str):
                        raise RuntimeError("Invalid WebRTC answer")
                    await pc.setRemoteDescription(RTCSessionDescription(sdp=payload["sdp"], type="answer"))
                    logger.info("WebRTC answer applied", extra={"session_id": request.session_id})
                elif signal_type == "peer_left":
                    logger.info("WebRTC viewer left", extra={"session_id": request.session_id})
                    break

            try:
                await socket.send(json.dumps({
                    "sessionId": request.session_id,
                    "type": "leave",
                    "requestId": uuid.uuid4().hex,
                }, separators=(",", ":")))
            except Exception:
                logger.debug("WebRTC leave signal could not be sent", exc_info=True)
        await pc.close()
