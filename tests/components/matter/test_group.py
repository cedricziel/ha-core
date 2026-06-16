"""Tests for Matter group aggregation helpers.

The end-to-end group entity tests require the group API on the Matter server /
client (``get_groups``, ``send_group_command`` and the ``GROUP_*`` events),
which is not yet released. Until then these unit tests cover the pure state
aggregation logic that backs the group entities.
"""

import pytest

from homeassistant.components.matter.group import (
    aggregate_is_on,
    aggregate_mean,
    first_present,
)


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ([], False),
        ([False, False], False),
        ([False, True], True),
        ([None, None], False),
        ([None, True], True),
    ],
    ids=["empty", "all-off", "one-on", "all-none", "none-and-on"],
)
def test_aggregate_is_on(values: list[bool | None], expected: bool) -> None:
    """An on state is reported if any member is on."""
    assert aggregate_is_on(values) is expected


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ([], None),
        ([None, None], None),
        ([100], 100),
        ([100, 200], 150),
        ([100, None, 200], 150),
        ([1, 2], 2),
    ],
    ids=["empty", "all-none", "single", "mean", "mean-skips-none", "rounds"],
)
def test_aggregate_mean(values: list[int | None], expected: int | None) -> None:
    """The mean ignores missing values and rounds to the nearest int."""
    assert aggregate_mean(values) == expected


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ([], None),
        ([None, None], None),
        ([None, 5, 9], 5),
        ([0, 1], 0),
    ],
    ids=["empty", "all-none", "first-present", "zero-is-present"],
)
def test_first_present(values: list[int | None], expected: int | None) -> None:
    """The first non-None value is returned."""
    assert first_present(values) == expected
