from app.engines.project_calibration import ProjectCalibration
"""
Recovery Plan Scorer

Scores recovery plans based on simulated outcomes.

Scoring happens AFTER simulation, not before. A plan's composite score
is NOT the sum of individual recommendation scores (which would double-count
overlapping effects and miss interaction effects). Instead, we run the
actual simulation and read the real resulting state.

Composite score formula (deterministic, no ML):
    0.45 * deadline_probability
    + 0.30 * delay_recovered_fraction
    + 0.15 * (1 - normalized_risk_score)
    - 0.10 * normalized_execution_complexity

The complexity penalty is critical: it stops the system from always
recommending the most aggressive plan. A 7-action plan needs to lose
points relative to a 3-action plan with similar probability, because
the 3-action plan is more likely to actually get executed correctly.

--------------------------------------------------------------------
P0 FIX (see recovery-plan audit): delay term is now BASELINE-RELATIVE,
not normalized against a fixed 30-day constant.

Previously: normalized_delay = min(expected_delay_days / 30.0, 1.0).
For any project whose baseline delay is already >= 30 days (common for
a genuinely at-risk project -- e.g. 34.5 days in the reference case),
normalized_delay saturates to 1.0 for EVERY plan, including the
do-nothing baseline itself. That makes the delay term contribute
~0 regardless of how much delay a plan actually recovers, while the
complexity penalty keeps scaling with action count. Net effect: a
0-action "plan" that changes nothing can outscore a 7-action plan that
recovers 5.8 real days, purely because the 0-action plan pays no
complexity tax and the delay signal was invisible to begin with.

Fix: delay_recovered_fraction = (baseline_delay_days - expected_delay_days) / baseline_delay_days,
clamped to [0, 1]. This directly measures what fraction of the CURRENT
project's own delay this plan recovers, so it can never saturate to
the same value for every plan regardless of baseline size, and a
0-action plan always scores exactly 0 on this term (since it recovers
0 days of ITS OWN baseline) rather than tying with everyone else.
--------------------------------------------------------------------
"""

from typing import Any, List, Union

from app.engines.recovery_plan_engine.models import RecoveryPlanCandidate, RecoveryPlanScore
from app.engines.simulation_engine import ScenarioResult, SimulationResultV2


class RecoveryPlanScorer:
    """
    Scores recovery plans based on simulated outcomes.
    
    Normalizes all metrics to 0-1 range before combining them into
    a weighted composite score.
    """

    # Normalization constants (tuned based on typical project scenarios)
    MAX_RISK_SCORE = 100.0  # RiskEngine outputs a 0-100 scale
    MAX_EXECUTION_COMPLEXITY = 3.0  # "High" complexity is ~5+ actions
    # NOTE: MAX_EXPECTED_DELAY_DAYS removed -- delay is now scored as a
    # baseline-relative recovered fraction (see class docstring), not
    # normalized against this fixed constant. Kept as a fallback only,
    # for the rare case where baseline_delay_days is unavailable/zero.
    FALLBACK_MAX_EXPECTED_DELAY_DAYS = 30.0

    # Composite score weights (must sum to 1.0)
    WEIGHT_DEADLINE_PROBABILITY = 0.45  # Most important: getting the deadline
    WEIGHT_DELAY_REDUCTION = 0.30  # Second most important: how much time saved
    WEIGHT_RISK_REDUCTION = 0.15  # Third: overall risk reduction
    WEIGHT_COMPLEXITY_PENALTY = -0.10  # Penalty: prefer simpler plans

    # --- Quality-gate thresholds (P0 fix: "Recommended plan rule") -------
    # A plan is only eligible to be labeled "Recommended" if it has at
    # least one action AND clears one of these minimum, measurable bars.
    # These are intentionally modest -- the point is to reject plans that
    # are statistically indistinguishable from doing nothing, not to set
    # an aggressive bar. Tune these with real workbook runs.
    MIN_MEANINGFUL_DELAY_RECOVERED_DAYS = 1.0  # at least 1 real day recovered...
    MIN_MEANINGFUL_DELAY_RECOVERED_FRACTION = 0.03  # ...or at least 3% of baseline delay
    MIN_MEANINGFUL_PROBABILITY_GAIN = 0.02  # or at least +2 percentage points of deadline probability

    def score_plan(self, plan: RecoveryPlanCandidate, scenario_result: Union[ScenarioResult, SimulationResultV2], project_state=None) -> RecoveryPlanScore:
        if project_state is not None:
            _cal = ProjectCalibration.from_project_state(project_state)
            self.WEIGHT_DEADLINE_PROBABILITY = _cal.plan_score_weights.probability
            self.WEIGHT_DELAY_REDUCTION      = _cal.plan_score_weights.delay
            self.WEIGHT_RISK_REDUCTION       = _cal.plan_score_weights.risk
            self.WEIGHT_COMPLEXITY_PENALTY   = _cal.plan_score_weights.complexity
        """
        Score a recovery plan based on its simulation result.
        
        Args:
            plan: RecoveryPlanCandidate to score.
            scenario_result: ScenarioResult or SimulationResultV2 from simulating the plan.
        
        Returns:
            RecoveryPlanScore with all metrics and composite score.
        """
        # Extract metrics from scenario result depending on version
        if hasattr(scenario_result, "simulated_metrics"):
            deadline_probability = scenario_result.simulated_metrics.on_time_probability
            expected_delay_days = scenario_result.simulated_metrics.expected_delay_days
            risk_score = scenario_result.simulated_metrics.overall_risk_score
            _baseline = getattr(scenario_result, "baseline_metrics", None)
            baseline_probability = getattr(_baseline, "on_time_probability", deadline_probability) if _baseline else deadline_probability
            baseline_delay_days = getattr(_baseline, "expected_delay_days", expected_delay_days) if _baseline else expected_delay_days
            baseline_risk_score = getattr(_baseline, "overall_risk_score", risk_score) if _baseline else risk_score
        else:
            deadline_probability = scenario_result.monte_carlo_comparison.simulated_on_time_probability
            expected_delay_days = scenario_result.forecast_comparison.simulated_delay_days
            risk_score = scenario_result.risk_comparison.simulated_risk_score
            baseline_probability = getattr(
                scenario_result.monte_carlo_comparison, "baseline_on_time_probability", deadline_probability
            )
            baseline_delay_days = getattr(
                scenario_result.forecast_comparison, "baseline_delay_days", expected_delay_days
            )
            baseline_risk_score = getattr(
                scenario_result.risk_comparison, "baseline_risk_score", risk_score
            )

        # Derive execution complexity from number of actions and action types
        complexity_str = self._derive_complexity(plan.actions)
        complexity_score = self._complexity_to_score(complexity_str)

        # --- Baseline-relative delay term (P0 fix, see class docstring) ---
        # delay_recovered_fraction = how much of THIS project's own baseline
        # delay this plan actually recovers. Never saturates to the same
        # value for every plan regardless of project size, unlike the old
        # fixed-30-day normalization.
        if baseline_delay_days and baseline_delay_days > 0:
            delay_recovered_fraction = (baseline_delay_days - expected_delay_days) / baseline_delay_days
        else:
            # No meaningful baseline delay to recover from (e.g. project already
            # on time). Fall back to the old fixed-constant normalization so we
            # don't divide by zero -- this branch should be rare in practice.
            normalized_delay = min(expected_delay_days / self.FALLBACK_MAX_EXPECTED_DELAY_DAYS, 1.0)
            delay_recovered_fraction = 1.0 - normalized_delay
        delay_recovered_fraction = max(0.0, min(1.0, delay_recovered_fraction))

        normalized_risk = min(risk_score / self.MAX_RISK_SCORE, 1.0)
        normalized_complexity = min(complexity_score / self.MAX_EXECUTION_COMPLEXITY, 1.0)

        # Compute composite score
        composite_score = (
            self.WEIGHT_DEADLINE_PROBABILITY * deadline_probability
            + self.WEIGHT_DELAY_REDUCTION * delay_recovered_fraction
            + self.WEIGHT_RISK_REDUCTION * (1.0 - normalized_risk)
            + self.WEIGHT_COMPLEXITY_PENALTY * normalized_complexity
        )

        # Clamp to 0-1 range
        composite_score = max(0.0, min(1.0, composite_score))

        # --- Quality gate (P0 fix: "Recommended plan rule") ---
        # A plan may only be labeled "Recommended" upstream (see engine.py)
        # if it clears this bar. Computed here, alongside every other score
        # value, so it is always traceable to real simulated numbers.
        actual_delay_recovered_days = max(0.0, baseline_delay_days - expected_delay_days)
        probability_gain = deadline_probability - baseline_probability
        meaningful_improvement = (
            len(plan.actions) > 0
            and (
                actual_delay_recovered_days >= self.MIN_MEANINGFUL_DELAY_RECOVERED_DAYS
                or delay_recovered_fraction >= self.MIN_MEANINGFUL_DELAY_RECOVERED_FRACTION
                or probability_gain >= self.MIN_MEANINGFUL_PROBABILITY_GAIN
            )
        )

        return RecoveryPlanScore(
            deadline_probability=deadline_probability,
            expected_delay_days=expected_delay_days,
            overall_risk_score=risk_score,
            actions_required=len(plan.actions),
            execution_complexity=complexity_str,
            composite_score=composite_score,
            baseline_delay_days=baseline_delay_days,
            baseline_deadline_probability=baseline_probability,
            baseline_risk_score=baseline_risk_score,
            meaningful_improvement=meaningful_improvement,
        )

    def score_all_plans(
        self,
        plans: List[RecoveryPlanCandidate],
        scenario_results: List[ScenarioResult],
    ) -> List[RecoveryPlanScore]:
        """
        Score multiple plans.
        
        Args:
            plans: List of RecoveryPlanCandidate objects.
            scenario_results: Corresponding list of ScenarioResult objects (same order).
        
        Returns:
            List of RecoveryPlanScore objects (same order).
        """
        if len(plans) != len(scenario_results):
            raise ValueError("Number of plans must match number of scenario results")
        
        return [self.score_plan(plan, result) for plan, result in zip(plans, scenario_results)]

    @staticmethod
    def _derive_complexity(actions: list) -> str:
        """
        Derive execution complexity from action count and types.

        The SAFE archetype can legitimately include up to 5 actions when they
        are mostly low-disruption reassignments or rebalances, so the classifier
        should look at both count and the presence of externally coordinated work.
        """
        num_actions = len(actions)
        # "External" here means work that requires coordinating with people/systems
        # beyond the plan's own actions (re-architecting dependencies, negotiating
        # capacity). resolve_blocker is deliberately excluded: it means chasing an
        # already-open external blocker to resolution, which doesn't add any new
        # coordination burden onto the team -- if anything it's the point of
        # MINIMAL_DISRUPTION plans, which should read as Low/Medium, not High,
        # purely because they contain 2+ blocker resolutions.
        external_count = sum(
            1
            for action in actions
            if action.action_type.value in [
                "remove_dependency_bottleneck",
                "add_resource_skill",
            ]
        )

        if num_actions <= 2 and external_count == 0:
            return "Low"
        elif num_actions <= 5 and external_count <= 1:
            return "Medium"
        else:
            return "High"

    @staticmethod
    def _complexity_to_score(complexity: str) -> float:
        """Convert complexity string to numeric score for normalization."""
        complexity_map = {
            "Low": 1.0,
            "Medium": 2.0,
            "High": 3.0,
        }
        return complexity_map.get(complexity, 2.0)  # Default to Medium if unknown
