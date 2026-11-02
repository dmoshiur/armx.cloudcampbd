from __future__ import annotations

from tests.test_devices import _pair


def _device_headers(paired: dict) -> dict[str, str]:
    return {
        "X-Device-Id": paired["device"]["id"],
        "X-Device-Token": paired["device_token"],
    }


async def _active_screen_session(client, vip_headers) -> tuple[dict, str]:
    paired = await _pair(client, vip_headers)
    device_id = paired["device"]["id"]
    requested = await client.post(f"/api/devices/{device_id}/screen-share/start", headers=vip_headers)
    assert requested.status_code == 200, requested.text
    session_id = requested.json()["session_id"]
    decision = await client.post(
        f"/api/devices/{device_id}/consent-sessions/{session_id}/decision",
        headers=_device_headers(paired),
        json={"decision": "consent", "visible_indicator": True, "system_consent": True},
    )
    assert decision.status_code == 200, decision.text
    return paired, session_id


async def test_frames_require_active_visible_consent_and_jpeg(client, vip_headers):
    paired = await _pair(client, vip_headers)
    device_id = paired["device"]["id"]
    device_headers = _device_headers(paired)
    requested = await client.post(f"/api/devices/{device_id}/screen-share/start", headers=vip_headers)
    session_id = requested.json()["session_id"]
    endpoint = f"/api/devices/{device_id}/consent-sessions/{session_id}/frame"

    before_consent = await client.post(endpoint, headers=device_headers, content=b"\xff\xd8frame\xff\xd9")
    assert before_consent.status_code == 409

    await client.post(
        f"/api/devices/{device_id}/consent-sessions/{session_id}/decision",
        headers=device_headers,
        json={"decision": "consent", "visible_indicator": True, "system_consent": True},
    )
    wrong_type = await client.post(
        endpoint,
        headers={**device_headers, "Content-Type": "image/png"},
        content=b"not a jpeg",
    )
    assert wrong_type.status_code == 415
    malformed = await client.post(
        endpoint,
        headers={**device_headers, "Content-Type": "image/jpeg"},
        content=b"not a jpeg",
    )
    assert malformed.status_code == 400


async def test_owner_fetches_latest_ephemeral_frame_and_end_clears_it(client, vip_headers):
    paired, session_id = await _active_screen_session(client, vip_headers)
    device_id = paired["device"]["id"]
    endpoint = f"/api/devices/{device_id}/consent-sessions/{session_id}/frame"
    first = b"\xff\xd8first-frame\xff\xd9"
    latest = b"\xff\xd8latest-frame\xff\xd9"

    no_frame = await client.get(endpoint, headers=vip_headers)
    assert no_frame.status_code == 204
    upload_one = await client.post(
        endpoint,
        headers={**_device_headers(paired), "Content-Type": "image/jpeg"},
        content=first,
    )
    upload_two = await client.post(
        endpoint,
        headers={**_device_headers(paired), "Content-Type": "image/jpeg"},
        content=latest,
    )
    assert upload_one.status_code == 202
    assert upload_two.json()["sequence"] == upload_one.json()["sequence"] + 1

    fetched = await client.get(endpoint, headers=vip_headers)
    assert fetched.status_code == 200
    assert fetched.headers["content-type"] == "image/jpeg"
    assert fetched.headers["cache-control"] == "no-store, max-age=0"
    assert fetched.content == latest

    ended = await client.post(
        f"/api/devices/{device_id}/consent-sessions/{session_id}/device-end",
        headers=_device_headers(paired),
    )
    assert ended.status_code == 200
    after_end = await client.get(endpoint, headers=vip_headers)
    assert after_end.status_code == 409


async def test_device_token_cannot_read_mirror_frame(client, vip_headers):
    paired, session_id = await _active_screen_session(client, vip_headers)
    device_id = paired["device"]["id"]
    response = await client.get(
        f"/api/devices/{device_id}/consent-sessions/{session_id}/frame",
        headers=_device_headers(paired),
    )
    assert response.status_code == 401
