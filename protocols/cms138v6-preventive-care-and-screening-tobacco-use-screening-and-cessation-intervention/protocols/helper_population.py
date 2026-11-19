"""Population helper for multi-population CQM protocols.

Mirrors ``canvas_workflow_kit.builtin_cqms.helper_population.Population`` so the
ported CMS138v6 protocol can track per-population initial/denominator/numerator
state without depending on the legacy workflow kit.
"""


class Population:
    """Tracks the initial/denominator/numerator state for a single population."""

    def __init__(self) -> None:
        self.in_initial_population: bool | None = None
        self.in_denominator: bool | None = None
        self.in_numerator: bool | None = None

    def set_initial_population(self, flag: bool) -> None:
        """Set initial population flag, cascading to denominator and numerator."""
        self.in_initial_population = flag
        self.in_denominator = flag
        self.in_numerator = flag

    def set_denominator(self, flag: bool) -> None:
        """Set denominator flag, cascading to numerator."""
        self.in_denominator = flag
        self.in_numerator = flag

    def set_numerator(self, flag: bool) -> None:
        """Set numerator flag."""
        self.in_numerator = flag
