"""Unit tests for flt track CLI helpers."""

from __future__ import annotations

import json
import socket
import uuid

import pytest
import typer

from fleet.track import cli
from fleet.track.api import TrackAPIError
from fleet.track.paths import TrackPaths


def test_enable_persists_generated_device_id_before_provision_retry(
    tmp_path,
    monkeypatch,
):
    """A failed first provision must not make the next enable use a new device."""
    paths = TrackPaths.under(tmp_path)
    seen_device_ids: list[str] = []

    class FailingTrackAPIClient:
        def provision(self, device_id: str) -> dict:
            seen_device_ids.append(device_id)
            raise TrackAPIError("network down")

    monkeypatch.setattr(cli.TrackPaths, "default", lambda: paths)
    monkeypatch.setenv("FLEET_API_KEY", "test-api-key")
    monkeypatch.setattr(cli, "TrackAPIClient", FailingTrackAPIClient)
    monkeypatch.setattr(socket, "gethostname", lambda: "Dev Laptop")
    monkeypatch.setattr(
        cli.uuid,
        "uuid4",
        lambda: uuid.UUID("11111111-2222-3333-4444-555555555555"),
    )

    with pytest.raises(typer.Exit):
        cli.enable()

    config = json.loads(paths.config_file.read_text())
    assert config["device_id"] == "dev-laptop-11111111"

    monkeypatch.setattr(
        cli.uuid,
        "uuid4",
        lambda: uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
    )

    with pytest.raises(typer.Exit):
        cli.enable()

    assert seen_device_ids == ["dev-laptop-11111111", "dev-laptop-11111111"]
    assert json.loads(paths.config_file.read_text())["device_id"] == (
        "dev-laptop-11111111"
    )
