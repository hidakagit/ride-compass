import pytest

from app.domain.errors import RoutingError


def test_routing_error_is_an_exception():
    assert issubclass(RoutingError, Exception)


def test_routing_error_preserves_message():
    with pytest.raises(RoutingError, match="something went wrong"):
        raise RoutingError("something went wrong")


def test_routing_error_can_be_raised_with_cause():
    original = ValueError("root cause")
    try:
        try:
            raise original
        except ValueError as exc:
            raise RoutingError("wrapped") from exc
    except RoutingError as wrapped:
        assert wrapped.__cause__ is original
