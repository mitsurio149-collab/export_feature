"""
Recovery Plan Engine Data Models

Defines all dataclasses for Recovery Plan generation, simulation, scoring, and explanation.
These models reuse existing types from the recommendation and simulation engines to avoid duplication.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List

from app.engines.recommendation_engine.models import Recommendation, TradeOff
from app.engines.simulation_engine import ScenarioResult


class RecoveryPlanArchetype(str, Enum):
    """Three plan archetypes representing different recovery strategies."""
    SAFE = "SAFE"  # Highest impact, lowest risk
    AGGRESSIVE = "AGGRESSIVE"  # Maximum delay recovery
    MINIMAL_DISRUPTION = "MINIMAL_DISRUPTION"  # Minimum blast radius


@dataclass(frozen=True)
class RecoveryPlanCandidate:
    """
    A candidate recovery plan built from a set of non-conflicting recommendations.
    
    This is an intermediate representation used during plan generation.
    It is not yet scored or explained.
    """
    plan_id: str
    archetype: RecoveryPlanArchetype
    actions: List[Recommendation]  # Reuses existing Recommendation type


@dataclass(frozen=True, order=False)
class RecoveryPlanScore:
    """
    Numeric scores for a recovery plan based on simulation results.
    
    All metrics come from the actual simulated outcome, not from summing
    individual recommendation estimates. This captures interaction effects.
    """
    deadline_probability: float  # % chance of hitting deadline (0.0-1.0)
    expected_delay_days: float  # Expected delay in days (from simulated ForecastResult)
    overall_risk_score: float  # Composite risk score (0.0-1.0)
    actions_required: int  # Number of actions in the plan
    execution_complexity: str  # "Low" (1-2), "Medium" (3-4), "High" (5+) or external stakeholder involved
    composite_score: float  # Weighted formula: 0.45*probability + 0.30*(1-delay) + 0.15*(1-risk) - 0.10*complexity


@dataclass(frozen=True)
class RecoveryPlanExplanation:
    """
    Narrative explanation for why a recovery plan was selected and how it compares to alternatives.
    
    Reuses comparison logic and TradeOff structures from RecommendationValidator.
    """
    plan_id: str
    why_recommended: List[str]  # Bullet points explaining why this plan is strong
    comparison_to_alternatives: List[str]  # How this plan beats or loses to alternatives
    trade_offs: List[TradeOff]  # Reuses existing TradeOff from recommendation_engine
    narrative_summary: str  # Single paragraph: "Recovery Plan A is recommended because..."


@dataclass(frozen=True)
class RecoveryPlan:
    """
    Complete recovery plan: actions + score + explanation + simulation output.
    
    This is the final, ranked output delivered to the API and frontend.
    """
    plan_id: str
    archetype: RecoveryPlanArchetype
    label: str  # "Recommended", "Alternative", "Minimal disruption"
    actions: List[Recommendation]  # Same as candidate actions
    score: RecoveryPlanScore  # Ranked by composite_score
    explanation: RecoveryPlanExplanation  # Why this plan was selected
    revised_sprint_plan: List[Dict[str, Any]]  # Reuses build_revised_sprint_plan output structure
    scenario_result: ScenarioResult  # Raw simulation output for drill-down
