from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from app.engines.recommendation_engine.models import Recommendation
from app.engines.simulation_engine import ScenarioResult, SimulationEngine


class AdvisorRecommendation(BaseModel):
    recommendation_ids: List[str] = Field(default_factory=list)
    priority: str = Field(..., description="high, medium, or low")
    summary: str = Field(..., description="Deterministic human-readable advice")
    rationale: List[str] = Field(default_factory=list)


class AIAdvisor:
    """Deterministic advisor layer built on top of the simulation engine."""

    def __init__(self, simulation_engine: SimulationEngine):
        self.simulation_engine = simulation_engine

    def advise(self, recommendation: Recommendation) -> AdvisorRecommendation:
        scenario = self.simulation_engine.simulate(recommendation)
        score = scenario.summary.overall_improvement_score
        if score >= 70.0:
            priority = "high"
        elif score >= 30.0:
            priority = "medium"
        else:
            priority = "low"

        rationale = [
            f"Forecast finish date moved by {scenario.forecast_comparison.finish_date_delta:+.0f} days.",
            f"Risk score improved by {scenario.risk_comparison.risk_reduction:.2f} points.",
        ]
        if scenario.summary.warnings:
            rationale.extend(scenario.summary.warnings)

        summary = (
            f"Simulation indicates the recommendation has {priority} value and "
            f"improves the project outlook by {score:.1f} points."
        )
        return AdvisorRecommendation(
            recommendation_ids=[recommendation.recommendation_id],
            priority=priority,
            summary=summary,
            rationale=rationale,
        )
