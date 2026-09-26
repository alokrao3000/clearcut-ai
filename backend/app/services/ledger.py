"""Project cost ledger: estimated vs quoted vs signed.

The budget endpoint already totals a project. The ledger answers a different question —
*how far has the estimate survived contact with the rightsholders?* — so it reports the three
figures side by side per task, with the variance between what the matrix guessed and what was
actually asked for.

Two deliberate choices:

* **Variance is measured against the top of the estimate range**, not the midpoint. The range
  is advisory and wide; a producer needs to know whether a quote broke the number they were
  planning against, and that number is the high end plus contingency.
* **Closed tasks are reported, not silently dropped.** A denied item with a quote on it is
  part of how a project got where it is, and an E&O reviewer will ask about it.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.enums import Stage
from app.models import ClearanceTask
from app.services.budget import RECOMMENDED_CONTINGENCY, _round

# Where the money for a task currently stands. `exposure` is the figure a producer should be
# holding against the task right now — the firmest number available for it.
COMMITTED_STAGES = {Stage.deal_memo_signed}
CLOSED_STAGES = {Stage.denied, Stage.dropped}


@dataclass
class Line:
    task: ClearanceTask
    estimate_low: Decimal | None
    estimate_high: Decimal | None
    quoted: Decimal | None
    agreed: Decimal | None
    exposure: Decimal
    basis: str  # agreed | quoted | estimate | none
    variance: Decimal | None  # quoted or agreed, minus the top of the estimate
    closed: bool


def _zero(value: Decimal | None) -> Decimal:
    return value if value is not None else Decimal(0)


def line_for(task: ClearanceTask) -> Line:
    stage = Stage(task.stage)
    closed = stage in CLOSED_STAGES
    estimate_high = task.estimate_high
    firm = task.agreed_amount if task.agreed_amount is not None else task.quoted_amount

    if closed:
        # A dropped or denied task costs nothing going forward, whatever was quoted for it.
        exposure, basis = Decimal(0), "none"
    elif task.agreed_amount is not None:
        exposure, basis = task.agreed_amount, "agreed"
    elif task.quoted_amount is not None:
        exposure, basis = task.quoted_amount, "quoted"
    elif estimate_high is not None:
        exposure, basis = estimate_high, "estimate"
    else:
        exposure, basis = Decimal(0), "none"

    variance = None
    if firm is not None and estimate_high is not None:
        variance = firm - estimate_high

    return Line(task=task, estimate_low=task.estimate_low, estimate_high=estimate_high,
                quoted=task.quoted_amount, agreed=task.agreed_amount, exposure=exposure,
                basis=basis, variance=variance, closed=closed)


def build(tasks: list[ClearanceTask]) -> dict:
    lines = [line_for(task) for task in tasks]
    live = [line for line in lines if not line.closed]

    estimate_low = sum((_zero(l.estimate_low) for l in live), Decimal(0))
    estimate_high = sum((_zero(l.estimate_high) for l in live), Decimal(0))
    quoted = sum((_zero(l.quoted) for l in live), Decimal(0))
    agreed = sum((_zero(l.agreed) for l in live), Decimal(0))
    exposure = sum((l.exposure for l in live), Decimal(0))

    priced = [l for l in live if l.variance is not None]
    over = [l for l in priced if l.variance > 0]

    return {
        "lines": lines,
        "totals": {
            "live_tasks": len(live),
            "closed_tasks": len(lines) - len(live),
            "estimate_low": estimate_low,
            "estimate_high": estimate_high,
            "quoted_total": quoted,
            "agreed_total": agreed,
            # What to hold today: the firmest number per task, plus contingency on the part
            # that is still only an estimate.
            "exposure": exposure,
            "recommended_contingency": _round(
                sum((_zero(l.estimate_high) for l in live if l.basis == "estimate"), Decimal(0))
                * RECOMMENDED_CONTINGENCY),
            "committed": sum((l.exposure for l in live
                              if Stage(l.task.stage) in COMMITTED_STAGES), Decimal(0)),
            "awaiting_reply": sum(1 for l in live if Stage(l.task.stage) is Stage.outreach_sent),
            "priced_tasks": len(priced),
            "over_estimate_tasks": len(over),
            "variance_total": sum((l.variance for l in priced), Decimal(0)),
            "worst_variance": max((l.variance for l in priced), default=Decimal(0)),
        },
    }
