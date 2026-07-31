"""
test_workbook_parser_resource_fields.py

Batch B.1 regression coverage for two confirmed parser-level findings:

1. "Skill 3" (a genuine third skill column in the Team sheet, alongside
   "Skill 1"/"Skill 2") was not parsed at all, so a resource whose only
   matching skill is Skill 3 was invisible to ResourceIntelligence /
   covers_skill() feasibility checks. FIXED in workbook_parser.py.

2. Explicit `0` allocation/availability must survive parsing as 0.0, not be
   silently replaced by a default. This was ALREADY correct
   (`_average_pct_columns` uses `value is not None`, not `if value:`) --
   this test locks that behavior in as a regression guard.

Both tests build a minimal but complete in-memory workbook (all
REQUIRED_SHEETS, correct Row1/Row2/Row3+ layout) and drive the real
WorkbookParser end-to-end, rather than calling private parser methods
directly -- this is the actual "Workbook row -> parser -> Resource ->
ResourceIntelligence -> covers_skill()" path asked for.
"""

import tempfile
import os
import openpyxl
import pytest

from app.parsers.workbook_parser import WorkbookParser
from app.engines.resource_intelligence import ResourceIntelligence

def _write_minimal_workbook(path: str, *, skill3_value: str, alloc_pct, avail_pct,
                            sprint_pcts=None):
    """Build the smallest workbook that satisfies WorkbookParser.REQUIRED_SHEETS
    and every column it reads as a *required* (non-optional) field, with one
    resource whose only matching skill is `skill3_value`, and configurable
    Alloc/Avail % (to test the explicit-zero case).

    `sprint_pcts`, if given, is a list of (alloc, avail) tuples -- one entry
    per sprint -- used to populate "S{n} Alloc %" / "S{n} Avail %" columns
    AND to create that many rows in Sprint_Plan (so sprint_number/sprint_id
    generation lines up exactly the way the real parser does it). When
    omitted, a single Sprint 1 row and single S1 Alloc/Avail pair are used
    (backward compatible with the original two tests below)."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    def sheet(name, title_cols, header, rows):
        ws = wb.create_sheet(name)
        ws.append(title_cols)
        ws.append(header)
        for r in rows:
            ws.append(r)

    sheet(
        "Project_Info",
        ["Title"],
        ["Project Name", "Sponsor", "Business Unit", "Project Manager",
         "Start Date", "Target End Date", "Sprint Length (Days)",
         "Methodology", "Customer", "Status"],
        [["Test Project", "Sponsor", "BU", "PM",
          "2026-01-01", "2026-12-31", 14, "Agile Scrum", "Cust", "Active"]],
    )

    if sprint_pcts is None:
        sprint_pcts = [(alloc_pct, avail_pct)]

    team_header = ["Resource Name", "Role", "Skill 1", "Skill 1 Level", "Skill 2",
                   "Skill 2 Level", "Skill 3", "Skill 3 Level"]
    team_row = ["Test Resource", "Engineer", "Primary Skill", "Senior",
                "Secondary Skill", "Mid", skill3_value, "Advanced"]
    for i, (a, v) in enumerate(sprint_pcts, start=1):
        team_header += [f"S{i} Alloc %", f"S{i} Avail %"]
        team_row += [a, v]
    sheet("Team", ["Title"], team_header, [team_row])

    sprint_header = ["Sprint Name", "Start Date", "End Date", "Duration (Days)",
                     "Sprint Goal", "Status", "Velocity (h)", "Carry-Over Items"]
    sprint_rows = []
    for i in range(1, len(sprint_pcts) + 1):
        start = f"2026-{i:02d}-01"
        end = f"2026-{i:02d}-14"
        sprint_rows.append([f"Sprint {i}", start, end, 14, "Goal",
                             "Not Started", 40, 0])
    sheet("Sprint_Plan", ["Title"], sprint_header, sprint_rows)

    sheet(
        "Work_Items",
        ["Title"],
        ["Task ID", "Task Name", "Type", "Sprint", "Orig. Sprint", "Owner",
         "Required Skill", "Priority", "Orig Est (h)", "Curr Est (h)",
         "Actual Hrs", "Remaining Hrs", "Progress %", "Status",
         "Scope Change", "Scope Reason"],
        [["WI-001", "Some Task", "Task", "Sprint 1", "Sprint 1",
          "Test Resource", (skill3_value or "Primary Skill"), "Medium", 10, 10, 0, 10, 0,
          "Not Started", "No", None]],
    )

    sheet(
        "Dependencies",
        ["Title"],
        ["Dep ID", "Predecessor Task", "Successor Task",
         "Dependency Type", "Lag Days"],
        [],
    )

    sheet(
        "Blockers",
        ["Title"],
        ["Blocker ID", "Related Task", "Impacted Task IDs", "Severity",
         "Status", "Owner", "Raised Date", "Target Resolution",
         "Actual Resolution", "Category", "Sprint Identified", "Notes"],
        [],
    )

    wb.save(path)


def test_skill_3_survives_parsing_and_is_recognized_by_resource_intelligence():
    """Workbook row -> parser -> Resource -> ResourceIntelligence -> covers_skill()
    recognizes a resource whose ONLY matching skill is Skill 3."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "wb.xlsx")
        _write_minimal_workbook(
            path, skill3_value="Tertiary Skill X", alloc_pct=1, avail_pct=1
        )

        state = WorkbookParser(path).parse()
        resource = state.team[0]

        # Skill 3 must not collide with / overwrite Skill 1 or Skill 2.
        assert resource.primary_skill == "Primary Skill"
        assert resource.secondary_skill == "Secondary Skill"

        # It must have reached the canonical skill_coverage representation,
        # not a separate, ad-hoc field.
        assert any(sc.skill == "Tertiary Skill X" for sc in resource.skill_coverage)

        # And ResourceIntelligence's feasibility path (same one used for
        # Skill 1/2) must recognize it -- this is the actual regression
        # guard: before the fix, a work item requiring only "Tertiary Skill X"
        # would show this resource as infeasible.
        ri = ResourceIntelligence(state)
        assert resource.covers_skill("Tertiary Skill X") is True

        item = next(w for w in state.work_items if w.item_id == "WI-001")
        assert item.required_skill == "Tertiary Skill X"
        evidence = ri.evidence(resource, item, "Sprint 1")
        assert evidence.skill_match is True


def test_skill_3_missing_does_not_break_parsing():
    """A resource with no Skill 3 value must parse cleanly with empty
    skill_coverage -- Skill 3 is optional, same as Skill 2."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "wb.xlsx")
        _write_minimal_workbook(path, skill3_value=None, alloc_pct=1, avail_pct=1)

        state = WorkbookParser(path).parse()
        resource = state.team[0]
        assert resource.skill_coverage == []


@pytest.mark.parametrize("alloc,avail", [(0, 1), (1, 0), (0, 0)])
def test_explicit_zero_allocation_or_availability_survives_parsing(alloc, avail):
    """Regression guard: explicit 0 is valid business data (fully allocated-
    out or fully unavailable resource) and must parse as 0.0, not fall back
    to a nonzero default. This was already correct
    (`_average_pct_columns` checks `value is not None`) -- this test locks
    it in."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "wb.xlsx")
        _write_minimal_workbook(
            path, skill3_value="Tertiary Skill X", alloc_pct=alloc, avail_pct=avail
        )

        state = WorkbookParser(path).parse()
        resource = state.team[0]
        assert resource.allocation_pct == pytest.approx(float(alloc))
        assert resource.availability_pct == pytest.approx(float(avail))


def test_per_sprint_allocation_availability_survive_parsing():
    """The workbook's real per-sprint columns (S1 Alloc %/S1 Avail % ..
    S{n} Alloc %/S{n} Avail %) must reach Resource.sprint_allocation_pct /
    sprint_availability_pct keyed by the SAME sprint_id the parser already
    generates for Sprint_Plan rows (SPR-1, SPR-2, SPR-3 for this fixture's
    3 sprints) -- not averaged away, and not a newly invented ID scheme."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "wb.xlsx")
        # Sprint 1: 100%/100%, Sprint 2: 50%/80%, Sprint 3 (our "Sprint 6"
        # stand-in for a distinct later sprint): 20%/40%.
        _write_minimal_workbook(
            path, skill3_value="Tertiary Skill X", alloc_pct=1, avail_pct=1,
            sprint_pcts=[(1.0, 1.0), (0.5, 0.8), (0.2, 0.4)],
        )
        state = WorkbookParser(path).parse()
        resource = state.team[0]

        assert resource.sprint_allocation_pct == {
            "SPR-1": 1.0, "SPR-2": 0.5, "SPR-3": 0.2,
        }
        assert resource.sprint_availability_pct == {
            "SPR-1": 1.0, "SPR-2": 0.8, "SPR-3": 0.4,
        }
        # The aggregate scalar fallback must still be the average across all
        # sprint columns (backward-compatible, unchanged formula).
        assert resource.allocation_pct == pytest.approx((1.0 + 0.5 + 0.2) / 3)
        assert resource.availability_pct == pytest.approx((1.0 + 0.8 + 0.4) / 3)


def test_sprint_specific_lookup_returns_sprint_value_not_project_average():
    """A specific sprint's ResourceIntelligence capacity must reflect THAT
    sprint's allocation/availability, not the project-wide average -- this
    is the actual regression the averaging bug caused."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "wb.xlsx")
        _write_minimal_workbook(
            path, skill3_value="Tertiary Skill X", alloc_pct=1, avail_pct=1,
            sprint_pcts=[(1.0, 1.0), (0.5, 0.8), (0.2, 0.4)],
        )
        state = WorkbookParser(path).parse()
        resource = state.team[0]
        ri = ResourceIntelligence(state)

        # SPR-3 (our stand-in for a distinct later sprint, e.g. "Sprint 6"
        # in the real workbook) must use its OWN 0.2/0.4, not the ~0.57/0.73
        # project average.
        assert ri.allocation_pct(resource, "SPR-3") == pytest.approx(0.2)
        assert ri.availability_pct(resource, "SPR-3") == pytest.approx(0.4)
        assert ri.allocation_pct(resource, "SPR-3") != pytest.approx(resource.allocation_pct)

        # Different sprints must produce different effective capacity for
        # the SAME resource (same daily_capacity_hrs, same sprint_days ~ 14d
        # in this fixture) -- proving sprint-awareness end to end, not just
        # at the raw dict-lookup level.
        cap_sprint_1 = ri.effective_capacity_hours(resource, "SPR-1")
        cap_sprint_3 = ri.effective_capacity_hours(resource, "SPR-3")
        assert cap_sprint_1 != cap_sprint_3
        assert cap_sprint_1 > cap_sprint_3  # SPR-1 is 100%/100%, SPR-3 is 20%/40%


def test_explicit_zero_sprint_availability_survives_and_is_not_fallback():
    """An explicit 0% availability for one specific sprint must be honored
    as 0.0 for that sprint (not silently replaced by the aggregate fallback,
    and not confused with 'missing')."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "wb.xlsx")
        _write_minimal_workbook(
            path, skill3_value="Tertiary Skill X", alloc_pct=1, avail_pct=1,
            sprint_pcts=[(1.0, 1.0), (1.0, 0.0)],
        )
        state = WorkbookParser(path).parse()
        resource = state.team[0]
        ri = ResourceIntelligence(state)

        assert resource.sprint_availability_pct["SPR-2"] == 0.0
        assert ri.availability_pct(resource, "SPR-2") == 0.0
        assert ri.effective_capacity_hours(resource, "SPR-2") == 0.0


def test_missing_sprint_specific_value_falls_back_to_aggregate():
    """A sprint with NO S{n} Alloc/Avail column data (e.g. a sprint beyond
    what the workbook tracked per-sprint) must fall back to the aggregate
    scalar -- this is the documented "missing vs zero" distinction."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "wb.xlsx")
        _write_minimal_workbook(
            path, skill3_value="Tertiary Skill X", alloc_pct=1, avail_pct=1,
            sprint_pcts=[(0.6, 0.9)],
        )
        state = WorkbookParser(path).parse()
        resource = state.team[0]
        ri = ResourceIntelligence(state)

        # "SPR-99" has no entry in sprint_allocation_pct/sprint_availability_pct
        # and no matching Sprint object -- must fall back to the aggregate.
        assert "SPR-99" not in resource.sprint_allocation_pct
        assert ri.allocation_pct(resource, "SPR-99") == pytest.approx(resource.allocation_pct)
        assert ri.availability_pct(resource, "SPR-99") == pytest.approx(resource.availability_pct)