"""
EMIOS Stage 14 — DecisionEngine (MCDA).

Takes the TradeoffMatrix (Stage 13) and a root-cause Diagnosis (Stage 6) and
picks a single winner via weighted multi-criteria scoring, with an explicit,
numeric rationale and explicit reasons for every rejected alternative.

There is NEVER a silent choice — every rejection is justified, and Brooks's
Law is checked whenever a capacity-add option is on the table.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional
from uuid import uuid4

from app.domain.emios_models import (
    BrooksLawCheck,
    Decision,
    Diagnosis,
    FeasibilityCheck,
    RejectedAlternative,
    TradeoffMatrix,
    TradeoffOption,
)
from app.domain.models import ProjectState, SprintStatus
from app.api.models_phase3 import MonteCarloResult


# ---------------------------------------------------------------------------
# MCDA weights (PM-overridable in future; hardcoded for now)
# ---------------------------------------------------------------------------
WEIGHTS: Dict[str, float] = {
    "SCHEDULE": 0.35,
    "BUSINESS": 0.25,
    "QUALITY": 0.20,
    "RESOURCE": 0.15,
    "ORGANIZATIONAL": 0.05,
}

_DISRUPTION_PENALTY = 0.80

_DONE_SPRINT_STATUSES = {"Completed", "Done"}


class DecisionEngine:
    """Stage 14: score every non-null TradeoffOption via MCDA, pick a winner,
    run the Brooks's Law and feasibility guardrails, and explain every
    rejection with actual numbers."""

    def run(
        self,
        tradeoff_matrix: TradeoffMatrix,
        diagnosis: Optional[Diagnosis],
        state: ProjectState,
        monte_carlo: Optional[MonteCarloResult],
    ) -> Decision:
        options = tradeoff_matrix.options or []
        null_option = tradeoff_matrix.null_option
        candidates = [o for o in options if o.recommendation_id is not None]

        positive_options = [o for o in options if o.net_expected_value > 0 and o.recommendation_id is not None]

        scores: Dict[str, float] = {}
        for opt in candidates:
            scores[opt.option_id] = self._score(opt, positive_options)

        remaining_sprints = self._remaining_sprints(state)
        brooks_check = self._brooks_law_check(candidates, remaining_sprints)

        warning: Optional[str] = None
        if candidates and any(s > 0 for s in scores.values()):
            winner = max(candidates, key=lambda o: scores[o.option_id])
            winner_score = scores[winner.option_id]
        else:
            # All options scored <= 0 (or there are no candidates at all):
            # fall back to the null (do-nothing) option, flagged with a warning.
            winner = null_option
            winner_score = null_option.net_expected_value if null_option else 0.0
            warning = "All candidate options scored <= 0; defaulting to do-nothing."

        # Rejected alternatives: every non-winning, non-null option, sorted DESC by score.
        rejected_alts: List[RejectedAlternative] = []
        for opt in sorted(candidates, key=lambda o: scores[o.option_id], reverse=True):
            if winner is not None and opt.option_id == winner.option_id:
                continue
            reason = self._rejection_reason(
                opt, scores[opt.option_id], winner, winner_score,
                brooks_check, remaining_sprints,
            )
            rejected_alts.append(
                RejectedAlternative(
                    option=opt,
                    score=round(scores[opt.option_id], 4),
                    rejection_reason=reason,
                )
            )

        feasibility = self._feasibility_check(
            winner, state, brooks_check, remaining_sprints
        )

        rationale = self._rationale(winner, winner_score, diagnosis, rejected_alts)

        confidence = float(diagnosis.confidence) if diagnosis is not None else 0.5

        chosen_id = winner.recommendation_id if winner is not None else None

        return Decision(
            id=f"dec-{uuid4().hex[:10]}",
            chosen_option=winner,
            weighted_score=round(winner_score, 4),
            rationale=rationale,
            rejected_alternatives=rejected_alts,
            expected_value=(winner.net_expected_value if winner is not None else None),
            confidence=round(confidence, 4),
            feasibility_check=feasibility,
            brooks_law_check=brooks_check,
            warning=warning,
            # legacy aliases
            decision_id=f"dec-{uuid4().hex[:10]}",
            chosen_option_id=chosen_id,
            rejected_option_ids=[ra.option.recommendation_id for ra in rejected_alts if ra.option.recommendation_id],
            rejected_reasons={
                ra.option.recommendation_id: ra.rejection_reason
                for ra in rejected_alts if ra.option.recommendation_id
            },
            feasibility_gates_passed=(feasibility.organizational_feasible and feasibility.engineering_feasible),
        )

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _score(self, option: TradeoffOption, positive_options: List[TradeoffOption]) -> float:
        raw_score = sum(
            option.gains.get(dim, 0.0) * weight
            - option.sacrifices.get(dim, 0.0) * weight * 0.5
            for dim, weight in WEIGHTS.items()
        )
        if option.disruption_level == "HIGH":
            if len(positive_options) > 1:
                raw_score *= _DISRUPTION_PENALTY
        return raw_score

    # ------------------------------------------------------------------
    # Brooks's Law
    # ------------------------------------------------------------------

    def _remaining_sprints(self, state: ProjectState) -> int:
        sprints = getattr(state, "sprints", []) or []
        remaining = 0
        for s in sprints:
            status = getattr(s, "status", None)
            status_val = getattr(status, "value", status)
            if status_val not in _DONE_SPRINT_STATUSES:
                remaining += 1
        return remaining

    @staticmethod
    def _is_add_resource(option: TradeoffOption) -> bool:
        return "brooks" in (option.sacrifice_statement or "").lower()

    @staticmethod
    def _is_resolve_blocker(option: TradeoffOption) -> bool:
        return "deprioritize" in (option.sacrifice_statement or "").lower()

    @staticmethod
    def _extract_blocker_owner(option: TradeoffOption) -> Optional[str]:
        m = re.search(r"requires (.+?) to deprioritize", option.sacrifice_statement or "")
        return m.group(1).strip() if m else None

    def _brooks_law_check(
        self, candidates: List[TradeoffOption], remaining_sprints: int
    ) -> Optional[BrooksLawCheck]:
        add_resource_present = any(self._is_add_resource(o) for o in candidates)
        if not add_resource_present:
            return None

        if remaining_sprints < 2:
            verdict = "REJECT"
        elif remaining_sprints < 3:
            verdict = "RISKY"
        else:
            verdict = "SAFE"

        if verdict == "REJECT":
            tail = "creates coordination overhead that historically worsens delivery"
        elif verdict == "RISKY":
            tail = "carries ramp-up risk"
        else:
            tail = "is feasible with adequate onboarding time"

        reasoning = (
            f"Adding capacity with {remaining_sprints} sprints remaining {tail}."
        )

        return BrooksLawCheck(
            triggered=True,
            ramp_window_sprints=remaining_sprints,
            verdict=verdict,
            reasoning=reasoning,
        )

    # ------------------------------------------------------------------
    # Feasibility
    # ------------------------------------------------------------------

    def _feasibility_check(
        self,
        winner: Optional[TradeoffOption],
        state: ProjectState,
        brooks_check: Optional[BrooksLawCheck],
        remaining_sprints: int,
    ) -> FeasibilityCheck:
        organizational_feasible = True
        blockers: List[str] = []

        if winner is not None and self._is_resolve_blocker(winner):
            owner = self._extract_blocker_owner(winner)
            team_names = {getattr(r, "name", None) for r in (getattr(state, "team", []) or [])}
            if owner and owner not in team_names:
                organizational_feasible = False
                blockers.append(
                    f"Owner '{owner}' is not on this team — escalation to {owner} required"
                )

        if winner is not None and self._is_add_resource(winner) and brooks_check is not None:
            if brooks_check.verdict == "REJECT":
                organizational_feasible = False
                blockers.append(
                    f"Brooks's Law: adding capacity with {remaining_sprints} sprints "
                    f"remaining is likely to worsen delivery"
                )

        return FeasibilityCheck(
            engineering_feasible=True,
            organizational_feasible=organizational_feasible,
            blockers=blockers,
        )

    # ------------------------------------------------------------------
    # Rationale + rejection reasons
    # ------------------------------------------------------------------

    def _rationale(
        self,
        winner: Optional[TradeoffOption],
        winner_score: float,
        diagnosis: Optional[Diagnosis],
        rejected_alts: List[RejectedAlternative],
    ) -> str:
        if winner is None:
            return "No viable option was found; no action is recommended."

        addresses_root_cause = bool(
            diagnosis
            and diagnosis.root_cause
            and diagnosis.root_cause.lower() in (winner.label or "").lower()
        )
        reason_clause = (
            "directly addresses the root cause"
            if addresses_root_cause
            else "produces the highest expected schedule recovery"
        )
        disruption_clause = "low" if winner.disruption_level == "LOW" else "medium"

        sentence_1 = (
            f"{winner.label} (score: {winner_score:.1f}) is the recommended action "
            f"because it {reason_clause} and recovers the most value with "
            f"{disruption_clause} disruption."
        )

        if rejected_alts:
            top_rejected = rejected_alts[0]
            sentence_2 = (
                f"{top_rejected.option.label} (score: {top_rejected.score:.1f}) "
                f"was rejected: {top_rejected.rejection_reason}"
            )
            return f"{sentence_1} {sentence_2}"

        return sentence_1

    def _rejection_reason(
        self,
        option: TradeoffOption,
        score: float,
        winner: Optional[TradeoffOption],
        winner_score: float,
        brooks_check: Optional[BrooksLawCheck],
        remaining_sprints: int,
    ) -> str:
        base = f"{option.label} scored {score:.1f} vs chosen {winner_score:.1f}. "

        if self._is_add_resource(option) and brooks_check is not None and brooks_check.verdict != "SAFE":
            return base + f"Brooks's Law risk with {remaining_sprints} sprints remaining."

        if option.disruption_level == "HIGH":
            return base + "Higher disruption (HIGH) penalised 20% in scoring."

        winner_schedule_gain = winner.gains.get("SCHEDULE", 0.0) if winner is not None else 0.0
        option_schedule_gain = option.gains.get("SCHEDULE", 0.0)
        return base + (
            f"Lower schedule recovery ({option_schedule_gain:.1f}d "
            f"vs {winner_schedule_gain:.1f}d)."
        )