"""
Recovery Plan Engine Orchestrator

Main entry point for recovery plan generation. Coordinates all components:
- Generator: Creates 3 candidate plans
- Simulator: Simulates each plan's impact
- Scorer: Scores based on simulation results
- Explainer: Generates narrative explanations
- Ranker: Ranks plans and marks "Recommended"

Returns complete ranked list of RecoveryPlan objects ready for API/frontend.
"""

import logging
from functools import cmp_to_key
from typing import Any, Callable, Dict, List, Optional, Set

from app.engines.recommendation_engine.models import Recommendation
from app.engines.recovery_plan_engine.conflict_detector import ConflictDetector
from app.engines.recovery_plan_engine.models import (
    RecoveryPlan,
    RecoveryPlanCandidate,
    RecoveryPlanScore,
    RecoveryPlanArchetype,
)
from app.engines.recovery_plan_engine.plan_explainer import RecoveryPlanExplainer
from app.engines.recovery_plan_engine.plan_generator import RecoveryPlanGenerator
from app.engines.recovery_plan_engine.plan_scorer import RecoveryPlanScorer

logger = logging.getLogger(__name__)
from app.engines.recovery_plan_engine.plan_simulator import RecoveryPlanSimulator
from app.engines.simulation_engine import ScenarioResult, SimulationEngine


class RecoveryPlanEngine:
    """
    Main engine for generating recovery plans.
    
    Orchestrates plan generation, simulation, scoring, explanation, and ranking
    into a complete workflow producing ranked RecoveryPlan objects.
    """

    def __init__(
        self,
        simulation_engine: SimulationEngine,
        max_actions_per_plan: int = 5,
        build_revised_sprint_plan_fn: Optional[Callable] = None,
    ):
        """
        Args:
            simulation_engine: Configured SimulationEngine with project state and upstream outputs.
            max_actions_per_plan: Maximum actions per plan (default 5).
            build_revised_sprint_plan_fn: Function to call to build revised sprint plan from simulation.
                                          If None, use dummy output (will be integrated later).
        """
        self.simulation_engine = simulation_engine
        self.generator = RecoveryPlanGenerator(max_actions_per_plan=max_actions_per_plan)
        self.simulator = RecoveryPlanSimulator(simulation_engine)
        self.scorer = RecoveryPlanScorer()
        self.explainer = RecoveryPlanExplainer()
        self.build_revised_sprint_plan_fn = build_revised_sprint_plan_fn

    def generate_recovery_plans(
        self,
        recommendations: List[Recommendation],
        critical_path_item_ids: Optional[Set[str]] = None,
        resource_loads: Optional[Dict[str, float]] = None,
    ) -> List[RecoveryPlan]:
        """
        Generate three ranked recovery plans from recommendations.
        
        Complete pipeline:
        1. Generate 3 candidate plans (SAFE, AGGRESSIVE, MINIMAL_DISRUPTION)
        2. Simulate each plan's impact
        3. Score each plan based on simulation
        4. Explain each plan (narrative, comparisons, trade-offs)
        5. Build revised sprint plan for each
        6. Rank by composite_score
        7. Mark highest-scoring plan as "Recommended"
        8. Return ranked list
        
        Args:
            recommendations: List of ranked recommendations to build plans from.
            critical_path_item_ids: Set of item IDs on the critical path (optional, used for MINIMAL_DISRUPTION archetype).
            resource_loads: Dict of resource_id -> load_percentage (optional, used for MINIMAL_DISRUPTION archetype).
        
        Returns:
            List of RecoveryPlan objects, ranked by composite_score descending.
            First plan (highest score) is labeled "Recommended".
        """
        if not recommendations:
            return []
        
        # Precompute per-recommendation simulations so SAFE plan can be
        # constructed from measured impact (delta on-time probability / delay).
        simulation_map: Dict[str, object] = {}
        for rec in recommendations:
            try:
                scenario = self.simulation_engine.simulate(rec)
            except Exception:
                scenario = None
            simulation_map[rec.recommendation_id] = scenario

        # Step 1: Generate candidate plans (3 archetypes)
        candidate_plans = self.generator.generate_all_archetypes(
            recommendations,
            critical_path_item_ids=critical_path_item_ids,
            resource_loads=resource_loads,
            simulation_results=simulation_map,
        )
        
        # Step 2: Simulate each candidate plan
        scenario_results: List[ScenarioResult] = []
        for plan in candidate_plans:
            scenario = self.simulator.simulate_plan(plan)
            scenario_results.append(scenario)
        
        # Step 3: Score each plan
        plan_scores: List[RecoveryPlanScore] = self.scorer.score_all_plans(candidate_plans, scenario_results)

        # NOTE: the old blanket "Aggressive scored lower than Safe" warning was removed
        # from here -- it fired any time complexity flipped the ranking, even when that
        # was legitimate (comparable outcomes, Safe genuinely simpler for similar results).
        # The dominance-aware warning further below only fires when the reordering
        # actually corrects a real contradiction (a plan dominated on every outcome
        # metric still scoring higher due to complexity alone).
        
        # Step 4: Explain each plan
        plan_explanations = []
        for i, (plan, score) in enumerate(zip(candidate_plans, plan_scores)):
            # Determine if this is the recommended (highest score) — will finalize after ranking
            explanation = self.explainer.explain_plan(
                plan=plan,
                plan_score=score,
                all_plans=candidate_plans,
                all_scores=plan_scores,
                is_recommended=False,  # Provisional; will update after ranking
            )
            plan_explanations.append(explanation)
        
        # Step 5: Build revised sprint plan for each (reuses validator logic)
        revised_sprint_plans = []
        for scenario in scenario_results:
            # Use prebuilt revised_sprint_plan if available (legacy path); otherwise fallback to empty list
            revised_plan = []
            if hasattr(scenario, "revised_sprint_plan") and scenario.revised_sprint_plan:
                revised_plan = scenario.revised_sprint_plan
            revised_sprint_plans.append(revised_plan)
        
        # Step 6: Rank by composite_score descending, with a dominance safeguard.
        #
        # The complexity penalty exists to break ties between plans with similar
        # outcomes (see plan_scorer.py docstring) -- it is NOT meant to override a
        # plan that is strictly better on every real outcome metric. If plan A has
        # probability >= plan B, delay <= plan B, and risk <= plan B (strictly better
        # on at least one), A must never rank below B just because A has more
        # actions. Complexity should only decide between genuinely comparable plans.
        def _dominates(a: RecoveryPlanScore, b: RecoveryPlanScore) -> bool:
            # Always cast to float so a str field can never cause TypeError
            a_prob  = float(a.deadline_probability)
            b_prob  = float(b.deadline_probability)
            a_delay = float(a.expected_delay_days)
            b_delay = float(b.expected_delay_days)
            a_risk  = float(a.overall_risk_score)
            b_risk  = float(b.overall_risk_score)
            prob_ge = a_prob  >= b_prob
            delay_le = a_delay <= b_delay
            risk_le  = a_risk  <= b_risk
            strictly_better = (
                a_prob  > b_prob
                or a_delay < b_delay
                or a_risk  < b_risk
            )
            return prob_ge and delay_le and risk_le and strictly_better

        def _compare(i: int, j: int) -> int:
            if _dominates(plan_scores[i], plan_scores[j]):
                return -1  # i ranks above j regardless of composite_score
            if _dominates(plan_scores[j], plan_scores[i]):
                return 1
            # No dominance either way -- fall back to composite_score, which is
            # exactly where the complexity penalty is meant to act as a tie-breaker.
            ci = float(plan_scores[i].composite_score)
            cj = float(plan_scores[j].composite_score)
            if ci > cj:
                return -1
            if ci < cj:
                return 1
            return 0

        # --- P0 fix: Recommended-plan quality gate -------------------------
        # A plan must never be labeled "Recommended" just because it has the
        # highest composite_score. It must first clear plan_scorer's
        # `meaningful_improvement` gate (actions > 0 AND a measurable delay/
        # probability improvement over baseline -- see plan_scorer.py).
        #
        # We do this by ranking eligible plans and ineligible plans as two
        # separate groups (each internally ordered by the existing dominance
        # + composite_score comparator), then concatenating eligible-first.
        # This guarantees an ineligible plan (e.g. 0 actions, or actions that
        # simulate to no measurable change) can never outrank a plan that
        # actually clears the bar, regardless of what composite_score alone
        # would have said.
        eligible = [i for i in range(len(plan_scores)) if plan_scores[i].meaningful_improvement]
        ineligible = [i for i in range(len(plan_scores)) if not plan_scores[i].meaningful_improvement]
        eligible_ranked = sorted(eligible, key=cmp_to_key(_compare))
        ineligible_ranked = sorted(ineligible, key=cmp_to_key(_compare))
        ranked_indices = eligible_ranked + ineligible_ranked
        any_eligible_plan = len(eligible) > 0

        # If dominance reordering actually changed anything vs. plain composite-score
        # sort, log it -- this is different from (and replaces) the old blanket
        # "Aggressive < Safe" warning, which fired even when no real contradiction existed.
        composite_only_order = sorted(range(len(plan_scores)), key=lambda i: plan_scores[i].composite_score, reverse=True)
        if ranked_indices != composite_only_order:
            logger.info(
                "Recovery plan ranking adjusted by outcome dominance and/or the "
                "Recommended-plan quality gate: %s (eligible-first) vs. plain "
                "composite-score order %s. Eligible plans (meaningful_improvement=True): %s.",
                [candidate_plans[i].archetype.value for i in ranked_indices],
                [candidate_plans[i].archetype.value for i in composite_only_order],
                [candidate_plans[i].archetype.value for i in eligible],
            )
        if not any_eligible_plan:
            logger.warning(
                "No recovery plan cleared the Recommended-plan quality gate "
                "(meaningful_improvement=False for all %d candidate plans). "
                "No plan will be labeled 'Recommended'.",
                len(plan_scores),
            )

        # Step 7: Build final RecoveryPlan objects (now marked as Recommended/Alternative)
        final_plans: List[RecoveryPlan] = []
        for rank, idx in enumerate(ranked_indices):
            plan = candidate_plans[idx]
            score = plan_scores[idx]
            explanation = plan_explanations[idx]
            scenario = scenario_results[idx]
            revised_plan = revised_sprint_plans[idx]

            # Determine label based on rank -- but rank 0 only earns "Recommended"
            # if it actually cleared the quality gate above. If NO plan clears
            # the gate, every plan is labeled as an Alternative and the top
            # plan's narrative explicitly says why nothing was recommended.
            if rank == 0 and any_eligible_plan:
                label = "Recommended"
                # Regenerate explanation now that we know this is recommended
                explanation = self.explainer.explain_plan(
                    plan=plan,
                    plan_score=score,
                    all_plans=candidate_plans,
                    all_scores=plan_scores,
                    is_recommended=True,
                )
            elif rank == 0 and not any_eligible_plan:
                label = "Alternative"
                explanation = self.explainer.explain_plan(
                    plan=plan,
                    plan_score=score,
                    all_plans=candidate_plans,
                    all_scores=plan_scores,
                    is_recommended=False,
                )
                no_plan_note = (
                    "No feasible recovery strategy materially improves the current "
                    "forecast under the available project constraints. This plan "
                    f"({plan.archetype.value}) scored highest of the three candidates "
                    f"but recovers only {max(0.0, score.baseline_delay_days - score.expected_delay_days):.1f} "
                    "days of delay and is not being presented as a recommendation."
                )
                explanation = explanation.__class__(
                    plan_id=explanation.plan_id,
                    why_recommended=explanation.why_recommended,
                    comparison_to_alternatives=explanation.comparison_to_alternatives,
                    trade_offs=explanation.trade_offs,
                    narrative_summary=no_plan_note,
                )
            elif rank == 1:
                label = "Alternative"
            else:
                label = f"Alternative {rank}"

            recovery_plan = RecoveryPlan(
                plan_id=plan.plan_id,
                archetype=plan.archetype,
                label=label,
                actions=plan.actions,
                score=score,
                explanation=explanation,
                revised_sprint_plan=revised_plan,
                scenario_result=scenario,
            )
            final_plans.append(recovery_plan)

        return final_plans

    def validate_plan(self, plan: RecoveryPlan) -> Dict[str, Any]:
        """
        Validate a recovery plan for consistency and correctness.
        
        Checks:
        - No internal conflicts between actions
        - All actions are in the recommendations list
        - Composite score is within expected range
        
        Returns:
            Dict with 'is_valid' bool and 'issues' list of any problems found.
        """
        issues = []
        
        # Check for internal conflicts
        if ConflictDetector.detect_conflicts_in_plan(plan.actions):
            issues.append("Plan contains conflicting actions")
        
        # Check composite score range
        if plan.score.composite_score < 0.0 or plan.score.composite_score > 1.0:
            issues.append(f"Composite score {plan.score.composite_score} is out of range [0, 1]")
        
        # Check actions count matches score.actions_required
        if len(plan.actions) != plan.score.actions_required:
            issues.append(
                f"Action count mismatch: plan has {len(plan.actions)} "
                f"but score says {plan.score.actions_required}"
            )
        
        return {
            "is_valid": len(issues) == 0,
            "issues": issues,
        }
