"""Example test module for Berlin Events Explorer.

This module contains a placeholder test that intentionally fails
to remind developers to implement proper tests.
"""

import pytest

from berlin_events_explorer._version import version


def test_version_exists():
    """Test that the package has a version attribute."""
    assert isinstance(version, str)


def test_todo_implement_tests():
    """Placeholder test that fails to remind developers to implement tests."""
    assert False, (
        "TODO: Implement proper tests for Berlin Events Explorer!\n"
        "This is a placeholder test that intentionally fails.\n"
        "Replace this with actual tests for your functionality."
    )


def test_sample_fixture(sample_fixture):
    """Example test using a fixture from conftest.py."""
    assert sample_fixture["key"] == "value"
    assert sample_fixture["project"] == "Berlin Events Explorer"