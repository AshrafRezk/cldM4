"""Signed artifact URLs. A bad signature is 404, never 403."""

from __future__ import annotations

import os
import time

from app import main
from app.artifacts import _b64


async def test_expired_tampered_and_traversal_are_404(make_client, install_key):
    store = main.artifacts
    artifact_id = store.save(b"hello", ".txt")
    good = store.sign(artifact_id)
    path = good.removeprefix(main.settings.public_base_url)
    _record, headers = install_key()

    async with make_client(headers) as client:
        ok = await client.get(path)
        assert ok.status_code == 200, ok.text
        assert ok.content == b"hello"
        assert ok.headers["x-content-type-options"] == "nosniff"
        assert "attachment" in ok.headers.get("content-disposition", "")

        tampered = await client.get(path + "x")
        assert tampered.status_code == 404

        old = int(time.time()) - 10
        sig = _b64(store._mac(artifact_id, old))
        gone = await client.get(f"/artifacts/{artifact_id}?exp={old}&sig={sig}")
        assert gone.status_code == 404

        traversal = await client.get(
            "/artifacts/../../.env", params={"exp": "9999999999", "sig": "nope"}
        )
        assert traversal.status_code == 404
        assert "403" not in traversal.text

        resigned = await client.post(f"/v1/artifacts/{artifact_id}/sign")
        assert resigned.status_code == 200
        assert resigned.json()["id"] == artifact_id


def test_janitor_removes_files_older_than_the_ttl():
    store = main.artifacts
    artifact_id = store.save(b"stale", ".txt")
    path = store._find(artifact_id)
    assert path is not None
    old = time.time() - (main.settings.artifact_ttl_hours * 3600) - 5
    os.utime(path, (old, old))
    assert store.sweep() >= 1
    assert store._find(artifact_id) is None
