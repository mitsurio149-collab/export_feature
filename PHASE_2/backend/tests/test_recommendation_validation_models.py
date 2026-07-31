from app.engines.recommendation_engine.models import (
    ConfidenceLevel,
    RecommendationValidation,
    TradeOff,
)


def test_recommendation_validation_models_can_be_instantiated() -> None:
    trade_off = TradeOff(description="Receiving resource is already loaded", severity="moderate")
    validation = RecommendationValidation(
        recommendation_id="rec-001",
        why_selected=["Meena is overloaded by 38%", "Ravi has 42 hours free"],
        why_better_than_alternatives=["Recovers 2.3 more days than alternative A"],
        rejected_alternatives=["Alternative A"],
        delay_reduction_summary="8.4d → 3.1d",
        probability_improvement_summary="68% → 91%",
        confidence_label=ConfidenceLevel.HIGH,
        confidence_reasoning="Based on direct staffing data.",
        trade_offs=[trade_off],
        one_line_pitch="Reassign the item to Ravi — recovers 5.3 days.",
    )

    assert validation.recommendation_id == "rec-001"
    assert validation.trade_offs[0].severity == "moderate"
    assert validation.confidence_label == ConfidenceLevel.HIGH
