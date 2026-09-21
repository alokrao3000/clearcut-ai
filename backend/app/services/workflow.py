"""Kanban lifecycle rules for a clearance task.

Sourced -> Rights Mapped -> Budget Approved -> Outreach Sent -> Quote Received -> Deal Memo Signed
Tasks move forward one step at a time, may step back one stage to correct a mistake,
can be dropped from any open stage, and can be denied once a rightsholder has been contacted.
"""

from app.enums import Stage
from app.models import ClearanceTask

PIPELINE = [Stage.sourced, Stage.rights_mapped, Stage.budget_approved, Stage.outreach_sent,
            Stage.quote_received, Stage.deal_memo_signed]
TERMINAL = {Stage.deal_memo_signed, Stage.denied, Stage.dropped}


class WorkflowError(ValueError):
    pass


def allowed_targets(current: Stage) -> set[Stage]:
    if current in (Stage.denied, Stage.dropped):
        return {Stage.sourced}  # reopen
    if current is Stage.deal_memo_signed:
        return set()
    i = PIPELINE.index(current)
    targets = {PIPELINE[i + 1], Stage.dropped}
    if i > 0:
        targets.add(PIPELINE[i - 1])
    if current in (Stage.outreach_sent, Stage.quote_received):
        targets.add(Stage.denied)
    return targets


def _guard(task: ClearanceTask, to: Stage) -> None:
    if to is Stage.rights_mapped and not task.rightsholder_id:
        raise WorkflowError("Assign a rightsholder before marking rights as mapped.")
    if to is Stage.budget_approved and task.estimate_high is None:
        raise WorkflowError("Run a budget estimate before approving the budget.")
    if to is Stage.quote_received and task.quoted_amount is None:
        raise WorkflowError("Record the quoted amount before marking a quote as received.")
    if to is Stage.deal_memo_signed and task.agreed_amount is None:
        raise WorkflowError("Record the agreed fee before marking the deal memo signed.")


def transition(task: ClearanceTask, to: Stage) -> None:
    current = Stage(task.stage)
    if to == current:
        return
    if to not in allowed_targets(current):
        allowed = ", ".join(sorted(s.value for s in allowed_targets(current))) or "none"
        raise WorkflowError(f"Cannot move from '{current}' to '{to}'. Allowed: {allowed}.")
    moving_forward = to in PIPELINE and current in PIPELINE and PIPELINE.index(to) > PIPELINE.index(current)
    if moving_forward:
        _guard(task, to)
    task.stage = to


# Rightsholder may change only before outreach. Changing it after budget approval invalidates the budget.
REASSIGNABLE = {Stage.sourced, Stage.rights_mapped, Stage.budget_approved}
