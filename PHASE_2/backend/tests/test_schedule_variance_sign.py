from app.engines.forecast_engine import classify_schedule_variance


def test_positive_delay_days_means_late():
    assert classify_schedule_variance(3.2) == "late"


def test_negative_delay_days_means_ahead():
    assert classify_schedule_variance(-2.1) == "ahead"
