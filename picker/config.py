from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_WEBHOOK_URL = "http://n8n:5678/webhook/f5986e63-7897-4e92-a794-86009334f273"
LOG_DIR = Path(__file__).resolve().parent.parent / "logs"


@dataclass
class EmailConfig:
    pick: str = ""
    listing: str = ""
    invoice: str = ""


@dataclass
class PickerConfig:
    desired_avg_cost_per_item: float = 44.0
    num_items: int = 100

    include_tags: list[str] | None = field(default_factory=list)
    exclude_tags: list[str] | None = field(default_factory=list)
    include_types: list[str] | None = field(default_factory=list)
    exclude_types: list[str] | None = field(default_factory=list)

    minimum_cost: float | None = 0.0
    maximum_cost: float | None = 0.0

    count_variance: float = 0.0
    avg_tolerance: float = 0.10
    cost_variance: float = 1.5
    attempts: int = 1
    swap_tries: int = 800
    seed: int | None = None

    allow_duplicates: bool = False

    emails: EmailConfig | None = field(default_factory=EmailConfig)

    @property
    def cost_window(self) -> float:
        # allowed range of costs to be selected from
        return self.desired_avg_cost_per_item * self.cost_variance

    @property
    def resolved_minimum_cost(self) -> float:
        min_cost = (
            self.desired_avg_cost_per_item - self.cost_window
            if self.minimum_cost is None
            else float(self.minimum_cost)
        )
        return 0.01 if min_cost == 0 else min_cost

    @property
    def resolved_maximum_cost(self) -> float:
        return (
            self.desired_avg_cost_per_item + self.cost_window
            if not self.maximum_cost
            else float(self.maximum_cost)
        )

