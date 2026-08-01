# Export Feature Instructions

This document explains how to use and verify the plan-projected Excel export feature added to Sprint Whisperer.

## What the export feature does

The Export tab lets a user download a copy of the original uploaded Excel workbook with `Work_Items` values projected for a selected recovery strategy:

- **Safe**
- **Aggressive**
- **Minimal Disruption**

The export is a projection only. Downloading a workbook does **not** apply the selected recovery plan to the live session.

## User workflow

1. Upload a valid sprint workbook or load the demo project.
2. Open the dashboard.
3. Generate or review recovery plans in the **Recovery Plans** tab if needed.
4. Open the **Export** tab.
5. Select the plan to export from the dropdown.
6. Click **Download Excel**.
7. The browser downloads a workbook named like:

   ```text
   sprint_plan_<session_id>_<plan_archetype>.xlsx
   ```

## Frontend behavior

The Export tab is registered in `PHASE_2/Frontend/src/pages/Dashboard.jsx` and renders `ExportPage` from `PHASE_2/Frontend/src/pages/Export.jsx`.

`ExportPage` performs these steps:

1. Reads the active `session_id` from `session.project_summary.session_id`.
2. Calls `GET /api/recovery-plans?session_id=<session_id>` through the shared API client.
3. Displays all available plan archetypes in a dropdown.
4. Calls `api.export(sessionId, selectedPlanId)` when the user clicks **Download Excel**.
5. Downloads the returned blob as an `.xlsx` file.

## Backend API

### Endpoint

```http
GET /api/export?session_id=<session_id>&plan_id=<plan_id>
```

### Query parameters

| Parameter | Required | Description |
| --- | --- | --- |
| `session_id` | Yes | The active session ID for the uploaded or demo workbook. |
| `plan_id` | No | The recovery plan ID to project into the exported workbook. |
| `archetype` | No | Alternative selector for the plan archetype: `SAFE`, `AGGRESSIVE`, or `MINIMAL_DISRUPTION`. |

Use either `plan_id` or `archetype` for a plan-projected export. If neither is provided, the endpoint exports the current session state.

### Backend processing flow

When `plan_id` or `archetype` is provided, the export route:

1. Loads the session from the in-memory session store.
2. Reads the original workbook bytes from the session.
3. Retrieves recovery plans from the stored or rebuilt pipeline result.
4. Selects the requested plan.
5. Creates a deep clone of the current `ProjectState`.
6. Applies the selected plan's actions to the cloned state with `ActionApplicator().apply_many(...)`.
7. Opens the original workbook with `openpyxl`.
8. Updates the `Work_Items` sheet from the projected cloned state.
9. Adds or replaces a `Recommended_Actions` sheet with the selected plan's actions.
10. Streams the updated workbook back to the browser.

Because the plan is applied only to a cloned state, export does not mutate the session's live project state.

## Workbook output

The exported workbook preserves the original workbook structure and updates the `Work_Items` sheet values from the projected plan state.

The updated `Work_Items` columns include:

- `Curr Est (h)`
- `Remaining Hrs`
- `Scope Reason`
- `Status`

The export also adds or replaces the `Recommended_Actions` sheet with columns for the selected plan's actions:

- `Recommendation ID`
- `Type`
- `Action`
- `Target Items`
- `Category`
- `Reason`
- `Escalation Path`
- `Workaround`
- `Delay Reduction (days)`
- `Probability Gain (%)`
- `Effort`
- `Confidence`
- `Status`
- `Plan`

## Manual verification checklist

Use this checklist after launching the backend and frontend locally:

1. Upload the workbook or load the demo project.
2. Confirm the dashboard opens successfully.
3. Open the **Export** tab.
4. Confirm the plan dropdown is populated with recovery plans.
5. Select **Safe** and download the workbook.
6. Select **Aggressive** and download the workbook.
7. Select **Minimal Disruption** and download the workbook.
8. Open each workbook in Excel or LibreOffice.
9. Confirm `Work_Items` exists and contains projected values.
10. Confirm `Recommended_Actions` exists and lists the selected plan's actions.
11. Confirm exporting does not apply the plan to the live dashboard state.

## Useful commands

### Backend syntax check

```bash
python -m py_compile PHASE_2/backend/app/api/routes/export.py
```

### Backend tests

```bash
cd PHASE_2/backend && python -m pytest tests/test_phase4_recovery_plans.py -q
```

### Frontend build

```bash
cd PHASE_2/Frontend && npm run build
```

### Frontend development server

```bash
cd PHASE_2/Frontend && npm run dev -- --host 0.0.0.0
```

## Troubleshooting

### `Session not found`

Confirm the `session_id` passed to `/api/export` matches the currently uploaded or demo-loaded session.

### `No recovery plans are available to export`

Generate recovery plans first or confirm the session pipeline result can be built successfully.

### `Recovery plan <id> not found`

Confirm the frontend is passing a valid `plan_id` returned from `/api/recovery-plans`.

### Workbook missing expected columns

The export route expects the `Work_Items` sheet to include these headers on row 2:

- `Task ID`
- `Curr Est (h)`
- `Remaining Hrs`
- `Scope Reason`
- `Status`

If any are missing or renamed, the backend returns a processing error.
