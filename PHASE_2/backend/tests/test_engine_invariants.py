import types

from app.engines.recommendation_engine.models import (
    ConfidenceLevel,
    Recommendation,
    RecommendationAction,
)
from app.engines.simulation_engine import SimulationEngine, SimulationEngineV2
from app.storage.session_store import SessionStore


class MutableState:
    def __init__(self, project_id="p1", counter=0):
        self.project_id = project_id
        self.counter = counter
        self.work_items = []

    def model_copy(self, deep=True):
        clone = MutableState(self.project_id, self.counter)
        clone.work_items = [item for item in self.work_items]
        return clone


class DummyApplicator:
    def apply(self, state, recommendation):
        state.counter += 1
        state.work_items.append((recommendation.recommendation_id, state.counter))

    def apply_many(self, state, recommendations):
        state.counter += len(recommendations)
        for recommendation in recommendations:
            state.work_items.append((recommendation.recommendation_id, state.counter))


class DummyRunner:
    def run(self, state, simulation_count=1000):
        return types.SimpleNamespace(
            monte_carlo=types.SimpleNamespace(on_time_probability=0.5),
            forecast=types.SimpleNamespace(expected_delay_days=1.0, projected_velocity=10.0),
            risk_result=types.SimpleNamespace(
                overall_risk_score=10.0,
                schedule_risk=types.SimpleNamespace(score=1.0),
                resource_risk=types.SimpleNamespace(score=1.0),
            ),
            cp_result=types.SimpleNamespace(critical_path_duration_hours=2.0),
            spillover=types.SimpleNamespace(predicted_spillover_by_sprint={"s1": 1.0}),
        )


def _make_recommendation(recommendation_id: str) -> Recommendation:
    return Recommendation(
        recommendation_id=recommendation_id,
        title="Test recommendation",
        description="",
        action_type=RecommendationAction.RESOLVE_BLOCKER,
        priority_score=1.0,
        confidence=ConfidenceLevel.MEDIUM,
        estimated_hours_recovered=1.0,
        estimated_delay_reduction_days=1.0,
        estimated_risk_reduction=1.0,
        affected_item_ids=[],
        affected_resource_ids=[],
        affected_sprint_ids=[],
        affected_blocker_ids=[],
        root_cause_signal_id="signal",
    )


def test_previewing_safe_plan_does_not_mutate_baseline():
    baseline = MutableState(project_id="p1", counter=0)
    engine = SimulationEngine(project_state=baseline, metrics=None, dag=None, cp_result=None, spillover=None, forecast=None, monte_carlo=None, risk_result=None)
    engine.applicator = DummyApplicator()
    engine._recalculate_clone = lambda clone: {}
    engine._build_scenario_result = lambda recommendations, simulated, clone: clone

    engine.simulate_scenario([_make_recommendation("safe")])

    assert baseline.counter == 0


def test_previewing_aggressive_plan_starts_from_original_baseline():
    baseline = MutableState(project_id="p2", counter=0)
    engine = SimulationEngineV2(project_state=baseline, baseline=None)
    engine.applicator = DummyApplicator()
    engine.runner = DummyRunner()
    engine._compute_result = lambda rec_ids, simulated: {"rec_ids": rec_ids}

    result = engine.simulate(_make_recommendation("aggressive"))

    assert result["rec_ids"] == ["aggressive"]
    assert baseline.counter == 0


def test_different_sessions_do_not_share_state():
    store = SessionStore()
    store._sessions.clear()

    first_state = MutableState(project_id="shared-a", counter=1)
    second_state = MutableState(project_id="shared-b", counter=1)
    first_session_id = store.create_session(first_state)
    second_session_id = store.create_session(second_state)

    first_session = store.get_session(first_session_id)
    second_session = store.get_session(second_session_id)

    first_session.project_state.counter = 99

    assert first_session.project_state is not second_session.project_state
    assert first_session.project_state.counter == 99
    assert second_session.project_state.counter == 1
    assert first_state.counter == 1
    assert second_state.counter == 1
