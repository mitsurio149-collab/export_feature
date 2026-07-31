"""
EMIOS Stage 13 — TradeoffAnalyzer.

Takes RecommendationEngine output (already simulation-grounded, positive-delta
only) and forces an explicit sacrifice statement for each option.
There is NEVER a free option — every gain has a cost.
"""
from __future__ import annotations

from typing import Dict, List, Optional
from uuid import uuid4

from app.domain.emios_models import (
    ImpactMatrix,
    TradeoffMatrix,
    TradeoffOption,
)
from app.domain.models import ProjectState
from app.engines.recommendation_engine.models import (
    Recommendation,
    RecommendationAction,
)
from app.api.models_phase3 import ForecastResult, MonteCarloResult


# ---------------------------------------------------------------------------
# Action-type to sacrifice mapping
# ---------------------------------------------------------------------------

_DISRUPTION_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}

_BLOCKER_ACTIONS = {
    RecommendationAction.RESOLVE_BLOCKER,
    RecommendationAction.ESCALATE_BLOCKER_EARLY,
}

_ADD_RESOURCE_ACTIONS = {
    RecommendationAction.ADD_RESOURCE_SKILL,
    RecommendationAction.CROSS_TRAIN_BACKUP,
}

_REASSIGN_ACTIONS = {
    RecommendationAction.REASSIGN_ITEM,
    RecommendationAction.REBALANCE_SPRINT_LOAD,
}

_PARALLELIZE_ACTIONS = {
    RecommendationAction.PARALLELIZE_ITEMS,
    RecommendationAction.SPLIT_ITEM,
    RecommendationAction.ADVANCE_ITEM_TO_EARLIER_SPRINT,
    RecommendationAction.SPLIT_AND_PAIR,
    RecommendationAction.PULL_FORWARD_ITEM,
    RecommendationAction.RESEQUENCE_NON_CRITICAL_ITEM,
}

_REDUCE_SCOPE_ACTIONS = {
    RecommendationAction.FREEZE_SCOPE_REQUEST,
}

_QUALITY_ACTIONS = {
    RecommendationAction.REBASELINE_ESTIMATE,
    RecommendationAction.INSERT_REVIEW_GATE,
    RecommendationAction.PAIR_REVIEWER,
    RecommendationAction.ASSIGN_AS_SECOND_REVIEWER,
}


class TradeoffAnalyzer:
    """Stage 13: project each recommendation across impact dimensions
    and surface the sacrifice. Always includes a null (do-nothing) option."""

    def run(
        self,
        recommendations: List[Recommendation],
        impact_matrix: Optional[ImpactMatrix],
        state: ProjectState,
        forecast: Optional[ForecastResult],
        monte_carlo: Optional[MonteCarloResult],
    ) -> TradeoffMatrix:
        options: List[TradeoffOption] = []

        for rec in recommendations:
            option = self._build_option(rec, impact_matrix, state)
            options.append(option)

        # Null option — always present, always last
        null_opt = self._build_null_option(impact_matrix, forecast, monte_carlo)
        options.append(null_opt)

        # Compute dominated options
        dominated = self._find_dominated(options, null_opt)

        return TradeoffMatrix(
            options=options,
            null_option=null_opt,
            dominated_options=dominated,
        )

    # ------------------------------------------------------------------
    # Option builders
    # ------------------------------------------------------------------

    def _build_option(
        self,
        rec: Recommendation,
        impact_matrix: Optional[ImpactMatrix],
        state: ProjectState,
    ) -> TradeoffOption:
        action = rec.action_type
        delay_days = rec.estimated_delay_reduction_days

        if action in _BLOCKER_ACTIONS:
            gains, sacrifices, disruption, reversible, statement = (
                self._map_blocker(rec, impact_matrix, state)
            )
        elif action in _ADD_RESOURCE_ACTIONS:
            gains, sacrifices, disruption, reversible, statement = (
                self._map_add_resource(rec)
            )
        elif action in _REASSIGN_ACTIONS:
            gains, sacrifices, disruption, reversible, statement = (
                self._map_reassign(rec)
            )
        elif action in _PARALLELIZE_ACTIONS:
            gains, sacrifices, disruption, reversible, statement = (
                self._map_parallelize(rec)
            )
        elif action in _REDUCE_SCOPE_ACTIONS:
            gains, sacrifices, disruption, reversible, statement = (
                self._map_reduce_scope(rec)
            )
        elif action in _QUALITY_ACTIONS:
            gains, sacrifices, disruption, reversible, statement = (
                self._map_quality(rec)
            )
        else:
            gains, sacrifices, disruption, reversible, statement = (
                self._map_default(rec)
            )

        nev = sum(gains.values()) - sum(sacrifices.values())

        return TradeoffOption(
            option_id=f"opt-{uuid4().hex[:8]}",
            recommendation_id=rec.recommendation_id,
            label=rec.title,
            gains=gains,
            sacrifices=sacrifices,
            net_expected_value=round(nev, 4),
            disruption_level=disruption,
            reversible=reversible,
            sacrifice_statement=statement,
            # Legacy compat
            projected_impacts=gains,
            sacrifice=statement,
            expected_value=round(nev, 4),
        )

    def _build_null_option(
        self,
        impact_matrix: Optional[ImpactMatrix],
        forecast: Optional[ForecastResult],
        monte_carlo: Optional[MonteCarloResult],
    ) -> TradeoffOption:
        expected_delay = float(
            getattr(forecast, "expected_delay_days", 0.0) or 0.0
        )
        otp = float(
            getattr(monte_carlo, "on_time_probability", 0.0) or 0.0
        )

        # Pull business and quality magnitudes from impact matrix
        business_mag = 0.0
        quality_mag = 0.0
        if impact_matrix and impact_matrix.estimates:
            biz_est = impact_matrix.estimates.get("business")
            if biz_est:
                business_mag = abs(float(getattr(biz_est, "magnitude", 0.0) or 0.0))
            qual_est = impact_matrix.estimates.get("quality")
            if qual_est:
                quality_mag = abs(float(getattr(qual_est, "magnitude", 0.0) or 0.0))

        sacrifices = {
            "SCHEDULE": expected_delay,
            "BUSINESS": business_mag,
            "QUALITY": quality_mag,
        }
        # Remove zero-value sacrifices for cleanliness
        sacrifices = {k: v for k, v in sacrifices.items() if v > 0}

        nev = -sum(sacrifices.values())

        statement = (
            f"Doing nothing accepts {expected_delay:.1f} days of delay "
            f"and {otp:.0%} on-time probability."
        )

        return TradeoffOption(
            option_id=f"opt-null-{uuid4().hex[:6]}",
            recommendation_id=None,
            label="Do nothing",
            gains={},
            sacrifices=sacrifices,
            net_expected_value=round(nev, 4),
            disruption_level="LOW",
            reversible=True,
            sacrifice_statement=statement,
            projected_impacts={},
            sacrifice=statement,
            expected_value=round(nev, 4),
        )

    # ------------------------------------------------------------------
    # Sacrifice mappings per action category
    # ------------------------------------------------------------------

    def _map_blocker(
        self,
        rec: Recommendation,
        impact_matrix: Optional[ImpactMatrix],
        state: ProjectState,
    ):
        # Find the blocker for title/owner
        blocker_title = "blocker"
        blocker_owner = "owner"
        delay = rec.estimated_delay_reduction_days

        if rec.affected_blocker_ids:
            bid = rec.affected_blocker_ids[0]
            for b in getattr(state, "blockers", []) or []:
                if getattr(b, "blocker_id", None) == bid:
                    blocker_title = getattr(b, "description", bid) or bid
                    blocker_owner = getattr(b, "owner", "owner") or "owner"
                    # Use estimated_delay_days from blocker if available
                    est = getattr(b, "estimated_delay_days", None)
                    if est and delay == 0:
                        delay = float(est)
                    break

        quality_gain = 0.0
        if impact_matrix and impact_matrix.estimates:
            qe = impact_matrix.estimates.get("quality")
            if qe:
                quality_gain = abs(float(getattr(qe, "magnitude", 0.0) or 0.0)) * 0.3

        gains = {"SCHEDULE": delay, "QUALITY": quality_gain}
        sacrifices = {"RESOURCE": 1.5}
        disruption = "MEDIUM"
        reversible = True
        statement = (
            f"Resolving {blocker_title[:60]} recovers {delay:.1f} days but "
            f"requires {blocker_owner} to deprioritize current sprint work for ~2 days."
        )
        return gains, sacrifices, disruption, reversible, statement

    def _map_add_resource(self, rec: Recommendation):
        delay = rec.estimated_delay_reduction_days
        gains = {"SCHEDULE": delay, "RESOURCE": 2.0}
        sacrifices = {"ORGANIZATIONAL": 3.0, "SCHEDULE": 1.5}
        disruption = "HIGH"
        reversible = True
        statement = (
            f"Adding capacity gains {delay:.1f} days but carries ramp-up overhead. "
            f"Brooks risk if < 3 sprints remaining."
        )
        return gains, sacrifices, disruption, reversible, statement

    def _map_reassign(self, rec: Recommendation):
        delay = rec.estimated_delay_reduction_days
        gains = {"SCHEDULE": delay, "RESOURCE": 1.0}
        sacrifices = {"RESOURCE": 2.0, "ORGANIZATIONAL": 1.0}
        disruption = "MEDIUM"
        reversible = True
        statement = (
            f"Reassigning work recovers {delay:.1f} days but increases load "
            f"on the receiving resource."
        )
        return gains, sacrifices, disruption, reversible, statement

    def _map_parallelize(self, rec: Recommendation):
        delay = rec.estimated_delay_reduction_days
        gains = {"SCHEDULE": delay}
        sacrifices = {"QUALITY": 1.5, "ORGANIZATIONAL": 1.0}
        disruption = "LOW"
        reversible = True
        statement = (
            f"Parallelizing recovers {delay:.1f} days but reduces "
            f"sequential review quality."
        )
        return gains, sacrifices, disruption, reversible, statement

    def _map_reduce_scope(self, rec: Recommendation):
        delay = rec.estimated_delay_reduction_days
        gains = {"SCHEDULE": delay, "RESOURCE": 2.0}
        sacrifices = {"BUSINESS": 4.0}
        disruption = "HIGH"
        reversible = False
        statement = (
            f"Deferring scope recovers {delay:.1f} days but removes committed "
            f"features — requires customer/stakeholder approval."
        )
        return gains, sacrifices, disruption, reversible, statement

    def _map_quality(self, rec: Recommendation):
        delay = rec.estimated_delay_reduction_days
        gains = {"QUALITY": 2.0, "SCHEDULE": delay}
        sacrifices = {"SCHEDULE": 0.5, "RESOURCE": 1.0}
        disruption = "LOW"
        reversible = True
        statement = (
            f"Adding a review gate improves quality but costs "
            f"~0.5 days of review overhead per item."
        )
        return gains, sacrifices, disruption, reversible, statement

    def _map_default(self, rec: Recommendation):
        delay = rec.estimated_delay_reduction_days
        gains = {"SCHEDULE": delay}
        sacrifices = {"RESOURCE": 1.0}
        disruption = "LOW"
        reversible = True
        statement = (
            f"{rec.title} is expected to recover {delay:.1f} days."
        )
        return gains, sacrifices, disruption, reversible, statement

    # ------------------------------------------------------------------
    # Domination logic
    # ------------------------------------------------------------------

    def _find_dominated(
        self, options: List[TradeoffOption], null_option: TradeoffOption
    ) -> List[str]:
        """Option A dominates Option B if:
        A.net_expected_value > B.net_expected_value
        AND disruption_rank(A) <= disruption_rank(B).
        The null option is NEVER dominated."""
        dominated: List[str] = []

        for b in options:
            # Null option is never dominated
            if b.recommendation_id is None:
                continue
            for a in options:
                if a.option_id == b.option_id:
                    continue
                if (
                    a.net_expected_value > b.net_expected_value
                    and _DISRUPTION_RANK[a.disruption_level]
                    <= _DISRUPTION_RANK[b.disruption_level]
                ):
                    if b.recommendation_id and b.recommendation_id not in dominated:
                        dominated.append(b.recommendation_id)
                    break

        return dominated
