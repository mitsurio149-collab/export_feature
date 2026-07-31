"""
Session Store

In-memory storage for project sessions.
For hackathon: one project per session.
For production: replace with Redis + session tokens.
"""

import copy
from typing import Dict, Optional
from datetime import datetime, timezone
from threading import Lock

from app.domain.models import ProjectState
from app.domain.emios_models import ActualSprintOutcome


class SessionNotFound(Exception):
    """Raised when a requested session does not exist."""

    def __init__(self, session_id: str):
        super().__init__(f"Session {session_id} not found")
        self.session_id = session_id


def _snapshot_from_analysis(analysis) -> dict:
    """Lightweight metrics snapshot for reforecast comparison tracking."""
    try:
        mc = analysis.monte_carlo
        forecast = analysis.forecast
        risk = analysis.risk_result
        metrics = getattr(analysis, "metrics", None)
        completed_sprints  = getattr(metrics, "completed_sprints", None)   if metrics else None
        current_sprint_num = getattr(metrics, "current_sprint_number", None) if metrics else None
        return {
            "on_time_probability": round(mc.on_time_probability * 100, 1),
            "on_time_risk_level": (
                mc.on_time_risk_level.value
                if hasattr(mc.on_time_risk_level, "value")
                else str(mc.on_time_risk_level)
            ),
            "expected_delay_days": round(forecast.expected_delay_days, 1),
            "overall_risk_score": round(risk.overall_risk_score, 1),
            "p50_date": mc.most_likely_finish_date.isoformat() if mc.most_likely_finish_date else None,
            "p80_date": mc.p80_finish_date.isoformat() if mc.p80_finish_date else None,
            "p95_date": mc.p95_finish_date.isoformat() if mc.p95_finish_date else None,
            "target_end_date": mc.target_end_date.isoformat() if mc.target_end_date else None,
            "completed_sprints":  completed_sprints,
            "current_sprint_num": current_sprint_num,
        }
    except Exception:
        return {}


def _clone_project_state(project_state: ProjectState):
    """Return an isolated copy of a project state for storage or simulation."""
    clone_method = getattr(project_state, "model_copy", None)
    if callable(clone_method):
        return clone_method(deep=True)
    return copy.deepcopy(project_state)


class Session:
    """Single project session."""
    
    def __init__(self, session_id: str, project_state: ProjectState):
        self.session_id = session_id
        self.project_state = _clone_project_state(project_state)
        self.created_at = datetime.now(timezone.utc)
        self.last_accessed = datetime.now(timezone.utc)
        self.descoped_item_ids = set()  # For scope change tracking
        # Lazily populated by SessionStore.get_analysis() — holds the single
        # computed truth (ProjectAnalysis) so every route reads the same numbers.
        self._analysis = None
        # Reforecast comparison snapshots.
        # baseline_snapshot: metrics at session creation — never overwritten.
        # pre_apply_snapshot: metrics immediately before the most recent
        #   recovery plan apply — lets reforecast-comparison show the marginal
        #   gain of each plan step rather than only the cumulative gain.
        # applied_plan_id: ID of the most recently applied recovery plan.
        self.baseline_snapshot = None
        self.pre_apply_snapshot = None
        self.applied_plan_id = None
        # last_simulation_result: stored by POST /recommendations/simulate
        self.last_simulation_result = None
        # pipeline_result: full PipelineResult from run_emios_pipeline(),
        # stored by _prewarm_session / POST /api/demo/load.
        # All routes (recovery_plans, recommendations) read from here first
        # instead of rebuilding engines from scratch on every request.
        self.pipeline_result = None
        # actual_outcomes: sprint_id -> ActualSprintOutcome, populated by
        # POST /api/learning/outcome once a sprint closes. Stage 17a
        # (LearningEngine) reads the most recent entry here instead of the
        # previous hardcoded actual_outcome=None.
        self.actual_outcomes: Dict[str, ActualSprintOutcome] = {}
        # forecast_history: time-series of snapshots appended on each fresh
        # analysis build (triggered by upload, scope change, or recovery plan
        # apply).  Capped at 12 entries — oldest dropped when full.
        # Each entry: {recorded_at, label, p50_date, p80_date, p95_date,
        #              on_time_probability, expected_delay_days}
        self.forecast_history: list = []

    def touch(self) -> None:
        """Update last accessed timestamp."""
        self.last_accessed = datetime.now(timezone.utc)

    def invalidate_analysis(self) -> None:
        """
        Drop the cached ProjectAnalysis so it is recomputed on the next
        get_analysis() call.  Must be called whenever project_state is mutated
        (e.g. scope change, descope).
        Also drops the pipeline_result so EMIOS is re-run with the new state.
        """
        self._analysis = None
        self.pipeline_result = None


class SessionStore:
    """Thread-safe in-memory session storage."""
    
    _instance = None
    _lock = Lock()
    
    def __new__(cls):
        """Singleton pattern."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        """Initialize store."""
        if self._initialized:
            return
        self._sessions: Dict[str, Session] = {}
        self._lock = Lock()
        self._initialized = True
    
    def create_session(self, project_state: ProjectState) -> str:
        """
        Create a new session for a project.
        
        Args:
            project_state: ProjectState to store
            
        Returns:
            session_id: Unique session identifier
        """
        session_id = project_state.project_id
        session = Session(session_id, project_state)
        
        with self._lock:
            self._sessions[session_id] = session

        # Capture the baseline snapshot immediately so reforecast-comparison
        # always has a pre-any-action reference even before analysis is built.
        # We store it lazily on the first get_analysis() call below.

        return session_id
    
    def get_session(self, session_id: str) -> Optional[Session]:
        """
        Retrieve session by ID.
        
        Args:
            session_id: Session identifier
            
        Returns:
            Session object or None if not found
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if session:
                session.touch()
            return session
    
    def get_project_state(self, session_id: str) -> Optional[ProjectState]:
        """
        Retrieve project state from session.
        
        Args:
            session_id: Session identifier
            
        Returns:
            ProjectState or None if not found
        """
        session = self.get_session(session_id)
        return session.project_state if session else None

    def get_analysis(self, session_id: str, simulation_count: int = 1000):
        """
        Return the cached ProjectAnalysis for this session, building it on
        the first call.

        This is the single point of truth for all engine outputs.  Every API
        route should call this instead of constructing engines independently.

        Args:
            session_id:        Session identifier.
            simulation_count:  Monte Carlo iterations (default 1000).

        Returns:
            ProjectAnalysis or None if the session does not exist.
        """
        session = self.get_session(session_id)
        if session is None:
            return None

        if session._analysis is None:
            # Import here to avoid a module-level circular dependency.
            from app.engines.project_analysis import ProjectAnalysis
            session._analysis = ProjectAnalysis.build(
                session.project_state,
                simulation_count=simulation_count,
            )
            # Capture the baseline snapshot on the very first analysis build.
            # This is never overwritten — it always represents the pre-any-action state.
            if session.baseline_snapshot is None:
                session.baseline_snapshot = _snapshot_from_analysis(session._analysis)

            # Append a trend entry every time a fresh analysis is built so the
            # UI can show how forecast dates have moved over time.
            snap = _snapshot_from_analysis(session._analysis)
            _sprint_num = snap.get("current_sprint_num")
            _label = (
                f"Sprint {_sprint_num}" if _sprint_num is not None
                else f"Run {len(session.forecast_history) + 1}"
            )
            entry = {
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "label": _label,
                **snap,
            }
            session.forecast_history.append(entry)
            if len(session.forecast_history) > 12:
                session.forecast_history.pop(0)

        return session._analysis

    def capture_pre_apply_snapshot(self, session_id: str, plan_id: str) -> None:
        """
        Snapshot the current metrics immediately before a recovery plan is applied.
        Called by the apply route so reforecast-comparison can show per-step deltas.
        """
        analysis = self.get_analysis(session_id)
        session = self.get_session(session_id)
        if session is not None and analysis is not None:
            session.pre_apply_snapshot = _snapshot_from_analysis(analysis)
            session.applied_plan_id = plan_id

    def set_pipeline_result(self, session_id: str, pipeline_result) -> None:
        """Store the full PipelineResult from run_emios_pipeline() on the session."""
        session = self.get_session(session_id)
        if session is not None:
            session.pipeline_result = pipeline_result

    def get_or_build_pipeline_result(self, session_id: str):
        """
        Return cached pipeline result for session_id.
        If not yet built (for example after a normal workbook upload), build it
        now and cache it.
        """
        session = self.get_session(session_id)
        if session is None:
            raise SessionNotFound(session_id)

        if session.pipeline_result is not None:
            return session.pipeline_result

        project_state = session.project_state
        if project_state is None:
            raise SessionNotFound(session_id)

        from app.pipeline.emios_pipeline import DEFAULT_SIMULATION_COUNT, run_emios_pipeline

        pipeline_result = run_emios_pipeline(
            project_state,
            simulation_count=DEFAULT_SIMULATION_COUNT,
            seed=42,
        )
        self.set_pipeline_result(session_id, pipeline_result)
        return pipeline_result

    def get_pipeline_result(self, session_id: str):
        """Return the stored PipelineResult, or None if not yet run."""
        session = self.get_session(session_id)
        return session.pipeline_result if session is not None else None

    def invalidate_analysis(self, session_id: str) -> None:
        """
        Drop the cached ProjectAnalysis for a session so it is rebuilt on
        the next get_analysis() call.

        Call this whenever project_state is mutated (scope change, descope,
        blocker resolution, etc.) so routes don't serve stale numbers.
        Also invalidates the stored pipeline_result so EMIOS is re-run.

        Args:
            session_id: Session identifier.
        """
        session = self.get_session(session_id)
        if session is not None:
            session.invalidate_analysis()
    
    def get_forecast_history(self, session_id: str) -> list:
        """Return the time-series of forecast snapshots for this session."""
        session = self.get_session(session_id)
        return session.forecast_history if session is not None else []

    def record_actual_outcome(self, session_id: str, outcome: ActualSprintOutcome) -> bool:
        """
        Store a real sprint outcome once it's known (sprint closed).
        Called by POST /api/learning/outcome. Overwrites any prior outcome
        recorded for the same sprint_id (PMs may correct/update a report).

        Returns True if stored, False if the session doesn't exist.
        """
        session = self.get_session(session_id)
        if session is None:
            return False
        session.actual_outcomes[outcome.sprint_id] = outcome
        return True

    def get_actual_outcome(self, session_id: str, sprint_id: str) -> Optional[ActualSprintOutcome]:
        """Retrieve a specific sprint's recorded outcome, if any."""
        session = self.get_session(session_id)
        if session is None:
            return None
        return session.actual_outcomes.get(sprint_id)

    def get_latest_actual_outcome(self, session_id: str) -> Optional[ActualSprintOutcome]:
        """
        Retrieve the most recently recorded outcome for this session
        (insertion order = report order, since dicts preserve insertion
        order). Used by the pipeline to feed Stage 17a (LearningEngine)
        the freshest ground truth available for this session.
        """
        session = self.get_session(session_id)
        if session is None or not session.actual_outcomes:
            return None
        return next(reversed(session.actual_outcomes.values()))

    def delete_session(self, session_id: str) -> bool:
        """
        Delete a session.
        
        Args:
            session_id: Session identifier
            
        Returns:
            True if deleted, False if not found
        """
        with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                return True
            return False
    
    def list_sessions(self) -> list:
        """
        List all active sessions.
        
        Returns:
            List of (session_id, project_name) tuples
        """
        with self._lock:
            return [
                (sid, s.project_state.project_info.project_name)
                for sid, s in self._sessions.items()
            ]
    
    def clear_all(self) -> None:
        """Clear all sessions (for testing)."""
        with self._lock:
            self._sessions.clear()


# Global singleton instance
store = SessionStore()


def get_or_build_pipeline_result(session_id: str):
    """Convenience wrapper around the shared session-store accessor."""
    return store.get_or_build_pipeline_result(session_id)
