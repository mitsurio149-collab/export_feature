"""
CalibrationStore — Stage 17a support (Phase 6a).

Process-level, in-memory running-mean store of calibration profiles per
team. Deliberately simple (class-level dict, no persistence) since this is
meant to accumulate signal across LearningEngine episodes within a single
running process; swap for a real datastore if cross-process persistence is
ever needed.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional

from app.domain.emios_models import CalibrationProfile, LearningRecord

# Below this many episodes, we don't trust the running mean enough to
# apply a velocity correction.
MIN_EPISODES_FOR_CORRECTION = 3


class CalibrationStore:
    """Class-level store; persists for the lifetime of the process."""

    _profiles: Dict[str, CalibrationProfile] = {}

    @classmethod
    def get(cls, team_id: str) -> Optional[CalibrationProfile]:
        return cls._profiles.get(team_id)

    @classmethod
    def update(cls, team_id: str, record: LearningRecord) -> CalibrationProfile:
        profile = cls._profiles.get(team_id) or CalibrationProfile(
            team_id=team_id,
            velocity_bias=0.0,
            probability_overestimate=0.0,
            brier_scores=[],
            episode_count=0,
            last_updated=datetime.now(timezone.utc),
        )

        n = profile.episode_count

        if record.velocity_estimate_bias is not None:
            profile.velocity_bias = (
                (profile.velocity_bias * n + record.velocity_estimate_bias) / (n + 1)
            )

        if record.brier_score is not None:
            profile.brier_scores.append(record.brier_score)

        if record.actual_outcome is not None and record.forecast_probability is not None:
            err = record.forecast_probability - record.actual_outcome
            profile.probability_overestimate = (
                (profile.probability_overestimate * n + err) / (n + 1)
            )

        profile.episode_count += 1
        profile.last_updated = datetime.now(timezone.utc)
        cls._profiles[team_id] = profile
        return profile

    @classmethod
    def get_velocity_correction(cls, team_id: str) -> float:
        profile = cls.get(team_id)
        if profile is None or profile.episode_count < MIN_EPISODES_FOR_CORRECTION:
            return 0.0
        return profile.velocity_bias

    @classmethod
    def reset(cls, team_id: Optional[str] = None) -> None:
        """Test/dev helper -- not part of the roadmap spec, but needed to
        keep tests isolated from each other since _profiles is class-level
        (process-wide) state."""
        if team_id is None:
            cls._profiles = {}
        else:
            cls._profiles.pop(team_id, None)
