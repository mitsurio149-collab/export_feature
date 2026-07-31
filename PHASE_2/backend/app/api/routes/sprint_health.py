"""
Sprint Health — deep root cause analysis from a project manager's perspective.

GET /api/sprint-health?session_id=<id>

Classifies every spillover and overbilling event into one of 8 root cause
categories using domain-aware skill affinity (e.g. CANoe Scripting ≈ HIL Testing
& CANoe Automation, not a mismatch). Each case gets:
  - A plain-English explanation
  - A concrete preventive action for future sprints
  - Severity rating
Per-person competency profiles and team-wide systemic prevention recommendations
are derived from the aggregate pattern.
"""
from fastapi import APIRouter, HTTPException, Query
from typing import Dict, List, Any
from app.api.models import ApiResponse
from app.storage.session_store import get_or_build_pipeline_result, store
from app.domain.models import WorkItemStatus

router = APIRouter(prefix="/api", tags=["Sprint Health"])

# ── Domain skill affinity groups ──────────────────────────────────────────────
# Skills in the same group are functionally related. Assigning someone whose
# primary/secondary is in the RELATED group is a "related skill" case, not a
# genuine mismatch — but may still show a competency gap.
SKILL_AFFINITY: Dict[str, List[str]] = {
    "CANoe Scripting":                  ["HIL Testing & CANoe Automation", "Regression & Integration Testing"],
    "HIL Testing & CANoe Automation":   ["CANoe Scripting", "Regression & Integration Testing"],
    "Regression & Integration Testing": ["HIL Testing & CANoe Automation", "CANoe Scripting"],
    "COM Stack & Signal Mapping":       ["CAN / J1939 Protocol Development", "PDU Configuration"],
    "CAN / J1939 Protocol Development": ["COM Stack & Signal Mapping", "PDU Configuration"],
    "PDU Configuration":                ["ECU Integration & Gateway Routing", "CAN / J1939 Protocol Development", "COM Stack & Signal Mapping"],
    "DCM / DEM Module Configuration":   ["UDS Diagnostics & DTC Management"],
    "UDS Diagnostics & DTC Management": ["DCM / DEM Module Configuration"],
    "SecOC & Secure Boot":              ["Automotive Cybersecurity (EVITA)"],
    "Automotive Cybersecurity (EVITA)": ["SecOC & Secure Boot"],
    "MCAL Driver Integration":          ["AUTOSAR Stack Configuration"],
    "AUTOSAR Stack Configuration":      ["MCAL Driver Integration", "ECU Integration & Gateway Routing"],
    "ECU Integration & Gateway Routing":["MCAL Driver Integration", "PDU Configuration", "AUTOSAR Stack Configuration"],
    "Backend API Integration":          ["OTA Firmware Update Mechanisms", "Manifest & Delta Packaging"],
    "OTA Firmware Update Mechanisms":   ["Backend API Integration", "Manifest & Delta Packaging"],
    "Manifest & Delta Packaging":       ["OTA Firmware Update Mechanisms", "Backend API Integration"],
}

ROOT_CAUSE_LABELS = {
    "GENUINE_SKILL_MISMATCH":           ("Genuine Skill Mismatch",           "rose",   "HIGH"),
    "RELATED_SKILL_COMPETENCY_GAP":     ("Related Skill — Competency Gap",   "orange", "HIGH"),
    "COMPETENCY_GAP_HIGH":              ("Competency Gap — Critical",        "rose",   "HIGH"),
    "COMPETENCY_GAP_MEDIUM":            ("Competency Gap — Moderate",        "amber",  "MEDIUM"),
    "DEPENDENCY_BLOCKED":               ("Dependency Blocked",               "sky",    "MEDIUM"),
    "EXTERNAL_BLOCKER":                 ("External Blocker",                 "rose",   "MEDIUM"),
    "CAPACITY_SQUEEZE_NOT_STARTED":     ("Capacity Squeeze — Not Started",   "amber",  "HIGH"),
    "CAPACITY_OVERCOMMIT":              ("Capacity Overcommit",              "amber",  "MEDIUM"),
    "ESTIMATION_DRIFT":                 ("Estimation Drift",                 "amber",  "LOW"),
    "MINOR_VARIANCE":                   ("Minor Variance",                   "slate",  "LOW"),
}

PREVENTION_TEMPLATES = {
    "GENUINE_SKILL_MISMATCH": {
        "explanation": (
            "Work required '{required}' but {owner} specialises in '{primary}' — "
            "these domains are unrelated. Working outside the skill domain inflates "
            "actual effort by 40–90% due to learning overhead and increased defect rate."
        ),
        "prevention": (
            "Add a skill-gate check in sprint planning: every item must match the owner's "
            "primary or a validated secondary skill before being committed. "
            "If no matching resource is available, flag the item for backlog restructuring "
            "rather than force-assigning it and absorbing the overrun silently."
        ),
        "sprint_action": "Skill-gate check in sprint planning",
        "metric_to_track": "% items with skill mismatch at sprint start (target: 0%)",
    },
    "RELATED_SKILL_COMPETENCY_GAP": {
        "explanation": (
            "'{required}' and '{primary}' are in the same domain group, so the assignment "
            "is defensible — but the {overrun}% effort overrun shows {owner} has not yet "
            "developed full depth in '{required}'. "
            "Example: HIL Testing & CANoe Automation is the right domain family, but "
            "scripting-intensive diagnostic test work (CANoe Scripting) requires deeper "
            "scripting proficiency than general automation."
        ),
        "prevention": (
            "Do not treat related-skill items as equivalent to primary-skill items in estimation. "
            "Apply a 1.4× complexity buffer for items where the owner's primary is 'related' "
            "but not an exact match. "
            "Schedule a targeted upskilling session for '{required}' within the next 2 sprints — "
            "pair {owner} with a primary-skill owner on similar items to close the gap faster."
        ),
        "sprint_action": "Apply 1.4× buffer + pair-programme on related-skill items",
        "metric_to_track": "Overrun % on related-skill items (target: <20%)",
    },
    "COMPETENCY_GAP_HIGH": {
        "explanation": (
            "Skill matched correctly ({owner} primary = '{required}') but actual effort "
            "was {overrun}% above estimate. This indicates the specific task complexity "
            "exceeded {owner}'s current depth in this skill — a common pattern for "
            "advancing-skill engineers taking on novel or high-complexity variants "
            "of otherwise familiar tasks."
        ),
        "prevention": (
            "Run a targeted skill-depth review for {owner} on '{required}' before the next sprint. "
            "Identify whether the overrun came from: (a) design complexity — needs senior review "
            "at task kickoff; (b) toolchain issues — needs environment preparation time; or "
            "(c) specification ambiguity — needs a Definition of Ready check before sprint start. "
            "Add a 1.3× estimate buffer for this person on similar tasks until "
            "overrun drops below 20% on two consecutive items."
        ),
        "sprint_action": "Skill-depth review + 1.3× buffer for next 2 sprints",
        "metric_to_track": "Overrun on '{required}' items for {owner} (target: <20%)",
    },
    "COMPETENCY_GAP_MEDIUM": {
        "explanation": (
            "Skill matched but actual effort was {overrun}% above estimate. "
            "{owner} has the right skills for '{required}' but is systematically "
            "underestimating complexity in this area — likely due to hidden dependencies "
            "or understated technical depth of the task."
        ),
        "prevention": (
            "Use actuals from this item as the new baseline estimate for similar tasks. "
            "Apply a 1.2× multiplier to '{required}' estimates for {owner} in the next sprint. "
            "Include a brief task kickoff discussion (15 min) where {owner} walks through "
            "their approach — this surfaces hidden complexity before it becomes an overrun."
        ),
        "sprint_action": "Actuals-based re-estimation + kickoff discussion",
        "metric_to_track": "'{required}' estimation accuracy for {owner} (target: ±15%)",
    },
    "DEPENDENCY_BLOCKED": {
        "explanation": (
            "Item could not complete because an upstream dependency was not ready. "
            "{owner} has the correct skill for '{required}' and the effort overrun "
            "is likely from rework or wait time, not competency. "
            "This is a planning failure, not a people failure."
        ),
        "prevention": (
            "Map all item dependencies before sprint commitment. "
            "Any item with an unresolved external dependency should be moved to a later sprint "
            "or split into a 'foundation' sub-item that can proceed independently. "
            "Set a mid-sprint dependency check-in (day 5) to catch blockers while there is "
            "still time to reassign capacity."
        ),
        "sprint_action": "Dependency mapping gate + day-5 check-in",
        "metric_to_track": "Items blocked by dependency at sprint end (target: 0)",
    },
    "EXTERNAL_BLOCKER": {
        "explanation": (
            "Item was impeded by an external factor (third-party team, tool unavailability, "
            "or infrastructure issue) rather than by skill or planning. "
            "{owner} could not progress despite having the right skills for '{required}'."
        ),
        "prevention": (
            "Log all external blockers with: blocker category, date raised, owner of resolution, "
            "and expected resolution date. Escalate to project manager if unresolved after 2 days. "
            "In the next sprint retrospective, identify whether this blocker was predictable "
            "and add it to the risk register if recurring."
        ),
        "sprint_action": "Blocker logging + 2-day escalation SLA",
        "metric_to_track": "External blockers resolved within 2 days (target: >80%)",
    },
    "CAPACITY_SQUEEZE_NOT_STARTED": {
        "explanation": (
            "{owner} was committed to more work than their sprint capacity allowed. "
            "'{item_title}' was not started — not because of skill gap, but because "
            "higher-priority items consumed all available hours. "
            "This is a capacity planning failure at sprint planning."
        ),
        "prevention": (
            "Cap {owner}'s sprint commitment at 80% of their available hours "
            "(reserve 20% for meetings, reviews, and unexpected complexity). "
            "If {owner} already has more than 80% capacity booked, escalate to the "
            "sprint planning meeting to explicitly defer lower-priority items rather "
            "than letting them silently spill over."
        ),
        "sprint_action": "Enforce 80% capacity cap in sprint planning",
        "metric_to_track": "Items not started at sprint end (target: 0)",
    },
    "CAPACITY_OVERCOMMIT": {
        "explanation": (
            "{owner} had the skill for '{required}' and completed the item, "
            "but the sprint was overcommitted — leaving insufficient buffer for "
            "the natural complexity variance that all engineering work has."
        ),
        "prevention": (
            "Review {owner}'s total sprint commitment at planning. "
            "If it exceeds 85% of sprint hours, remove the lowest-priority item. "
            "A 15% buffer absorbs normal estimation noise without requiring spillover."
        ),
        "sprint_action": "85% capacity rule at sprint planning",
        "metric_to_track": "Sprint over-commitment rate (target: <5% of sprints)",
    },
    "ESTIMATION_DRIFT": {
        "explanation": (
            "Skill matched correctly and overrun was modest ({overrun}%), "
            "within normal engineering estimation noise for this domain. "
            "However, if this pattern repeats it becomes a systematic drift "
            "that compounds across sprints."
        ),
        "prevention": (
            "Use historical actuals to anchor future estimates. "
            "If '{required}' items consistently run 15–25% over, apply a "
            "1.15–1.25× factor to the next sprint's estimates. "
            "Track the rolling mean overrun per task category per person quarterly."
        ),
        "sprint_action": "Update estimates with actuals-based correction factor",
        "metric_to_track": "Rolling mean overrun for '{required}' items (target: <15%)",
    },
}


def _safe(obj, *attrs, default=None):
    for attr in attrs:
        if obj is None:
            return default
        obj = getattr(obj, attr, None)
    return obj if obj is not None else default


def _is_exact_match(required: str, primary: str, secondary: str) -> bool:
    return required == primary or required == secondary


def _is_affinity_match(required: str, primary: str, secondary: str) -> bool:
    related = SKILL_AFFINITY.get(required, [])
    return primary in related or secondary in related


def _classify(required: str, primary: str, secondary: str,
              est: float, actual: float, spillover_reason: str | None) -> tuple:
    """Return (root_cause_key, overrun_pct)."""
    exact = _is_exact_match(required, primary, secondary)
    affinity = _is_affinity_match(required, primary, secondary)
    overrun = round((actual / est - 1) * 100) if est > 0 and actual > 0 else None

    if not exact and not affinity:
        return "GENUINE_SKILL_MISMATCH", overrun

    if not exact and affinity:
        if overrun is not None and overrun > 35:
            return "RELATED_SKILL_COMPETENCY_GAP", overrun
        return "ESTIMATION_DRIFT", overrun

    # Exact match
    if spillover_reason == "DEPENDENCY":
        return "DEPENDENCY_BLOCKED", overrun
    if spillover_reason == "BLOCKER":
        return "EXTERNAL_BLOCKER", overrun
    if actual == 0 and est > 0:
        return "CAPACITY_SQUEEZE_NOT_STARTED", overrun
    if overrun is None:
        return "MINOR_VARIANCE", overrun
    if overrun > 55:
        return "COMPETENCY_GAP_HIGH", overrun
    if overrun > 25:
        return "COMPETENCY_GAP_MEDIUM", overrun
    if overrun > 12:
        return "ESTIMATION_DRIFT", overrun
    return "MINOR_VARIANCE", overrun


def _format_template(template: str, **ctx) -> str:
    try:
        return template.format(**ctx)
    except KeyError:
        return template


def _build_item_record(item_id, title, sprint_id, owner, required_skill,
                       primary_skill, secondary_skill, est_hrs, actual_hrs,
                       spillover_reason, is_spillover,
                       from_sprint=None, to_sprint=None, sprints_delayed=None) -> Dict:
    rc_key, overrun = _classify(
        required_skill or "",
        primary_skill or "",
        secondary_skill or "",
        est_hrs, actual_hrs, spillover_reason
    )
    label, color, severity = ROOT_CAUSE_LABELS.get(rc_key, ("Unknown", "slate", "LOW"))
    tmpl = PREVENTION_TEMPLATES.get(rc_key, {})

    ctx = dict(
        required=required_skill or "unknown",
        primary=primary_skill or "unknown",
        owner=owner or "unknown",
        overrun=overrun if overrun is not None else 0,
        item_title=title or item_id,
    )

    explanation = _format_template(tmpl.get("explanation", "No analysis available."), **ctx)
    prevention  = _format_template(tmpl.get("prevention", "Review during retrospective."), **ctx)
    metric      = _format_template(tmpl.get("metric_to_track", ""), **ctx)
    sprint_action = tmpl.get("sprint_action", "Review during retrospective")

    record = {
        "item_id":          item_id,
        "item_title":       title or item_id,
        "sprint_id":        sprint_id or "",
        "owner":            owner or "",
        "required_skill":   required_skill or "",
        "owner_primary":    primary_skill or "",
        "owner_secondary":  secondary_skill or "",
        "estimated_hrs":    est_hrs,
        "actual_hrs":       actual_hrs,
        "overrun_hrs":      round(actual_hrs - est_hrs, 1) if actual_hrs > 0 else None,
        "overrun_pct":      overrun,
        "root_cause":       rc_key,
        "root_cause_label": label,
        "root_cause_color": color,
        "severity":         severity,
        "exact_skill_match":   _is_exact_match(required_skill or "", primary_skill or "", secondary_skill or ""),
        "affinity_match":      _is_affinity_match(required_skill or "", primary_skill or "", secondary_skill or ""),
        "explanation":         explanation,
        "prevention":          prevention,
        "sprint_action":       sprint_action,
        "metric_to_track":     metric,
        "is_spillover":        is_spillover,
    }
    if is_spillover:
        record.update({
            "from_sprint":    from_sprint,
            "to_sprint":      to_sprint,
            "sprints_delayed": sprints_delayed,
            "spillover_reason_raw": spillover_reason,
        })
    return record


@router.get("/sprint-health")
def get_sprint_health(session_id: str = Query(...)):
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        result = get_or_build_pipeline_result(session_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    hist = getattr(result, "historical_analysis", None)
    if hist is None:
        raise HTTPException(status_code=404, detail="Historical analysis not available")
    state = store.get_project_state(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Project state not found")

    wi_map  = {w.item_id: w for w in state.work_items}
    res_map = {r.resource_id: r for r in state.team}

    # ── Spillover items ────────────────────────────────────────────────────────
    spillover_items = []
    for sp in (getattr(hist, "spillover", []) or []):
        wi  = wi_map.get(sp.item_id)
        if not wi:
            continue
        res = res_map.get(wi.assigned_resource)
        rec = _build_item_record(
            item_id         = sp.item_id,
            title           = getattr(sp, "item_title", wi.item_id),
            sprint_id       = getattr(sp, "original_sprint", ""),
            owner           = wi.assigned_resource,
            required_skill  = wi.required_skill,
            primary_skill   = _safe(res, "primary_skill"),
            secondary_skill = _safe(res, "secondary_skill"),
            est_hrs         = float(wi.estimated_effort_hrs or 0),
            actual_hrs      = float(wi.actual_effort_hrs or 0),
            spillover_reason= sp.reason_category,
            is_spillover    = True,
            from_sprint     = sp.original_sprint,
            to_sprint       = sp.landed_sprint,
            sprints_delayed = sp.sprints_delayed,
        )
        spillover_items.append(rec)

    # ── Overbilling items ──────────────────────────────────────────────────────
    # Exclude items already captured as spillover — same WI can appear in both
    # the historical_analyzer's overbilling and spillover lists when a spilled
    # item was eventually closed with hours > estimate. Showing it in both tabs
    # confuses readers; spillover is the primary classification in that case.
    _spillover_ids = {s["item_id"] for s in spillover_items}
    overbilling_items = []
    for o in sorted(getattr(hist, "overbilling", []) or [], key=lambda x: x.overrun_pct, reverse=True):
        wi  = wi_map.get(o.item_id)
        if not wi:
            continue
        if o.item_id in _spillover_ids:
            continue
        res = res_map.get(wi.assigned_resource)
        rec = _build_item_record(
            item_id         = o.item_id,
            title           = getattr(o, "item_title", o.item_id),
            sprint_id       = o.sprint_id,
            owner           = wi.assigned_resource,
            required_skill  = wi.required_skill,
            primary_skill   = _safe(res, "primary_skill"),
            secondary_skill = _safe(res, "secondary_skill"),
            est_hrs         = float(o.estimated_hrs or 0),
            actual_hrs      = float(o.actual_hrs or 0),
            spillover_reason= None,
            is_spillover    = False,
        )
        overbilling_items.append(rec)

    # ── Per-person competency profiles ────────────────────────────────────────
    from collections import defaultdict
    person_items: Dict[str, List] = defaultdict(list)
    for item in spillover_items + overbilling_items:
        person_items[item["owner"]].append(item)

    people = []
    for r in state.team:
        rid   = r.resource_id
        items = person_items.get(rid, [])

        by_rc: Dict[str, int] = defaultdict(int)
        for it in items:
            by_rc[it["root_cause"]] += 1

        high_sev   = [i for i in items if i["severity"] == "HIGH"]
        medium_sev = [i for i in items if i["severity"] == "MEDIUM"]
        overruns   = [i["overrun_pct"] for i in items if i.get("overrun_pct") is not None]
        avg_overrun = round(sum(overruns) / len(overruns)) if overruns else 0

        genuines  = by_rc.get("GENUINE_SKILL_MISMATCH", 0)
        related_gaps = by_rc.get("RELATED_SKILL_COMPETENCY_GAP", 0)
        comp_high = by_rc.get("COMPETENCY_GAP_HIGH", 0)
        comp_med  = by_rc.get("COMPETENCY_GAP_MEDIUM", 0)
        capacity  = by_rc.get("CAPACITY_SQUEEZE_NOT_STARTED", 0) + by_rc.get("CAPACITY_OVERCOMMIT", 0)
        dep_blocked = by_rc.get("DEPENDENCY_BLOCKED", 0)

        if genuines >= 1 or comp_high >= 2 or avg_overrun > 60:
            health, health_label, health_color = "NEEDS_IMPROVEMENT", "Needs improvement", "rose"
        elif related_gaps >= 1 or comp_high >= 1 or comp_med >= 2 or avg_overrun > 35:
            health, health_label, health_color = "WATCH",            "Watch",             "amber"
        elif len(items) > 0:
            health, health_label, health_color = "MINOR_ISSUES",     "Minor issues",      "sky"
        else:
            health, health_label, health_color = "GOOD",             "Good",              "emerald"

        # Per-person action plan
        actions = []
        if genuines:
            actions.append({
                "priority": "CRITICAL",
                "type": "SKILL_ASSIGNMENT_GATE",
                "action": (
                    f"Immediate: audit all remaining sprint backlog items assigned to {rid}. "
                    f"Found {genuines} item(s) outside their skill domain. "
                    f"Reassign or pair before next sprint starts."
                ),
            })
        if related_gaps:
            actions.append({
                "priority": "HIGH",
                "type": "RELATED_SKILL_UPSKILLING",
                "action": (
                    f"Schedule a focused upskilling session for {rid} on the specific sub-skills "
                    f"where overrun exceeded 35% despite domain affinity. "
                    f"Apply 1.4× estimate buffer until two consecutive items come in under 20% overrun."
                ),
            })
        if comp_high:
            actions.append({
                "priority": "HIGH",
                "type": "COMPETENCY_DEVELOPMENT",
                "action": (
                    f"Run a skill-depth review with {rid}'s tech lead for '{r.primary_skill}'. "
                    f"Identify whether overruns come from design complexity, toolchain gaps, or "
                    f"specification ambiguity — each has a different fix. "
                    f"Add 1.3× buffer on advanced items for the next 2 sprints."
                ),
            })
        if capacity:
            actions.append({
                "priority": "HIGH",
                "type": "CAPACITY_PLANNING",
                "action": (
                    f"Enforce 80% capacity cap for {rid} in sprint planning. "
                    f"Found {capacity} item(s) that could not start due to overcommitment. "
                    f"If the backlog pressure remains, escalate to re-prioritise scope."
                ),
            })
        if dep_blocked:
            actions.append({
                "priority": "MEDIUM",
                "type": "DEPENDENCY_MANAGEMENT",
                "action": (
                    f"Before committing {rid}'s items, verify all upstream dependencies are "
                    f"resolved or have a confirmed completion date within the sprint window. "
                    f"Set a day-5 check-in to catch blocked items early."
                ),
            })
        if not actions and health == "GOOD":
            actions.append({
                "priority": "INFO",
                "type": "MAINTAIN",
                "action": f"No issues detected for {rid}. Maintain current assignment and estimation practices.",
            })

        total_assigned = [w for w in state.work_items if w.assigned_resource == rid]
        _done_statuses = {WorkItemStatus.DONE, WorkItemStatus.COMPLETED}
        completed = [w for w in total_assigned if w.status in _done_statuses]

        people.append({
            "resource_id":          rid,
            "name":                 getattr(r, "name", rid),
            "primary_skill":        r.primary_skill,
            "secondary_skill":      r.secondary_skill,
            "total_assigned":       len(total_assigned),
            "completed_count":      len(completed),
            "total_issues":         len(items),
            "spillover_count":      sum(1 for i in items if i["is_spillover"]),
            "overbilling_count":    sum(1 for i in items if not i["is_spillover"]),
            "high_severity_count":  len(high_sev),
            "avg_overrun_pct":      avg_overrun,
            "root_cause_breakdown": dict(by_rc),
            "health":               health,
            "health_label":         health_label,
            "health_color":         health_color,
            "action_plan":          actions,
        })

    # ── Summary ────────────────────────────────────────────────────────────────
    all_items = spillover_items + overbilling_items
    rc_dist: Dict[str, int] = defaultdict(int)
    for it in all_items:
        rc_dist[it["root_cause"]] += 1

    total_waste = sum(i["overrun_hrs"] for i in all_items if i.get("overrun_hrs"))

    # Team-wide systemic recommendations
    systemic = []
    if rc_dist["GENUINE_SKILL_MISMATCH"] > 0:
        systemic.append({
            "trigger": "Genuine skill mismatches detected",
            "finding": f"{rc_dist['GENUINE_SKILL_MISMATCH']} item(s) assigned to owners with no domain connection.",
            "action":  "Introduce a mandatory skill-match gate in sprint planning. Before finalising assignments, each item's required skill must appear in the owner's primary or validated secondary skill list.",
            "sprint":  "Next sprint planning",
            "priority": "CRITICAL",
        })
    if rc_dist["RELATED_SKILL_COMPETENCY_GAP"] > 0:
        systemic.append({
            "trigger": "Related-skill competency gaps",
            "finding": f"{rc_dist['RELATED_SKILL_COMPETENCY_GAP']} item(s) assigned within the correct domain family but with >35% effort overrun — the owner is not yet at full depth in the specific sub-skill.",
            "action":  "Do not treat related skills as equivalent in estimation. Apply 1.4× buffer for related-skill items and schedule domain-specific upskilling (pairing, workshops, or deliberate practice items in the next sprint).",
            "sprint":  "Next sprint planning",
            "priority": "HIGH",
        })
    if (rc_dist["COMPETENCY_GAP_HIGH"] + rc_dist["COMPETENCY_GAP_MEDIUM"]) > 2:
        systemic.append({
            "trigger": "Systemic competency gaps on matched skills",
            "finding": f"{rc_dist['COMPETENCY_GAP_HIGH'] + rc_dist['COMPETENCY_GAP_MEDIUM']} item(s) with correct skill assignment but consistent effort overruns — suggests the team is taking on tasks at the leading edge of their expertise faster than skill growth can keep up.",
            "action":  "Build a sprint 'skill investment' budget: dedicate 10% of each sprint to deliberate practice items (lower stakes, high learning value). Review estimation accuracy per skill per person quarterly and update reference estimates from actuals.",
            "sprint":  "Sprint planning review",
            "priority": "HIGH",
        })
    if (rc_dist["CAPACITY_SQUEEZE_NOT_STARTED"] + rc_dist["CAPACITY_OVERCOMMIT"]) > 1:
        systemic.append({
            "trigger": "Recurring capacity overcommitment",
            "finding": f"{rc_dist['CAPACITY_SQUEEZE_NOT_STARTED'] + rc_dist['CAPACITY_OVERCOMMIT']} capacity-driven events across {getattr(hist,'sprints_analysed',0)} sprints. Sprint velocity is being set by aspiration, not by data.",
            "action":  "Set sprint commitment to 80% of team capacity at planning. Use the rolling average of actual velocity from the last 3 sprints as the ceiling, not the theoretical capacity. Treat the 20% buffer as non-negotiable, not as slack to fill.",
            "sprint":  "Immediately — enforce from next sprint",
            "priority": "HIGH",
        })
    if rc_dist["DEPENDENCY_BLOCKED"] > 0:
        systemic.append({
            "trigger": "Dependency-driven spillover",
            "finding": f"{rc_dist['DEPENDENCY_BLOCKED']} item(s) delayed by unresolved upstream dependencies at sprint start.",
            "action":  "Add a dependency resolution check to the Definition of Ready. No item enters a sprint unless all its upstream dependencies are either done or have a confirmed completion date within the first 3 days of the sprint.",
            "sprint":  "Implement in DoR template this sprint",
            "priority": "MEDIUM",
        })

    historical_prevention = [
        {
            "trigger": r.trigger,
            "action":  r.action,
            "sprint_to_apply": r.sprint_to_apply,
            "confidence": r.confidence,
            "evidence": r.evidence[:3] if r.evidence else [],
        }
        for r in (getattr(hist, "prevention_recommendations", []) or [])
    ]

    summary = {
        "sprints_analysed":       getattr(hist, "sprints_analysed", 0),
        "total_spillover":        len(spillover_items),
        "total_overbilling":      len(overbilling_items),
        "total_wasted_hrs":       round(total_waste, 1),
        "root_cause_distribution": dict(rc_dist),
        "people_critical":        sum(1 for p in people if p["health"] == "NEEDS_IMPROVEMENT"),
        "people_watch":           sum(1 for p in people if p["health"] == "WATCH"),
        "systemic_actions":       systemic,
        "historical_prevention":  historical_prevention,
        "overall_summary":        getattr(hist, "summary", ""),
    }

    return ApiResponse(
        success=True,
        message="Sprint health analysis retrieved",
        data={
            "summary":         summary,
            "people":          people,
            "spillover_items": spillover_items,
            "overbilling_items": overbilling_items,
        },
    )
