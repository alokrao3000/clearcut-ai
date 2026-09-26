"""Placeholder directory and rate cards for development.

Entity names are real companies so matching can be exercised on real URLs, but every contact
and every rate is UNVERIFIED PLACEHOLDER DATA. Emails use the reserved `.example` TLD so
nothing can be sent to a real licensing desk by accident.
"""

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import acting_as
from app.enums import ActorType, Layer, RateUnit
from app.enums import RightsholderKind as K
from app.models import RateCard, Rightsholder, RightsholderAlias

# Standing of each entity, used by contact reliability scoring. Majors run staffed
# licensing desks; independents may never answer.
TIERS = {
    "ent_warner_bros_discovery": "major", "ent_warner_bros_pictures": "major",
    "ent_warner_bros_animation": "major", "ent_nbcuniversal": "major",
    "ent_universal_pictures": "major", "ent_nbc_news_archives": "notable",
    "ent_sony_music_entertainment": "major", "ent_rca_records": "major",
    "ent_sony_music_publishing": "major", "ent_universal_music_group": "major",
    "ent_universal_music_publishing": "major", "ent_warner_music_group": "major",
    "ent_warner_chappell": "major", "ent_getty_images": "major",
    "ent_shutterstock": "notable", "ent_pond5": "notable", "ent_nara": "notable",
    "ent_british_pathe": "notable", "ent_ap_archive": "notable",
}

# id, name, kind, parent, email, aliases (str, or (alias, [layers]))
ENTITIES = [
    ("ent_warner_bros_discovery", "Warner Bros. Discovery", K.studio, None, "clip-licensing@wbd.example",
     ["WBD", "Warner Bros Discovery"]),
    ("ent_warner_bros_pictures", "Warner Bros. Pictures", K.studio, "ent_warner_bros_discovery", None,
     ["Warner Bros.", "Warner Bros", "Warner Brothers", "Warner Bros. Classics", "WB Pictures"]),
    ("ent_warner_bros_animation", "Warner Bros. Animation", K.studio, "ent_warner_bros_discovery",
     "animation-clips@wbd.example", ["Looney Tunes", "Merrie Melodies", "WB Animation"]),
    ("ent_nbcuniversal", "NBCUniversal", K.studio, None, "clip-licensing@nbcuni.example",
     ["NBC Universal", "NBC"]),
    ("ent_universal_pictures", "Universal Pictures", K.studio, "ent_nbcuniversal", None,
     ["Universal Studios", "Universal Pictures"]),
    ("ent_nbc_news_archives", "NBC News Archives", K.broadcaster, "ent_nbcuniversal",
     "archives@nbcnews.example", ["NBC News"]),
    ("ent_sony_music_entertainment", "Sony Music Entertainment", K.label, None, "sync@sonymusic.example",
     ["Sony Music", "Columbia Records", "Epic Records"]),
    ("ent_rca_records", "RCA Records", K.label, "ent_sony_music_entertainment", None,
     ["RCA", ("Rick Astley", [Layer.master_recording])]),
    ("ent_sony_music_publishing", "Sony Music Publishing", K.publisher, None, "sync-requests@sonypub.example",
     ["Sony/ATV", "Sony ATV Music Publishing"]),
    ("ent_universal_music_group", "Universal Music Group", K.label, None, "film-tv@umusic.example",
     ["UMG", "Universal Music", "Interscope", "Republic Records", "Island Records"]),
    ("ent_universal_music_publishing", "Universal Music Publishing Group", K.publisher, None,
     "sync@umpg.example", ["UMPG", "Universal Music Publishing"]),
    ("ent_warner_music_group", "Warner Music Group", K.label, None, "sync@wmg.example",
     ["Warner Records", "Atlantic Records", "Warner Music"]),
    ("ent_warner_chappell", "Warner Chappell Music", K.publisher, None, "sync@warnerchappell.example",
     ["Warner Chappell", "Warner/Chappell"]),
    ("ent_getty_images", "Getty Images", K.stock_agency, None, "footage-licensing@gettyimages.example",
     ["Getty", "iStock"]),
    ("ent_shutterstock", "Shutterstock", K.stock_agency, None, "licensing@shutterstock.example", []),
    ("ent_pond5", "Pond5", K.stock_agency, None, "licensing@pond5.example", []),
    ("ent_nara", "U.S. National Archives and Records Administration", K.archive, None,
     "reproductions@nara.example", ["National Archives", "NARA", "US National Archives"]),
    ("ent_british_pathe", "British Pathe", K.archive, None, "licensing@britishpathe.example",
     ["British Pathé", "Pathe News"]),
    ("ent_ap_archive", "AP Archive", K.broadcaster, None, "archive-licensing@ap.example",
     ["Associated Press", "AP"]),
]

TEMPLATES = {
    K.studio: ["clip_clearance_request", "deal_memo_short_form"],
    K.broadcaster: ["news_footage_request"],
    K.label: ["master_use_request"],
    K.publisher: ["sync_license_request"],
    K.stock_agency: ["stock_license_quote"],
    K.archive: ["archival_reproduction_request"],
}

# rightsholder_id (None = industry default), layer, unit, low, high, minimum_units, note
RATES = [
    (None, Layer.footage, RateUnit.per_minute, 1500, 4000, 1, "Generic studio/broadcast footage"),
    (None, Layer.still_image, RateUnit.per_image, 250, 1500, 1, "Generic editorial still"),
    (None, Layer.master_recording, RateUnit.per_use, 2500, 15000, 1, "Major-label master, background use"),
    (None, Layer.composition, RateUnit.per_use, 2500, 15000, 1, "Major-publisher sync, background use"),
    (None, Layer.performance, RateUnit.per_use, 1000, 7500, 1, "Recognizable performer likeness"),
    (None, Layer.trademark, RateUnit.per_use, 0, 1000, 1, "Incidental logo use"),
    ("ent_warner_bros_discovery", Layer.footage, RateUnit.per_minute, 2500, 5000, 1, "Archival clip, WBD"),
    ("ent_getty_images", Layer.footage, RateUnit.per_use, 500, 2500, 1, "Rights-managed stock clip"),
    ("ent_getty_images", Layer.still_image, RateUnit.per_image, 175, 1000, 1, "Editorial still"),
    ("ent_shutterstock", Layer.footage, RateUnit.per_use, 80, 400, 1, "Royalty-free clip, enhanced license"),
    ("ent_shutterstock", Layer.still_image, RateUnit.per_image, 15, 200, 1, "Royalty-free still"),
    ("ent_pond5", Layer.footage, RateUnit.per_use, 50, 500, 1, "Royalty-free clip"),
    ("ent_nara", Layer.footage, RateUnit.per_use, 0, 150, 1,
     "Most NARA holdings are public domain; cost is reproduction. Verify underlying rights per item."),
    ("ent_british_pathe", Layer.footage, RateUnit.per_minute, 1000, 3500, 0.5, "Newsreel footage"),
]


def seed(session: Session) -> bool:
    if session.scalar(select(func.count()).select_from(Rightsholder)):
        return False
    with acting_as(session, ActorType.system, "seed", "Initial placeholder directory"):
        # Parents first so FK checks pass.
        for rid, name, kind, parent, email, aliases in ENTITIES:
            rh = Rightsholder(id=rid, name=name, kind=kind.value, parent_id=parent, licensing_email=email,
                              preferred_templates=TEMPLATES.get(kind, []), is_placeholder=True,
                              tier=TIERS.get(rid, "unknown"))
            for a in aliases:
                alias, layers = (a, None) if isinstance(a, str) else (a[0], [layer.value for layer in a[1]])
                rh.aliases.append(RightsholderAlias(alias=alias, layers=layers))
            session.add(rh)
            session.flush()
        for rid, layer, unit, low, high, minimum, note in RATES:
            session.add(RateCard(rightsholder_id=rid, layer=layer.value, unit=unit.value, base_low=Decimal(low),
                                 base_high=Decimal(high), minimum_units=minimum, source_note=note,
                                 is_placeholder=True))
    session.commit()
    return True
