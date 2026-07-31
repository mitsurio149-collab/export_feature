from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "BaselineMetrics",
    "CandidateGenerator",
    "ConfidenceLevel",
    "ImpactEstimate",
    "OpportunitySignal",
    "Recommendation",
    "RecommendationAction",
    "RecommendationCandidate",
    "ScoringWeights",
    "SignalCategory",
    "SignalEvidence",
    "SignalSeverity",
    "SimulatedMetrics",
    "SimulationResult",
    "UpstreamEngineOutputs",
    "signal_id",
    "stable_id",
]


def __getattr__(name: str) -> Any:
    if name in {
        "BaselineMetrics",
        "ConfidenceLevel",
        "ImpactEstimate",
        "OpportunitySignal",
        "Recommendation",
        "RecommendationAction",
        "RecommendationCandidate",
        "ScoringWeights",
        "SignalCategory",
        "SignalEvidence",
        "SignalSeverity",
        "SimulatedMetrics",
        "SimulationResult",
        "UpstreamEngineOutputs",
        "signal_id",
        "stable_id",
    }:
        module = import_module(".models", __name__)
        return getattr(module, name)
    if name == "CandidateGenerator":
        module = import_module(".candidate_generator", __name__)
        return getattr(module, name)
    raise AttributeError(name)
