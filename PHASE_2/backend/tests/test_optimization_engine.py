"""
Regression tests for OptimizationEngine (PR 1). [V2-correct]

Strategy: inject a FakeSim in place of SimulationEngineV2 so we can script the
on-time probability of every candidate STATE (keyed by op-set). This lets us
construct the B+C > A trap precisely and assert search behavior without loading
a workbook or running Monte Carlo. FakeSim returns a SimulationResult-shaped
object with baseline_metrics / simulated_metrics, matching the V2 contract.
"""
from types import SimpleNamespace

import pytest

from app.engines.optimization_engine import OptimizationEngine, _rec_id


# ── fakes ──────────────────────────────────────────────────────────────────────
def rec(rid: str) -> SimpleNamespace:
    """Minimal stand-in for a Recommendation (only id + title are read)."""
    return SimpleNamespace(recommendation_id=rid, title=f"Action {rid}")


def _metrics(prob, delay, risk):
    return SimpleNamespace(
        on_time_probability=prob,
        expected_delay_days=delay,
        overall_risk_score=risk,
    )


def _result(prob, base):
    """SimulationResult-shaped object: absolute baseline_metrics + simulated_metrics."""
    base_prob, base_delay, base_risk = base
    delay = round(base_delay * (1.0 - prob), 4)
    risk = round(base_risk * (1.0 - prob * 0.5), 4)
    return SimpleNamespace(
        baseline_metrics=_metrics(base_prob, base_delay, base_risk),
        simulated_metrics=_metrics(prob, delay, risk),
    )


class FakeSim:
    """Scripted V2 evaluator. prob_map: frozenset(op_ids) -> on-time probability."""
    def __init__(self, prob_map, base=(0.20, 40.0, 70.0)):
        self.prob_map = prob_map
        self.base = base
        self.calls = []                      # every simulate_scenario invocation, in order

    def simulate_scenario(self, recs):
        ids = frozenset(_rec_id(r) for r in recs)
        self.calls.append(ids)
        prob = self.prob_map.get(ids, self.base[0])
        return _result(prob, self.base)


def build_engine(prob_map, candidates, **kwargs):
    """OptimizationEngine wired to a FakeSim (bypasses EngineRunnerV2 entirely)."""
    eng = OptimizationEngine(state=SimpleNamespace(), candidates=candidates, **kwargs)
    eng._sim = FakeSim(prob_map)             # pre-set so _simulation_engine() never builds a real one
    return eng


# The canonical trap: greedy picks A, but B+C is the global optimum.
TRAP = {
    frozenset(): 0.20,
    frozenset({"A"}): 0.45,
    frozenset({"B"}): 0.40,
    frozenset({"C"}): 0.30,
    frozenset({"A", "B"}): 0.50,
    frozenset({"A", "C"}): 0.50,
    frozenset({"B", "C"}): 0.80,
}
ABC = [rec("A"), rec("B"), rec("C")]


# ── 1. beam beats greedy ─────────────────────────────────────────────────────────
def test_beam_beats_greedy():
    greedy = build_engine(TRAP, ABC, beam_width=1, max_actions=2).optimize()
    beam = build_engine(TRAP, ABC, beam_width=5, max_actions=2).optimize()

    assert set(greedy.selected_action_ids) == {"A", "B"}      # greedy's local optimum
    assert greedy.final_probability == pytest.approx(0.50)

    assert set(beam.selected_action_ids) == {"B", "C"}         # global optimum recovered
    assert beam.final_probability == pytest.approx(0.80)
    assert beam.final_probability > greedy.final_probability


# ── 2. deduplication: {A,B} == {B,A}, evaluated once ─────────────────────────────
def test_deduplication_of_symmetric_paths():
    eng = build_engine(TRAP, ABC, beam_width=5, max_actions=2)
    eng.optimize()
    calls = eng._sim.calls
    # each unique op-set is simulated at most once (frozenset key collapses A,B / B,A)
    assert len(calls) == len(set(calls))
    assert calls.count(frozenset({"A", "B"})) == 1


# ── 3. cache: re-evaluating the same state hits the cache ────────────────────────
def test_evaluation_cache():
    eng = build_engine(TRAP, ABC)
    before = len(eng._sim.calls)
    eng._evaluate(("A", "B"))                 # first eval → 1 simulate call
    after_first = len(eng._sim.calls)
    eng._evaluate(("B", "A"))                 # same op-set, reordered → cache hit, no new call
    after_second = len(eng._sim.calls)

    assert after_first == before + 1
    assert after_second == after_first        # cache served the second call


# ── 4. convergence: stop when no child beats min_probability_gain ────────────────
def test_convergence_stops_on_no_improvement():
    flat = {
        frozenset(): 0.20,
        frozenset({"A"}): 0.201,              # +0.001 < min_gain
        frozenset({"B"}): 0.202,
        frozenset({"C"}): 0.2005,
    }
    eng = build_engine(flat, ABC, beam_width=5, max_actions=5, min_probability_gain=0.005)
    plan = eng.optimize()

    assert plan.selected_action_ids == []
    assert plan.total_probability_gain == pytest.approx(0.0)
    assert "optimal" in plan.narrative.lower()


# ── 5. applicability: invalid ops never enter the beam ───────────────────────────
def test_applicability_excludes_invalid_ops():
    prob_map = dict(TRAP)
    prob_map[frozenset({"X"})] = 0.99          # X looks amazing on paper...
    candidates = ABC + [rec("X")]

    eng = build_engine(
        prob_map, candidates, beam_width=5, max_actions=2,
        is_applicable=lambda applied_ids, cid: cid != "X",   # ...but X is never valid
    )
    plan = eng.optimize()

    assert "X" not in plan.selected_action_ids
    assert all("X" not in op_set for op_set in eng._sim.calls)   # X-states never even simulated


# ── 6. marginal contribution: leave-one-out is sensible + finds the dominant op ──
def test_marginal_contributions():
    plan = build_engine(TRAP, ABC, beam_width=5, max_actions=2).optimize()
    contrib = plan.action_contributions

    assert set(contrib) == {"B", "C"}
    # full{B,C}=0.80; without B = {C}=0.30 → 0.50; without C = {B}=0.40 → 0.40
    assert contrib["B"] == pytest.approx(0.50)
    assert contrib["C"] == pytest.approx(0.40)
    assert all(v > 0 for v in contrib.values())
    assert max(contrib, key=contrib.get) == "B"                # dominant action identified


# ── 7. determinism: same seed → same plan ────────────────────────────────────────
def test_determinism():
    p1 = build_engine(TRAP, ABC, beam_width=5, max_actions=2, seed=42).optimize()
    p2 = build_engine(TRAP, ABC, beam_width=5, max_actions=2, seed=42).optimize()

    assert p1.selected_action_ids == p2.selected_action_ids
    assert p1.final_probability == p2.final_probability
    assert p1.search_trace == p2.search_trace