"""
tests/test_phase4_decision.py

Integration tests for Phase 4 Stage 14: DecisionEngine (MCDA).

Gate: rationale string in every test output must contain a number.
      assert any(c.isdigit() for c in decision.rationale)
"""
from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from app.engines.decision_engine import DecisionEngine
from app.domain.emios_models import TradeoffMatrix, TradeoffOption, Diagnosis
from app.domain.models import SprintStatus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _opt(
    *,
    option_id: str,
    recommendation_id,
    label: str,
    gains: dict,
    sacrifices: dict,
    disruption: str = "LOW",
    reversible: bool = True,
    statement: str = "",
) -> TradeoffOption:
    nev = sum(gains.values()) - sum(sacrifices.values())
    return TradeoffOption(
        option_id=option_id,
        recommendation_id=recommendation_id,
        label=label,
        gains=gains,
        sacrifices=sacrifices,
        net_expected_value=round(nev, 4),
        disruption_level=disruption,
        reversible=reversible,
        sacrifice_statement=statement,
        projected_impacts=gains,
        sacrifice=statement,
        expected_value=round(nev, 4),
    )


def _null_opt(sacrifices: dict) -> TradeoffOption:
    return _opt(
        option_id="opt-null",
        recommendation_id=None,
        label="Do nothing",
        gains={},
        sacrifices=sacrifices,
        disruption="LOW",
        reversible=True,
        statement="Doing nothing accepts delay.",
    )


def _make_state(*, team_names=None, remaining_sprints=4) -> SimpleNamespace:
    team_names = team_names if team_names is not None else ["Meena"]
    team = [SimpleNamespace(name=n) for n in team_names]

    sprints = []
    for i in range(remaining_sprints):
        sprints.append(SimpleNamespace(sprint_id=f"S-open-{i}", status=SprintStatus.IN_PROGRESS))
    # a couple of completed sprints that must NOT count toward "remaining"
    sprints.append(SimpleNamespace(sprint_id="S-done-1", status=SprintStatus.COMPLETED))
    sprints.append(SimpleNamespace(sprint_id="S-done-2", status=SprintStatus.COMPLETED))

    return SimpleNamespace(team=team, sprints=sprints)


def _make_diagnosis(root_cause: str = "resource overload", confidence: float = 0.72) -> Diagnosis:
    return Diagnosis(
        diagnosis_id="diag-001",
        root_cause=root_cause,
        confidence=confidence,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_winner_has_highest_weighted_score():
    """The chosen option must be the one with the highest MCDA score."""
    weak = _opt(
        option_id="opt-weak", recommendation_id="rec-weak", label="Weak option",
        gains={"SCHEDULE": 1.0}, sacrifices={"BUSINESS": 4.0},
        disruption="LOW", statement="Weak option statement.",
    )
    strong = _opt(
        option_id="opt-strong", recommendation_id="rec-strong", label="Strong option",
        gains={"SCHEDULE": 8.0}, sacrifices={"QUALITY": 1.0},
        disruption="LOW", statement="Strong option statement.",
    )
    null_opt = _null_opt({"SCHEDULE": 6.0})

    matrix = TradeoffMatrix(options=[weak, strong, null_opt], null_option=null_opt, dominated_options=[])

    decision = DecisionEngine().run(
        tradeoff_matrix=matrix,
        diagnosis=None,
        state=_make_state(),
        monte_carlo=None,
    )

    assert decision.chosen_option.recommendation_id == "rec-strong"
    assert decision.weighted_score >= decision.expected_value or decision.weighted_score > 0


def test_rationale_contains_numeric_scores():
    """Gate: rationale must contain at least one digit."""
    weak = _opt(
        option_id="opt-weak", recommendation_id="rec-weak", label="Weak option",
        gains={"SCHEDULE": 1.0}, sacrifices={"BUSINESS": 4.0},
        disruption="LOW", statement="Weak option statement.",
    )
    strong = _opt(
        option_id="opt-strong", recommendation_id="rec-strong", label="Strong option",
        gains={"SCHEDULE": 8.0}, sacrifices={"QUALITY": 1.0},
        disruption="LOW", statement="Strong option statement.",
    )
    null_opt = _null_opt({"SCHEDULE": 6.0})
    matrix = TradeoffMatrix(options=[weak, strong, null_opt], null_option=null_opt, dominated_options=[])

    decision = DecisionEngine().run(
        tradeoff_matrix=matrix,
        diagnosis=_make_diagnosis(),
        state=_make_state(),
        monte_carlo=None,
    )

    assert any(c.isdigit() for c in decision.rationale)


def test_high_disruption_penalised_when_alternatives_exist():
    """A HIGH-disruption option should score lower than an equivalent LOW-disruption
    option once >1 positive-EV option exists, because of the 20% penalty."""
    high_disruption = _opt(
        option_id="opt-high", recommendation_id="rec-high", label="High disruption option",
        gains={"SCHEDULE": 10.0}, sacrifices={"BUSINESS": 1.0},
        disruption="HIGH", statement="High disruption statement.",
    )
    low_disruption = _opt(
        option_id="opt-low", recommendation_id="rec-low", label="Low disruption option",
        gains={"SCHEDULE": 10.0}, sacrifices={"BUSINESS": 1.0},
        disruption="LOW", statement="Low disruption statement.",
    )
    null_opt = _null_opt({"SCHEDULE": 3.0})
    matrix = TradeoffMatrix(
        options=[high_disruption, low_disruption, null_opt],
        null_option=null_opt, dominated_options=[],
    )

    decision = DecisionEngine().run(
        tradeoff_matrix=matrix,
        diagnosis=None,
        state=_make_state(),
        monte_carlo=None,
    )

    # Identical gains/sacrifices, but HIGH is penalised -> LOW wins.
    assert decision.chosen_option.recommendation_id == "rec-low"
    rejected_ids = [ra.option.recommendation_id for ra in decision.rejected_alternatives]
    assert "rec-high" in rejected_ids
    high_rejection = [ra for ra in decision.rejected_alternatives if ra.option.recommendation_id == "rec-high"][0]
    assert "disruption" in high_rejection.rejection_reason.lower()


def test_brooks_law_triggered_for_add_resource():
    """An option whose sacrifice_statement mentions Brooks risk must trigger the check."""
    add_resource = _opt(
        option_id="opt-add", recommendation_id="rec-add", label="Add AUTOSAR specialist",
        gains={"SCHEDULE": 4.0, "RESOURCE": 2.0}, sacrifices={"ORGANIZATIONAL": 3.0, "SCHEDULE": 1.5},
        disruption="HIGH",
        statement="Adding capacity gains 4.0 days but carries ramp-up overhead. Brooks risk if < 3 sprints remaining.",
    )
    null_opt = _null_opt({"SCHEDULE": 3.0})
    matrix = TradeoffMatrix(options=[add_resource, null_opt], null_option=null_opt, dominated_options=[])

    decision = DecisionEngine().run(
        tradeoff_matrix=matrix,
        diagnosis=None,
        state=_make_state(remaining_sprints=4),
        monte_carlo=None,
    )

    assert decision.brooks_law_check is not None
    assert decision.brooks_law_check.triggered is True
    assert decision.brooks_law_check.verdict == "SAFE"


def test_brooks_law_reject_when_less_than_2_sprints():
    """Fewer than 2 remaining sprints must produce a REJECT verdict."""
    add_resource = _opt(
        option_id="opt-add", recommendation_id="rec-add", label="Add AUTOSAR specialist",
        gains={"SCHEDULE": 4.0, "RESOURCE": 2.0}, sacrifices={"ORGANIZATIONAL": 3.0, "SCHEDULE": 1.5},
        disruption="HIGH",
        statement="Adding capacity gains 4.0 days but carries ramp-up overhead. Brooks risk if < 3 sprints remaining.",
    )
    null_opt = _null_opt({"SCHEDULE": 3.0})
    matrix = TradeoffMatrix(options=[add_resource, null_opt], null_option=null_opt, dominated_options=[])

    decision = DecisionEngine().run(
        tradeoff_matrix=matrix,
        diagnosis=None,
        state=_make_state(remaining_sprints=1),
        monte_carlo=None,
    )

    assert decision.brooks_law_check is not None
    assert decision.brooks_law_check.verdict == "REJECT"
    assert decision.feasibility_check.organizational_feasible is False
    assert decision.feasibility_check.blockers


def test_rejected_alternatives_explain_why_not_just_that_not():
    """Every rejected alternative must carry a concrete, non-generic reason."""
    weak = _opt(
        option_id="opt-weak", recommendation_id="rec-weak", label="Weak option",
        gains={"SCHEDULE": 1.0}, sacrifices={"BUSINESS": 4.0},
        disruption="LOW", statement="Weak option statement.",
    )
    strong = _opt(
        option_id="opt-strong", recommendation_id="rec-strong", label="Strong option",
        gains={"SCHEDULE": 8.0}, sacrifices={"QUALITY": 1.0},
        disruption="LOW", statement="Strong option statement.",
    )
    null_opt = _null_opt({"SCHEDULE": 6.0})
    matrix = TradeoffMatrix(options=[weak, strong, null_opt], null_option=null_opt, dominated_options=[])

    decision = DecisionEngine().run(
        tradeoff_matrix=matrix,
        diagnosis=None,
        state=_make_state(),
        monte_carlo=None,
    )

    assert len(decision.rejected_alternatives) >= 1
    for ra in decision.rejected_alternatives:
        assert ra.rejection_reason.strip() != ""
        assert "scored" in ra.rejection_reason
        assert any(c.isdigit() for c in ra.rejection_reason)


def test_null_option_never_chosen_when_positive_ev_exists():
    """If any candidate scores > 0, the null (do-nothing) option must not win."""
    strong = _opt(
        option_id="opt-strong", recommendation_id="rec-strong", label="Strong option",
        gains={"SCHEDULE": 8.0}, sacrifices={"QUALITY": 1.0},
        disruption="LOW", statement="Strong option statement.",
    )
    null_opt = _null_opt({"SCHEDULE": 6.0})
    matrix = TradeoffMatrix(options=[strong, null_opt], null_option=null_opt, dominated_options=[])

    decision = DecisionEngine().run(
        tradeoff_matrix=matrix,
        diagnosis=None,
        state=_make_state(),
        monte_carlo=None,
    )

    assert decision.chosen_option.recommendation_id is not None
    assert decision.warning is None


def test_confidence_inherits_from_diagnosis():
    """Decision.confidence must equal diagnosis.confidence when a diagnosis exists,
    and fall back to 0.5 when there is none."""
    strong = _opt(
        option_id="opt-strong", recommendation_id="rec-strong", label="Strong option",
        gains={"SCHEDULE": 8.0}, sacrifices={"QUALITY": 1.0},
        disruption="LOW", statement="Strong option statement.",
    )
    null_opt = _null_opt({"SCHEDULE": 6.0})
    matrix = TradeoffMatrix(options=[strong, null_opt], null_option=null_opt, dominated_options=[])

    with_diag = DecisionEngine().run(
        tradeoff_matrix=matrix,
        diagnosis=_make_diagnosis(confidence=0.81),
        state=_make_state(),
        monte_carlo=None,
    )
    assert with_diag.confidence == pytest.approx(0.81)

    without_diag = DecisionEngine().run(
        tradeoff_matrix=matrix,
        diagnosis=None,
        state=_make_state(),
        monte_carlo=None,
    )
    assert without_diag.confidence == pytest.approx(0.5)