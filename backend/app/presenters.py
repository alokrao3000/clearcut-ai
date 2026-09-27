from app.enums import Stage
from app.models import Asset, ClearanceTask, Rightsholder
from app.schemas import AssetOut, BoardCard, ContactOut, RightsholderBrief, RightsholderOut, TaskOut
from app.services.mapping import effective_contact
from app.services.workflow import allowed_targets


def task_out(task: ClearanceTask) -> TaskOut:
    out = TaskOut.model_validate(task)
    if task.rightsholder is not None:
        out.contact = ContactOut(**effective_contact(task.rightsholder))
    out.allowed_transitions = sorted(allowed_targets(Stage(task.stage)), key=lambda s: list(Stage).index(s))
    return out


def asset_out(asset: Asset) -> AssetOut:
    out = AssetOut.model_validate(asset, from_attributes=True)
    out.tasks = [task_out(t) for t in asset.tasks]
    return out


def board_card(task: ClearanceTask) -> BoardCard:
    a = task.asset
    return BoardCard(task=task_out(task), asset_id=a.id, asset_title=a.title,
                     asset_thumbnail_url=a.thumbnail_url, platform=a.platform)


def rightsholder_out(rh: Rightsholder, org_id: str | None = None) -> RightsholderOut:
    """`children` comes from a relationship, which no query filter touches.

    Scoping the top-level row is not enough: a tenant can parent a private entry onto a
    shared one, and it would then appear in every other tenant's view of that parent. The
    child list is filtered here, where the relationship is actually read.
    """
    children = [c for c in rh.children if c.org_id is None or c.org_id == org_id]
    return RightsholderOut(
        id=rh.id, name=rh.name, kind=rh.kind, is_placeholder=rh.is_placeholder, parent_id=rh.parent_id,
        licensing_email=rh.licensing_email, address=rh.address, website=rh.website,
        preferred_templates=rh.preferred_templates or [], aliases=[a.alias for a in rh.aliases],
        contact=ContactOut(**effective_contact(rh)),
        children=[RightsholderBrief.model_validate(c) for c in children],
    )
