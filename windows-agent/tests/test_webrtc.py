from __future__ import annotations

import pytest

from homeguard_agent.webrtc import IceServerSpec, parse_stream_request


def valid_payload():
    return {
        "session_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "signaling_url": "wss://signal.example.com/ws",
        "ice_servers": [
            {"urls": ["stun:stun.example.com:3478"]},
            {
                "urls": ["turns:turn.example.com:5349?transport=tcp"],
                "username": "temporary-user",
                "credential": "temporary-secret",
            },
        ],
        "max_fps": 15,
    }


def test_stream_request_accepts_secure_short_lived_configuration():
    request = parse_stream_request(valid_payload())
    assert request.session_id == "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    assert request.signaling_url.startswith("wss://")
    assert request.max_fps == 15
    assert request.ice_servers[1] == IceServerSpec(
        ("turns:turn.example.com:5349?transport=tcp",),
        "temporary-user",
        "temporary-secret",
    )


def test_stream_request_rejects_insecure_signaling():
    payload = valid_payload()
    payload["signaling_url"] = "ws://signal.example.com"
    with pytest.raises(ValueError, match="WSS"):
        parse_stream_request(payload)


def test_stream_request_rejects_turn_without_credentials():
    payload = valid_payload()
    payload["ice_servers"] = [{"urls": "turn:turn.example.com:3478"}]
    with pytest.raises(ValueError, match="credentials"):
        parse_stream_request(payload)


def test_stream_request_rejects_unbounded_fps():
    payload = valid_payload()
    payload["max_fps"] = 120
    with pytest.raises(ValueError, match="max_fps"):
        parse_stream_request(payload)
