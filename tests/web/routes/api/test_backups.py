"""Tests for backup API routes."""

from datetime import UTC, datetime

import pytest

from anibridge.app.web.routes.api import backups as backups_api_module
from anibridge.app.web.services.backup_service import BackupMeta


class _FakeBackupService:
    def __init__(self) -> None:
        self.restored: list[tuple[str, str]] = []
        self.raw_requests: list[tuple[str, str]] = []

    def list_backups(self, profile: str) -> list[BackupMeta]:
        return [
            BackupMeta(
                filename=f"{profile}.json",
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
                size_bytes=10,
                entries=1,
                user="Tester",
                age_seconds=0.0,
            )
        ]

    async def restore_backup(self, profile: str, filename: str) -> None:
        self.restored.append((profile, filename))

    def read_backup_raw(self, profile: str, filename: str):
        self.raw_requests.append((profile, filename))
        return {"profile": profile, "filename": filename}


@pytest.fixture
def backup_service(monkeypatch: pytest.MonkeyPatch) -> _FakeBackupService:
    service = _FakeBackupService()
    monkeypatch.setattr(backups_api_module, "get_backup_service", lambda: service)
    return service


@pytest.fixture
def backup_client(api_client_for):
    return api_client_for(backups_api_module, "/api/backups")


def test_list_backups_route_serializes_service_response(
    backup_client,
    backup_service: _FakeBackupService,
) -> None:
    listed = backup_client.get("/api/backups/default")

    assert listed.status_code == 200
    assert listed.json()["backups"][0]["filename"] == "default.json"


@pytest.mark.parametrize(
    (
        "method",
        "path",
        "json_body",
        "expected_json",
        "expected_restored",
        "expected_raw_requests",
    ),
    [
        pytest.param(
            "post",
            "/api/backups/default/restore",
            {"filename": "backup.json"},
            None,
            [("default", "backup.json")],
            [],
            id="restore",
        ),
        pytest.param(
            "get",
            "/api/backups/default/raw/backup.json",
            None,
            {"profile": "default", "filename": "backup.json"},
            [],
            [("default", "backup.json")],
            id="raw-preview",
        ),
    ],
)
def test_backup_action_routes_delegate_to_service(
    backup_client,
    backup_service: _FakeBackupService,
    method: str,
    path: str,
    json_body: dict[str, str] | None,
    expected_json: dict[str, str] | None,
    expected_restored: list[tuple[str, str]],
    expected_raw_requests: list[tuple[str, str]],
) -> None:
    if json_body is None:
        response = getattr(backup_client, method)(path)
    else:
        response = getattr(backup_client, method)(path, json=json_body)

    assert response.status_code == 200
    if expected_json is not None:
        assert response.json() == expected_json

    assert backup_service.restored == expected_restored
    assert backup_service.raw_requests == expected_raw_requests
