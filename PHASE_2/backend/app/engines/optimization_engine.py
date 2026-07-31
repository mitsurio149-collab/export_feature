"""
OptimizationEngine (PR 1) — beam search over candidate ProjectStates. [V2-correct]

Architectural stance:
  - The search NODE is a candidate FUTURE ProjectState, not a recommendation list.
  - A Recommendation is merely the OPERATOR that mutates one state into the next.
  - We score STATES via the EXISTING SimulationEngineV2, then explain the winning
    state's delta as the ordered sequence of ops that produced it.

Search = beam search (width W). Greedy is just W=1, so this strictly dominates it
and recovers combinations like B+C > A that greedy misses. This is a drop-in
upgrade of the greedy loop already inside RecommendationEngineV2.generate().

Reuses SimulationEngineV2.simulate_scenario() as the state evaluator. Computes no
forecast/MC/risk math of its own. Deterministic (seeded MC) so the beam is stable.

Scope note (PR 1): CandidateState carries an op-set identity + evaluated score,
not a cloned ProjectState — states are reproduced on demand by the simulator and
cached by op-set. Snapshotting the mutated state, composite scoring, pluggable
search strategies (A*/MCTS/GA), and feedback-based priors are deliberately
deferred to later PRs. The applicability hook is included because impossible
states must never enter the beam.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from app.domain.models import ProjectState
from app.engines.recommendation_engine.models import (
    Recommendation,
    SimulationResult,
    UpstreamEngineOutputs,
)
from app.engines.simulation_engine import EngineRunnerV2, SimulationEngineV2

logger = logging.getLogger(__name__)


def _rec_id(rec: Recommendation) -> str:
    return getattr(rec, "recommendation_id", None) or getattr(rec, "id", "") or ""


def _rec_title(rec: Recommendation) -> str:
    return getattr(rec, "title", None) or getattr(rec, "description", None) or _rec_id(rec)


@dataclass(frozen=True)
class CandidateState:
    """A future ProjectState, identified by the ordered ops that produced it.

    The state itself is reproducible on demand via SimulationEngine (which
    deep-copies the baseline and applies these ops), so we carry the cheap
    identity + its evaluated score rather than a heavy state clone in every
    beam slot."""
    applied_ids: Tuple[str, ...]          # ordered operator ids (recommendation ids)
    probability: float                    # on-time probability of THIS state
    delay_days: float
    risk_score: float

    def key(self) -> frozenset:
        # order-independent identity: {A,B} == {B,A} so the beam de-dupes paths
        return frozenset(self.applied_ids)


@dataclass
class OptimizedPlan:
    selected_action_ids: List[str]
    baseline_probability: float
    final_probability: float
    baseline_delay_days: float
    final_delay_days: float
    baseline_risk_score: float
    final_risk_score: float
    total_probability_gain: float
    total_delay_reduction_days: float
    action_contributions: Dict[str, float] = field(default_factory=dict)  # order-independent, leave-one-out
    search_trace: List[Dict] = field(default_factory=list)                # per-depth beam snapshot, for the UI/debug
    narrative: str = ""


# Predicate: given the ops already applied to a state and a candidate op id,
# return True if that op may legally extend the state. Default = allow-all.
ApplicabilityFn = Callable[[Tuple[str, ...], str], bool]


class OptimizationEngine:
    def __init__(
        self,
        state: ProjectState,
        candidates: Sequence[Recommendation],
        *,
        beam_width: int = 5,
        max_actions: int = 5,
        min_probability_gain: float = 0.005,
        simulation_count: int = 1000,
        seed: int = 42,
        is_applicable: Optional[ApplicabilityFn] = None,
        seed_upstream: Optional[UpstreamEngineOutputs] = None,
    ) -> None:
        self.state = state
        self.candidates = {_rec_id(c): c for c in candidates if _rec_id(c)}
        self.beam_width = beam_width
        self.max_actions = max_actions
        self.min_probability_gain = min_probability_gain
        self.simulation_count = simulation_count
        self.seed = seed
        # default: every operator is applicable to every state
        self.is_applicable: ApplicabilityFn = is_applicable or (lambda applied_ids, cid: True)
        # optionally reuse the session's already-computed upstream (skips a full pipeline run)
        self._seed_upstream = seed_upstream
        self._sim: Optional[SimulationEngineV2] = None
        self._eval_cache: Dict[frozenset, CandidateState] = {}

    # ── evaluator: materialize a candidate STATE and score it (V2) ──────────────
    def _simulation_engine(self) -> SimulationEngineV2:
        if self._sim is None:
            upstream: UpstreamEngineOutputs = (
                self._seed_upstream
                or EngineRunnerV2().run(self.state, simulation_count=self.simulation_count)
            )
            self._sim = SimulationEngineV2(self.state, upstream, simulation_count=self.simulation_count)
        return self._sim

    def _evaluate(self, applied_ids: Tuple[str, ...]) -> CandidateState:
        """Produce and score the ProjectState reached by applying these ops.
        Cached by op-set so the beam never re-simulates an equivalent state.
        V2 simulate_scenario returns absolute simulated_metrics (not deltas)."""
        k = frozenset(applied_ids)
        if k in self._eval_cache:
            return self._eval_cache[k]
        recs = [self.candidates[i] for i in applied_ids]
        res: SimulationResult = self._simulation_engine().simulate_scenario(recs)
        cand = CandidateState(
            applied_ids=applied_ids,
            probability=res.simulated_metrics.on_time_probability,
            delay_days=res.simulated_metrics.expected_delay_days,
            risk_score=res.simulated_metrics.overall_risk_score,
        )
        self._eval_cache[k] = cand
        return cand

    # ── beam search over candidate states ───────────────────────────────────────
    def optimize(self) -> OptimizedPlan:
        sim = self._simulation_engine()
        # An empty scenario still carries baseline_metrics — read the baseline from it.
        base_res: SimulationResult = sim.simulate_scenario([])
        base_prob = base_res.baseline_metrics.on_time_probability
        base_delay = base_res.baseline_metrics.expected_delay_days
        base_risk = base_res.baseline_metrics.overall_risk_score

        root = CandidateState((), base_prob, base_delay, base_risk)
        beam: List[CandidateState] = [root]
        best: CandidateState = root
        trace: List[Dict] = []

        for depth in range(self.max_actions):
            frontier: Dict[frozenset, CandidateState] = {}
            for node in beam:
                for cid in self.candidates:
                    if cid in node.applied_ids:
                        continue
                    if not self.is_applicable(node.applied_ids, cid):  # prune impossible states
                        continue
                    child = self._evaluate(node.applied_ids + (cid,))
                    # prune paths that don't beat their own parent beyond noise
                    if child.probability - node.probability < self.min_probability_gain:
                        continue
                    prev = frontier.get(child.key())
                    if prev is None or child.probability > prev.probability:
                        frontier[child.key()] = child

            if not frontier:
                break  # no state at this depth improves on its parent → converged

            beam = sorted(frontier.values(), key=lambda c: c.probability, reverse=True)[: self.beam_width]
            trace.append({
                "depth": depth + 1,
                "beam": [{"actions": list(c.applied_ids), "probability": round(c.probability, 4)} for c in beam],
            })
            if beam[0].probability > best.probability:
                best = beam[0]

        contributions = self._leave_one_out(best.applied_ids, base_prob)
        return OptimizedPlan(
            selected_action_ids=list(best.applied_ids),
            baseline_probability=base_prob, final_probability=best.probability,
            baseline_delay_days=base_delay, final_delay_days=best.delay_days,
            baseline_risk_score=base_risk, final_risk_score=best.risk_score,
            total_probability_gain=best.probability - base_prob,
            total_delay_reduction_days=base_delay - best.delay_days,
            action_contributions=contributions,
            search_trace=trace,
            narrative=self._narrative(best, base_prob, base_delay, contributions),
        )

    # ── marginal contribution (order-independent, leave-one-out) ────────────────
    def _leave_one_out(self, applied_ids: Tuple[str, ...], base_prob: float) -> Dict[str, float]:
        if not applied_ids:
            return {}
        full = self._evaluate(applied_ids).probability
        out: Dict[str, float] = {}
        for cid in applied_ids:
            others = tuple(i for i in applied_ids if i != cid)
            without = self._evaluate(others).probability if others else base_prob
            out[cid] = round(full - without, 4)
        return out

    def _narrative(self, best: CandidateState, base_prob: float, base_delay: float,
                   contributions: Dict[str, float]) -> str:
        if not best.applied_ids:
            return "No candidate state improves the forecast beyond noise; the current plan is already optimal."
        top_id = max(contributions, key=contributions.get)
        top = self.candidates[top_id]
        return (
            f"Best future state applies {len(best.applied_ids)} action(s): on-time probability "
            f"{base_prob:.0%} → {best.probability:.0%}, expected delay "
            f"{base_delay:.1f} → {best.delay_days:.1f} days. "
            f"'{_rec_title(top)}' contributes the most (+{contributions[top_id]:.0%})."
        )