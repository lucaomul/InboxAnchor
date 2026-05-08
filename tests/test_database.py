from pathlib import Path

from inboxanchor.infra.database import _resolve_database_url


def test_relative_sqlite_url_resolves_to_app_data_directory():
    resolved = _resolve_database_url("sqlite:///./inboxanchor.db")

    assert resolved.startswith("sqlite:///")
    assert "/inboxanchor/inboxanchor.db" in resolved


def test_absolute_sqlite_url_is_preserved_when_parent_is_writable(tmp_path):
    candidate = tmp_path / "nested" / "inboxanchor.db"

    resolved = _resolve_database_url(f"sqlite:///{candidate}")

    assert resolved == f"sqlite:///{candidate}"
    assert Path(candidate.parent).exists()
