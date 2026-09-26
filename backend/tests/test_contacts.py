"""Credit-line evidence, contact reliability scoring, and the recommendation itself."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.config import Settings
from app.enums import Layer
from app.models import Asset, ClearanceTask, Organization, Project, Rightsholder
from app.services import contacts, evidence, providers
from app.services.mapping import effective_contact

def an_org(session) -> Organization:
    """These are unit tests over the resolver, but a project still needs a tenant."""
    org = session.scalar(select(Organization).limit(1))
    if org is None:
        org = Organization(name="Test Productions", slug="test-productions")
        session.add(org)
        session.flush()
    return org


# ---------------------------------------------------------------- evidence


def asset_with(**fields) -> Asset:
    base = dict(description=None, user_notes=None, title=None, ingest_payload={})
    base.update(fields)
    return Asset(**base)


def test_phonogram_notice_identifies_the_master_owner():
    claims = evidence.collect(asset_with(
        description="℗ 2019 RCA Records, a division of Sony Music Entertainment")).claims
    assert claims[0].name == "RCA Records"
    assert claims[0].claim_type == "phonogram_notice"
    assert Layer.master_recording.value in claims[0].layers
    # The (P) line speaks to the recording, not the song.
    assert Layer.composition.value not in claims[0].layers


def test_copyright_notice_identifies_the_underlying_work():
    claims = evidence.collect(asset_with(description="© 1987 Sony Music Publishing")).claims
    assert claims[0].name == "Sony Music Publishing"
    assert Layer.composition.value in claims[0].layers


def test_provided_to_youtube_line_is_read():
    ev = evidence.collect(asset_with(
        description="Provided to YouTube by Sony Music Entertainment\n\n℗ 1987 RCA Records"))
    names = {c.name for c in ev.claims}
    assert "Sony Music Entertainment" in names
    assert "RCA Records" in names


def test_courtesy_and_credit_lines():
    ev = evidence.collect(asset_with(user_notes="Footage courtesy of British Pathe. Photo: AP Archive"))
    names = {c.name for c in ev.claims}
    assert "British Pathe" in names
    assert "AP Archive" in names


def test_trailing_boilerplate_is_trimmed():
    claims = evidence.collect(asset_with(description="© 2001 Warner Bros. Pictures. All rights reserved.")).claims
    assert claims[0].name == "Warner Bros. Pictures"


def test_prose_is_not_mistaken_for_an_owner():
    ev = evidence.collect(asset_with(description="The video shows a copyright notice on a wall."))
    assert [c for c in ev.claims if c.name.lower().startswith("notice on")] == []


def test_evidence_is_filtered_per_layer():
    ev = evidence.collect(asset_with(description="℗ 2019 RCA Records\n© 1987 Sony Music Publishing"))
    assert [c.name for c in ev.for_layer(Layer.master_recording)] == ["RCA Records"]
    assert [c.name for c in ev.for_layer(Layer.composition)] == ["Sony Music Publishing"]


def test_claims_carry_their_source_and_excerpt():
    claim = evidence.collect(asset_with(user_notes="Licensed by Getty Images")).claims[0]
    assert claim.source_field == "user_notes"
    assert "Getty" in claim.excerpt


# ---------------------------------------------------------------- reliability


def rh(**fields) -> Rightsholder:
    base = dict(id="ent_x", name="X", kind="label", tier="unknown", is_placeholder=False,
                outreach_attempts=0, outreach_responses=0, preferred_templates=[])
    base.update(fields)
    return Rightsholder(**base)


DIRECT = {"via_rightsholder_id": "ent_x", "via_name": "X", "licensing_email": "a@b.example",
          "address": None, "preferred_templates": [], "is_placeholder": False}
NO_CONTACT = {**DIRECT, "licensing_email": None}


def test_a_major_scores_above_an_unknown():
    major, _ = contacts.reliability_of(rh(tier="major"), DIRECT)
    unknown, _ = contacts.reliability_of(rh(tier="unknown"), DIRECT)
    assert major > unknown


def test_verification_raises_reliability():
    verified, _ = contacts.reliability_of(
        rh(tier="notable", verified_at=datetime.now(UTC), verification_source="official site"), DIRECT)
    placeholder, _ = contacts.reliability_of(rh(tier="notable", is_placeholder=True), DIRECT)
    assert verified > placeholder


def test_missing_intake_is_penalised():
    with_contact, _ = contacts.reliability_of(rh(tier="major"), DIRECT)
    without, _ = contacts.reliability_of(rh(tier="major"), NO_CONTACT)
    assert with_contact > without


def test_track_record_only_counts_once_there_is_data():
    _, cold = contacts.reliability_of(rh(tier="major"), DIRECT)
    assert "track_record" not in cold["components"]

    _, warm = contacts.reliability_of(
        rh(tier="major", outreach_attempts=10, outreach_responses=9, avg_response_days=4.0), DIRECT)
    assert warm["components"]["track_record"]["score"] == 90.0
    assert "9 of 10" in warm["components"]["track_record"]["note"]


def test_breakdown_explains_every_component():
    _, breakdown = contacts.reliability_of(rh(tier="major"), DIRECT)
    for name in ("standing", "verification", "contact_directness"):
        assert breakdown["components"][name]["note"]
        assert 0 <= breakdown["components"][name]["score"] <= 100


# ---------------------------------------------------------------- recommendation


@pytest.fixture
def resolved(SessionTest):
    """A master-recording task whose description credits RCA, resolved end to end."""
    with SessionTest() as session:
        project = Project(org_id=an_org(session).id, name="Diner",
                          distribution_scope="festival", production_tier="ultra_low")
        session.add(project)
        session.flush()
        asset = Asset(
            project_id=project.id, source_type="url_ingest", raw_source="https://example.test/a",
            platform="youtube", platform_asset_id="a", title="Never Gonna Give You Up",
            owner_name="Rick Astley",
            description="Provided to YouTube by Sony Music Entertainment\n\n℗ 1987 RCA Records",
            published_at=None, thumbnail_url=None, duration_seconds=212,
            inferred_keywords=["Rick Astley"], user_notes=None, usage_seconds=40,
            ingest_status="complete", ingest_error=None, ingest_payload={},
        )
        asset.tasks = [ClearanceTask(layer=Layer.master_recording.value, stage="sourced",
                                     mapping_candidates=[])]
        session.add(asset)
        session.flush()
        resolution = contacts.resolve(session, asset.tasks[0], Settings())
        yield resolution


def test_the_credited_label_is_recommended(resolved):
    assert resolved.recommended is not None
    assert resolved.recommended.name == "RCA Records"
    assert resolved.recommended.evidence, "the recommendation should cite the credit line"
    assert "credits them" in resolved.recommended.reasons[0] or any(
        "credits them" in reason for reason in resolved.recommended.reasons)


def test_options_carry_cost_reliability_and_identity(resolved):
    option = resolved.recommended
    assert 0 <= option.identity <= 100
    assert 0 <= option.reliability <= 100
    assert option.cost_high is not None and option.cost_high > 0
    assert option.contact["licensing_email"], "contact resolves up to the parent's intake"


def test_licensing_runs_through_the_parent_when_the_label_has_no_desk(resolved):
    # RCA has no intake of its own in the seed; Sony Music Entertainment does.
    contact = resolved.recommended.contact
    assert contact["via_name"] == "Sony Music Entertainment"
    assert any("runs through" in reason for reason in resolved.recommended.reasons)


def test_a_resolved_task_gets_no_research_homework(resolved):
    assert resolved.leads == []


def test_low_confidence_options_are_listed_but_blocked(SessionTest):
    with SessionTest() as session:
        project = Project(org_id=an_org(session).id, name="P",
                          distribution_scope="festival", production_tier="ultra_low")
        session.add(project)
        session.flush()
        asset = Asset(project_id=project.id, source_type="url_ingest", raw_source="https://x.test/1",
                      platform="other", platform_asset_id=None, title="Unnamed clip",
                      owner_name="Some Guy Productions", description=None, published_at=None,
                      thumbnail_url=None, duration_seconds=None, inferred_keywords=[],
                      user_notes=None, usage_seconds=None, ingest_status="partial",
                      ingest_error=None, ingest_payload={})
        asset.tasks = [ClearanceTask(layer=Layer.footage.value, stage="sourced", mapping_candidates=[])]
        session.add(asset)
        session.flush()

        resolution = contacts.resolve(session, asset.tasks[0], Settings())
        assert resolution.recommended is None
        # Nothing credible, so the producer gets somewhere to look instead.
        sources = {lead["source"] for lead in resolution.leads}
        assert "copyright_office" in sources
        assert "copyright_alliance" in sources


def test_research_leads_carry_a_prefilled_query(SessionTest):
    class FakeAsset:
        owner_name = "Estate of Jane Doe"
        title = "A photograph"
        description = None

    class FakeTask:
        layer = Layer.still_image.value
        asset = FakeAsset()

    leads = providers.research_leads(FakeTask(), [], Settings(), unresolved=True)
    watch = next(lead for lead in leads if lead["source"] == "watch")
    assert "Estate+of+Jane+Doe" in watch["url"]
    assert watch["automatable"] is False  # no sanctioned automated access to WATCH


def test_configured_providers_flip_to_automatable():
    settings = Settings(ccc_api_key="k")
    assert providers.configured_providers(settings) == {"ccc"}
    assert providers.configured_providers(Settings()) == set()


def test_cheaper_alternative_is_surfaced_when_it_is_not_the_pick():
    """A cheap unreliable option must still be visible, just not recommended."""
    def option(name, reliability, cost, identity=95.0):
        return contacts.ContactOption(
            rightsholder_id=f"ent_{name}", name=name, kind="label", identity=identity,
            reliability=reliability, cost_low=Decimal(cost), cost_high=Decimal(cost),
            overall=0.0, contact=DIRECT, reliability_breakdown={}, reasons=[], blockers=[],
        )

    sony = option("Sony Music", 95.0, 8000)
    indie = option("Random Productions", 45.0, 1200)
    resolution = contacts.Resolution(options=[sony, indie], recommended=sony, cheapest=indie, leads=[])

    fields = resolution.to_task_fields()
    assert fields["recommended_contact"]["name"] == "Sony Music"
    assert fields["recommended_contact"]["cheaper_alternative"]["name"] == "Random Productions"
    assert len(fields["contact_options"]) == 2


def test_the_assigned_rightsholder_is_always_an_option(SessionTest):
    """A manual assignment is the strongest signal there is; never rank it out of existence."""
    with SessionTest() as session:
        project = Project(org_id=an_org(session).id, name="P",
                          distribution_scope="festival", production_tier="ultra_low")
        session.add(project)
        session.flush()
        asset = Asset(project_id=project.id, source_type="url_ingest", raw_source="https://x.test/2",
                      platform="youtube", platform_asset_id="2", title="Some song",
                      owner_name="Rick Astley", description=None, published_at=None,
                      thumbnail_url=None, duration_seconds=None, inferred_keywords=[],
                      user_notes=None, usage_seconds=None, ingest_status="complete",
                      ingest_error=None, ingest_payload={})
        # Composition layer: the "Rick Astley" alias is scoped to master_recording, so name
        # matching finds nobody here. The human's pick must still be evaluated.
        task = ClearanceTask(layer=Layer.composition.value, stage="rights_mapped",
                             mapping_candidates=[], rightsholder_id="ent_universal_music_publishing",
                             mapping_method="manual")
        asset.tasks = [task]
        session.add(asset)
        session.flush()

        resolution = contacts.resolve(session, task, Settings())

        assert resolution.recommended is not None
        assert resolution.recommended.rightsholder_id == "ent_universal_music_publishing"
        assert resolution.recommended.identity == 100.0
        assert any("Currently assigned" in reason for reason in resolution.recommended.reasons)
        assert resolution.leads == []


def test_an_auto_assigned_rightsholder_keeps_its_matcher_confidence(SessionTest):
    with SessionTest() as session:
        project = Project(org_id=an_org(session).id, name="P",
                          distribution_scope="festival", production_tier="ultra_low")
        session.add(project)
        session.flush()
        asset = Asset(project_id=project.id, source_type="url_ingest", raw_source="https://x.test/3",
                      platform="youtube", platform_asset_id="3", title="Clip", owner_name="Nobody",
                      description=None, published_at=None, thumbnail_url=None, duration_seconds=None,
                      inferred_keywords=[], user_notes=None, usage_seconds=None,
                      ingest_status="complete", ingest_error=None, ingest_payload={})
        task = ClearanceTask(layer=Layer.footage.value, stage="rights_mapped", mapping_candidates=[],
                             rightsholder_id="ent_getty_images", mapping_method="auto",
                             mapping_confidence=72.0)
        asset.tasks = [task]
        session.add(asset)
        session.flush()

        option = next(o for o in contacts.resolve(session, task, Settings()).options
                      if o.rightsholder_id == "ent_getty_images")
        assert option.identity == 72.0
        assert any("by the matcher" in reason for reason in option.reasons)
