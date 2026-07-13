"""Smoke tests for the Berlin Events Explorer package."""

from berlin_events_explorer._version import version


def test_version_exists():
    """Test that the package has a version attribute."""
    assert isinstance(version, str)


def test_sample_fixture(sample_fixture):
    """Example test using a fixture from conftest.py."""
    assert sample_fixture["key"] == "value"
    assert sample_fixture["project"] == "Berlin Events Explorer"
