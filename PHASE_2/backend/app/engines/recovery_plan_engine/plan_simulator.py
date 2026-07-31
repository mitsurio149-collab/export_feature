"""
Recovery Plan Simulator

Thin wrapper around SimulationEngine.simulate_scenario() for evaluating entire plans.

No new simulation logic is required — SimulationEngine already:
- Clones the project state
- Applies multiple recommendations in sequence
- Recalculates the engine pipeline
- Returns a complete ScenarioResult

This layer just adapts the interface to work with RecoveryPlanCandidate objects.
"""

from app.engines.recovery_plan_engine.models import RecoveryPlanCandidate
from app.engines.simulation_engine import ScenarioResult, SimulationEngine


class RecoveryPlanSimulator:
    """
    Simulates a complete recovery plan by applying all its actions together
    and capturing the resulting scenario outcome.
    """

    def __init__(self, simulation_engine: SimulationEngine):
        """
        Args:
            simulation_engine: The existing SimulationEngine configured with project state and upstream outputs.
        """
        self.simulation_engine = simulation_engine

    def simulate_plan(self, plan: RecoveryPlanCandidate) -> ScenarioResult:
        """
        Simulate a recovery plan.

        The simulator always starts from an isolated project-state copy so a
        preview cannot mutate the baseline state stored on the engine.
        """
        original_state = self.simulation_engine.project_state
        cloned_state = self.simulation_engine._clone_project_state()
        self.simulation_engine.project_state = cloned_state
        try:
            return self.simulation_engine.simulate_scenario(plan.actions)
        finally:
            self.simulation_engine.project_state = original_state
