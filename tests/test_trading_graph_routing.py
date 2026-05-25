"""Routing tests cover each branch listed in Section 9 step 5 of the spec."""

from dataclasses import replace

from src.trading_graph.config import Settings
from src.trading_graph.routing import route_after_cio, route_after_risk
from src.trading_graph.state import initial_state


def _state(**overrides):
    s = initial_state()
    s.update(overrides)
    return s


def test_approved_routes_to_cio() -> None:
    assert route_after_risk(_state(risk_approved=True)) == "cio"


def test_rejected_routes_to_portfolio_manager() -> None:
    assert (
        route_after_risk(_state(risk_approved=False, revision_count=1))
        == "portfolio_manager"
    )


def test_rejected_at_limit_routes_to_end() -> None:
    settings = Settings(max_revisions=2)
    assert (
        route_after_risk(
            _state(risk_approved=False, revision_count=2), settings=settings
        )
        == "__end__"
    )


def test_rejected_past_limit_routes_to_end() -> None:
    settings = Settings(max_revisions=3)
    assert (
        route_after_risk(
            _state(risk_approved=False, revision_count=5), settings=settings
        )
        == "__end__"
    )


def test_cio_signoff_routes_to_end() -> None:
    assert route_after_cio(_state(final_execution_ready=True)) == "__end__"


def test_cio_followup_routes_to_researcher() -> None:
    assert route_after_cio(_state(final_execution_ready=False)) == "researcher"


def test_max_revisions_pulled_from_settings_not_hardcoded() -> None:
    """Confirm settings override changes the bail-out boundary."""
    lenient = Settings(max_revisions=10)
    strict = Settings(max_revisions=1)
    s = _state(risk_approved=False, revision_count=2)
    assert route_after_risk(s, settings=lenient) == "portfolio_manager"
    assert route_after_risk(s, settings=strict) == "__end__"
    # silence unused import
    assert replace(lenient, max_revisions=5).max_revisions == 5
