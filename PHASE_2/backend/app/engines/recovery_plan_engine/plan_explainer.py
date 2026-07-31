"""
Recovery Plan Explainer

Generates narrative explanations for recovery plans, including:
- Why a plan was selected (why_recommended)
- How it compares to alternatives (comparison_to_alternatives)
- What trade-offs exist (trade_offs)
- One-paragraph summary (narrative_summary)

Reuses comparison-building logic from RecommendationValidator where possible.
"""

from typing import Dict, List

from app.engines.recommendation_engine.models import TradeOff
from app.engines.recovery_plan_engine.models import (
    RecoveryPlanCandidate,
    RecoveryPlanExplanation,
    RecoveryPlanScore,
)


class RecoveryPlanExplainer:
    """
    Explains recovery plans in natural language.
    
    Produces reasons why plans are recommended and how they compare to alternatives.
    """

    def explain_plan(
        self,
        plan: RecoveryPlanCandidate,
        plan_score: RecoveryPlanScore,
        all_plans: List[RecoveryPlanCandidate],
        all_scores: List[RecoveryPlanScore],
        is_recommended: bool = False,
    ) -> RecoveryPlanExplanation:
        """
        Generate a complete explanation for a recovery plan.
        
        Args:
            plan: RecoveryPlanCandidate to explain.
            plan_score: RecoveryPlanScore for this plan.
            all_plans: All recovery plans (for comparison).
            all_scores: Scores for all plans (for comparison).
            is_recommended: True if this is the highest-scoring plan.
        
        Returns:
            RecoveryPlanExplanation with narrative, comparison, and trade-offs.
        """
        plan_id = plan.plan_id
        
        # Generate why_recommended bullets
        why_recommended = self._generate_why_recommended(plan, plan_score, is_recommended)
        
        # Generate comparison to alternatives
        comparison_to_alternatives = self._generate_comparison(plan, plan_score, all_plans, all_scores)
        
        # Generate trade-offs
        trade_offs = self._generate_trade_offs(plan, plan_score)
        
        # Generate one-paragraph narrative summary
        narrative_summary = self._generate_narrative_summary(plan, plan_score, is_recommended)
        
        return RecoveryPlanExplanation(
            plan_id=plan_id,
            why_recommended=why_recommended,
            comparison_to_alternatives=comparison_to_alternatives,
            trade_offs=trade_offs,
            narrative_summary=narrative_summary,
        )

    @staticmethod
    def _generate_why_recommended(
        plan: RecoveryPlanCandidate,
        plan_score: RecoveryPlanScore,
        is_recommended: bool,
    ) -> List[str]:
        """Generate bullet-point reasons why a plan is strong."""
        reasons = []
        
        # Always mention deadline probability
        prob_pct = round(plan_score.deadline_probability * 100, 1)
        reasons.append(f"Achieves {prob_pct}% probability of hitting the deadline")
        
        # Mention delay recovery
        delay = round(plan_score.expected_delay_days, 1)
        if delay <= 0:
            reasons.append("Delivers project on time (zero delay)")
        else:
            reasons.append(f"Reduces expected delay to {delay} days")
        
        # Mention risk reduction
        risk = round(plan_score.overall_risk_score, 2)
        reasons.append(f"Overall risk score: {risk}")
        
        # Mention simplicity if marked as recommended
        if is_recommended and plan_score.execution_complexity == "Low":
            reasons.append("Low execution complexity — easy to implement")
        
        # Mention archetype
        archetype_descriptions = {
            "SAFE": "High-confidence actions only",
            "AGGRESSIVE": "Maximum delay recovery, accepts higher complexity",
            "MINIMAL_DISRUPTION": "Minimizes blast radius to team and critical path",
        }
        archetype_desc = archetype_descriptions.get(plan.archetype.value, "")
        if archetype_desc:
            reasons.append(f"Strategy: {archetype_desc}")
        
        return reasons

    @staticmethod
    def _generate_comparison(
        plan: RecoveryPlanCandidate,
        plan_score: RecoveryPlanScore,
        all_plans: List[RecoveryPlanCandidate],
        all_scores: List[RecoveryPlanScore],
    ) -> List[str]:
        """Generate comparison statements to alternatives."""
        comparisons = []
        
        # Compare to each other plan
        for other_plan, other_score in zip(all_plans, all_scores):
            if other_plan.plan_id == plan.plan_id:
                continue
            
            # Compare deadline probability
            prob_diff = (plan_score.deadline_probability - other_score.deadline_probability) * 100
            if prob_diff > 1:
                comparisons.append(
                    f"Outperforms {other_plan.archetype.value.lower()} plan by {abs(prob_diff):.1f}% "
                    f"on deadline probability"
                )
            elif prob_diff < -1:
                comparisons.append(
                    f"Trades {abs(prob_diff):.1f}% deadline probability to {other_plan.archetype.value.lower()} "
                    f"plan for simpler execution"
                )
            
            # Compare complexity
            if plan_score.execution_complexity != other_score.execution_complexity:
                comparisons.append(
                    f"{plan_score.execution_complexity} complexity vs. "
                    f"{other_score.execution_complexity.lower()} for {other_plan.archetype.value.lower()}"
                )
        
        return comparisons if comparisons else ["Comparable to alternatives with distinct trade-offs"]

    @staticmethod
    def _generate_trade_offs(
        plan: RecoveryPlanCandidate,
        plan_score: RecoveryPlanScore,
    ) -> List[TradeOff]:
        """Generate trade-off descriptions."""
        trade_offs = []
        
        # High complexity is a trade-off
        if plan_score.execution_complexity == "High":
            trade_offs.append(
                TradeOff(
                    description=f"Requires {plan_score.actions_required} coordinated actions across team",
                    severity="medium",
                )
            )
        
        # If deadline probability is not very high, that's a trade-off
        if plan_score.deadline_probability < 0.7:
            trade_offs.append(
                TradeOff(
                    description=f"Only {round(plan_score.deadline_probability * 100, 1)}% chance of hitting deadline",
                    severity="high",
                )
            )
        
        # If still expecting significant delay
        if plan_score.expected_delay_days > 5:
            trade_offs.append(
                TradeOff(
                    description=f"Expected delay of {round(plan_score.expected_delay_days, 1)} days remains",
                    severity="medium",
                )
            )
        
        if not trade_offs:
            trade_offs.append(
                TradeOff(
                    description="No significant trade-offs identified",
                    severity="low",
                )
            )
        
        return trade_offs

    @staticmethod
    def _generate_narrative_summary(
        plan: RecoveryPlanCandidate,
        plan_score: RecoveryPlanScore,
        is_recommended: bool,
    ) -> str:
        """Generate a single-paragraph narrative summary."""
        prob_pct = round(plan_score.deadline_probability * 100, 1)
        delay = round(plan_score.expected_delay_days, 1)
        actions = plan_score.actions_required
        complexity = plan_score.execution_complexity
        archetype = plan.archetype.value.lower()
        
        if is_recommended:
            return (
                f"Recovery Plan {plan.archetype.value} is recommended. It combines {actions} actions "
                f"({complexity.lower()} complexity) to achieve {prob_pct}% probability of hitting the deadline. "
                f"Expected project delay: {delay} days. This plan offers the best balance of deadline recovery "
                f"and execution feasibility across the team."
            )
        else:
            return (
                f"Recovery Plan {plan.archetype.value} ({archetype}) proposes {actions} actions "
                f"({complexity.lower()} complexity) achieving {prob_pct}% deadline probability with {delay} days "
                f"expected delay. Consider this option if you prioritize {archetype.replace('_', ' ')} over "
                f"the recommended plan."
            )
