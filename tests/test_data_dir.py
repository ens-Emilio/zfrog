"""Tests for state path resolution (the deployment volume).

A container mount only persists the paths it covers. Every store default is
relative, so without a single root they resolve against the working directory and
land in the container's writable layer: a restart then silently loses the API
keys, users, sessions and version blobs.
"""

from pathlib import Path

import pytest

from zfrog.config import _STATE_PATH_FIELDS, Settings


def test_default_data_dir_keeps_the_historical_paths():
    """`data_dir="."` must not move anything: local use stays as it was."""
    settings = Settings(data_dir=Path("."))

    assert settings.output_dir == Path("output")
    assert settings.api_keys_file == Path("api_keys.json")
    assert settings.versions_dir == Path("versions")


def test_data_dir_moves_every_state_path_under_it(tmp_path):
    settings = Settings(data_dir=tmp_path)

    for name in _STATE_PATH_FIELDS:
        value = getattr(settings, name)
        assert isinstance(value, Path), name
        assert tmp_path in value.parents, f"{name} -> {value} is outside the volume"


def test_absolute_paths_are_left_alone(tmp_path):
    """In-cluster service-account files are absolute and must not be rewritten."""
    settings = Settings(data_dir=tmp_path)

    assert settings.k8s_token_file == Path(
        "/var/run/secrets/kubernetes.io/serviceaccount/token"
    )
    assert settings.k8s_ca_file == Path(
        "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
    )


def test_an_explicit_absolute_path_wins_over_data_dir(tmp_path):
    """An operator who points a store somewhere else must be obeyed."""
    explicit = tmp_path / "elsewhere" / "keys.json"
    settings = Settings(data_dir=tmp_path / "data", api_keys_file=explicit)

    assert settings.api_keys_file == explicit


def test_a_store_writes_under_the_volume_and_reads_back(tmp_path, monkeypatch):
    """The point of the volume: a store's file lands on it and survives.

    `auth.py` holds a reference to the settings OBJECT, so the new instance is
    injected where the store reads it — which is also what a restarted process
    effectively does by rebuilding the object from the environment.
    """
    from zfrog import auth

    fresh = Settings(data_dir=tmp_path)
    monkeypatch.setattr(auth, "settings", fresh)

    secret, _ = auth.ApiKeyStore().create("ana", "admin")

    # The file is on the volume, not in the working directory.
    assert (tmp_path / "api_keys.json").is_file()

    # A store pointed at the resolved path still verifies the secret.
    assert auth.ApiKeyStore(path=fresh.api_keys_file).verify(secret) is not None
