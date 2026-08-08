"""Tests for run.py — the CLI entry point.

Only the preflight check is exercised here; the fetch/join/emit stages have
their own tests and are stubbed out.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import join as join_mod
import run as run_mod


def test_missing_raw_files_lists_every_absent_input(tmp_path, monkeypatch):
    monkeypatch.setattr(join_mod, "RAW", tmp_path)
    (tmp_path / "parcels.geojson").write_text("{}")
    missing = run_mod.missing_raw_files()
    assert "parcels.geojson" not in missing
    assert set(missing) == set(join_mod.RAW_FILES) - {"parcels.geojson"}


def test_missing_raw_files_empty_when_cache_complete(tmp_path, monkeypatch):
    monkeypatch.setattr(join_mod, "RAW", tmp_path)
    for name in join_mod.RAW_FILES:
        (tmp_path / name).write_text("{}")
    assert run_mod.missing_raw_files() == []


def test_no_fetch_with_empty_cache_fails_with_actionable_message(
    tmp_path, monkeypatch, capsys
):
    """`--no-fetch` against an empty raw/ used to die on a bare
    FileNotFoundError from deep inside join_all. It must instead name the
    missing files and the command that would produce them."""
    monkeypatch.setattr(join_mod, "RAW", tmp_path)
    monkeypatch.setattr(sys, "argv", ["run.py", "--no-fetch", "--no-dos"])

    def explode(*a, **k):  # join must never be reached
        raise AssertionError("join_all ran against a missing cache")

    monkeypatch.setattr(run_mod, "join_all", explode)

    assert run_mod.main() == 2
    err = capsys.readouterr().err
    assert "code_violations.json" in err
    assert "--no-fetch" in err
    assert "run.py" in err
