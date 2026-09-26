from enum import StrEnum


class DistributionScope(StrEnum):
    festival = "festival"
    worldwide_streaming = "worldwide_streaming"
    all_media_perpetual = "all_media_perpetual"


class ProductionTier(StrEnum):
    ultra_low = "ultra_low"
    sag_moderate_low = "sag_moderate_low"
    studio_feature = "studio_feature"


class Platform(StrEnum):
    youtube = "youtube"
    vimeo = "vimeo"
    getty = "getty"
    shutterstock = "shutterstock"
    pond5 = "pond5"
    internet_archive = "internet_archive"
    nara = "nara"
    other = "other"


class SourceType(StrEnum):
    url_ingest = "url_ingest"
    script_ingest = "script_ingest"
    manual = "manual"


class IngestStatus(StrEnum):
    complete = "complete"
    partial = "partial"  # metadata fetch blocked or failed; URL-derived fields only
    failed = "failed"


class Layer(StrEnum):
    """A distinct right that must be cleared. Composite assets get one task per layer."""

    footage = "footage"
    still_image = "still_image"
    master_recording = "master_recording"
    composition = "composition"
    performance = "performance"  # on-screen talent / likeness
    trademark = "trademark"


class RightsholderKind(StrEnum):
    studio = "studio"
    broadcaster = "broadcaster"
    label = "label"
    publisher = "publisher"
    stock_agency = "stock_agency"
    archive = "archive"
    individual = "individual"
    brand = "brand"


class Stage(StrEnum):
    sourced = "sourced"
    rights_mapped = "rights_mapped"
    budget_approved = "budget_approved"
    outreach_sent = "outreach_sent"
    quote_received = "quote_received"
    deal_memo_signed = "deal_memo_signed"
    denied = "denied"
    dropped = "dropped"


class ReplyKind(StrEnum):
    """What a rightsholder's reply amounts to, as read by the parser."""

    approved = "approved"
    denied = "denied"
    quote = "quote"
    needs_info = "needs_info"
    unclear = "unclear"


class RateUnit(StrEnum):
    per_minute = "per_minute"
    per_use = "per_use"
    per_image = "per_image"


class ActorType(StrEnum):
    user = "user"
    system = "system"
    scraper = "scraper"
    llm = "llm"


# Which rightsholder kinds can plausibly own each layer. Used to filter mapping candidates.
LAYER_KINDS: dict[Layer, set[RightsholderKind]] = {
    Layer.footage: {RightsholderKind.studio, RightsholderKind.broadcaster, RightsholderKind.stock_agency,
                    RightsholderKind.archive, RightsholderKind.individual},
    Layer.still_image: {RightsholderKind.stock_agency, RightsholderKind.archive, RightsholderKind.studio,
                        RightsholderKind.individual},
    Layer.master_recording: {RightsholderKind.label, RightsholderKind.individual},
    Layer.composition: {RightsholderKind.publisher, RightsholderKind.individual},
    Layer.performance: {RightsholderKind.individual},
    Layer.trademark: {RightsholderKind.brand, RightsholderKind.studio},
}


# Where each reading would take a task, if a human confirms it. `needs_info` and `unclear`
# map to nothing on purpose: they are correspondence, not progress. `approved` targets
# quote_received like `quote` does, because the workflow will not advance a task past
# outreach without a figure — an approval with no fee named comes back blocked, saying so.
REPLY_TARGET_STAGE: dict[ReplyKind, Stage | None] = {
    ReplyKind.approved: Stage.quote_received,
    ReplyKind.quote: Stage.quote_received,
    ReplyKind.denied: Stage.denied,
    ReplyKind.needs_info: None,
    ReplyKind.unclear: None,
}
