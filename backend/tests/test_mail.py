"""The mail loop: sending guards, the inbound webhook, reply reading, and the cost ledger.

The parser is stubbed throughout — the job, the DB writes, the workflow guards and the API
stay real. What is being tested is that a model's reading never moves a task on its own, and
that everything around it fails in the safe direction.
"""

from decimal import Decimal

import pytest

from app.config import get_settings
from app.models import InboundMessage, MailThread
from app.services import mail, replies
from app.services.replies import ItemReading, ReplyReading
from tests.conftest import ingest, tasks_by_layer

RICK = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


# ---------------------------------------------------------------- fixtures

@pytest.fixture
def allow_example(monkeypatch):
    """The seed directory is all `.example`; most tests need sending to it permitted."""
    monkeypatch.setattr(get_settings(), "allow_reserved_tld_recipients", True)


@pytest.fixture
def sent_packet(accepted, project, allow_example):
    """A finalized, sent packet covering the master recording, with its reply thread open."""
    [res] = ingest(accepted, project["id"], {"url": RICK, "notes": "Diner jukebox",
                                             "usage_seconds": 45})
    master = tasks_by_layer(accepted, res["asset_id"])["master_recording"]
    accepted.post(f"/api/tasks/{master['id']}/transition", json={"to": "budget_approved"})
    packet = accepted.post(f"/api/projects/{project['id']}/packets",
                           json={"task_ids": [master["id"]]}).json()
    accepted.post(f"/api/packets/{packet['id']}/finalize", json={})
    r = accepted.post(f"/api/packets/{packet['id']}/send",
                      json={"allow_unverified": True})
    assert r.status_code == 200, r.text
    return {"packet": packet, "task_id": master["id"], "outbound": r.json()}


def stub_parser(monkeypatch, reading: ReplyReading):
    """Replace only the network call. Everything downstream of it stays real."""
    class FakeResponse:
        parsed = reading

    class FakeClient:
        class messages:  # noqa: N801 - mirrors the SDK's shape
            @staticmethod
            def parse(**_kwargs):
                return FakeResponse()

    monkeypatch.setattr(replies, "_client", lambda _settings: FakeClient())


def deliver(client, token, text, *, message_id="msg-1", subject="Re: Clearance request",
            from_email="sync@sonymusic.example"):
    settings = get_settings()
    return client.post("/api/mail/inbound", json={
        "MessageID": message_id,
        "FromFull": {"Email": from_email, "Name": "Dana Reyes"},
        "OriginalRecipient": mail.reply_to_address(token, settings),
        "Subject": subject,
        "TextBody": text,
    })


def thread_token(SessionTest, packet_id):
    with SessionTest() as s:
        return s.query(MailThread).filter_by(packet_id=packet_id).one().token


# ---------------------------------------------------------------- send guards

def test_reserved_domains_are_refused_by_default(accepted, project):
    """The seed directory is full of plausible `.example` addresses; none may be mailed."""
    [res] = ingest(accepted, project["id"], {"url": RICK})
    master = tasks_by_layer(accepted, res["asset_id"])["master_recording"]
    accepted.post(f"/api/tasks/{master['id']}/transition", json={"to": "budget_approved"})
    packet = accepted.post(f"/api/projects/{project['id']}/packets",
                           json={"task_ids": [master["id"]]}).json()
    accepted.post(f"/api/packets/{packet['id']}/finalize", json={})

    r = accepted.post(f"/api/packets/{packet['id']}/send", json={"allow_unverified": True})
    assert r.status_code == 422
    assert "reserved documentation domain" in r.json()["detail"]


def test_unverified_contacts_need_an_explicit_override(accepted, project, allow_example):
    [res] = ingest(accepted, project["id"], {"url": RICK})
    master = tasks_by_layer(accepted, res["asset_id"])["master_recording"]
    accepted.post(f"/api/tasks/{master['id']}/transition", json={"to": "budget_approved"})
    packet = accepted.post(f"/api/projects/{project['id']}/packets",
                           json={"task_ids": [master["id"]]}).json()
    accepted.post(f"/api/packets/{packet['id']}/finalize", json={})

    r = accepted.post(f"/api/packets/{packet['id']}/send", json={})
    assert r.status_code == 422
    assert "unverified placeholder data" in r.json()["detail"]

    assert accepted.post(f"/api/packets/{packet['id']}/send",
                         json={"allow_unverified": True}).status_code == 200


def test_an_unfinalized_packet_cannot_be_sent(accepted, project, allow_example):
    [res] = ingest(accepted, project["id"], {"url": RICK})
    master = tasks_by_layer(accepted, res["asset_id"])["master_recording"]
    accepted.post(f"/api/tasks/{master['id']}/transition", json={"to": "budget_approved"})
    packet = accepted.post(f"/api/projects/{project['id']}/packets",
                           json={"task_ids": [master["id"]]}).json()

    r = accepted.post(f"/api/packets/{packet['id']}/send", json={"allow_unverified": True})
    assert r.status_code == 409
    assert "Finalize the packet" in r.json()["detail"]


def test_sending_records_the_message_and_opens_a_thread(sent_packet, accepted):
    out = sent_packet["outbound"]
    assert out["status"] == "sent"
    assert out["to_email"] == "sync@sonymusic.example"
    assert "+" in out["reply_to"] and out["reply_to"].endswith("@inbound.example.com")

    thread = accepted.get(f"/api/packets/{sent_packet['packet']['id']}/thread").json()
    assert len(thread["outbound"]) == 1
    assert thread["inbound"] == []
    # The console provider is the default and does not touch the network.
    assert out["provider"] == "console"


def test_console_provider_says_it_did_not_really_send(sent_packet):
    """A successful-looking row must admit nothing left the machine."""
    assert sent_packet["outbound"]["error"] is None
    assert "Set CLEARCUT_MAIL_PROVIDER" in sent_packet["outbound"]["note"]


# ---------------------------------------------------------------- addressing

def test_thread_token_survives_the_address_it_travels_in():
    settings = get_settings()
    token = mail.new_thread_token()
    address = mail.reply_to_address(token, settings)
    assert mail.token_from_address(address) == token
    assert mail.token_from_address("someone@example.com") is None
    assert mail.token_from_address(None, "", address) == token


def test_quoted_history_is_trimmed_but_short_replies_survive():
    reply = ("Approved at $2,500.\n\nOn Tue, 12 May 2026, Clearances wrote:\n"
             "> We are handling clearances on The Long Way Home\n> and would like...")
    assert mail.strip_quoted(reply) == "Approved at $2,500."
    # A terse reply must never be trimmed to nothing.
    assert mail.strip_quoted("Approved, $2,500") == "Approved, $2,500"


# ---------------------------------------------------------------- webhook

def test_unroutable_replies_are_kept_and_look_identical_to_routed_ones(accepted, SessionTest):
    r = deliver(accepted, "nosuchtoken00000", "Who is this?")
    assert r.status_code == 200
    assert r.json()["status"] == "stored"

    with SessionTest() as s:
        message = s.query(InboundMessage).one()
        assert message.status == "unroutable"
        assert message.thread_id is None
        assert "No open thread" in message.error


def test_webhook_retries_do_not_produce_a_second_reading(accepted, sent_packet, SessionTest,
                                                          monkeypatch):
    stub_parser(monkeypatch, ReplyReading(
        kind="quote", confidence=0.95, summary="Quoted $2,500.",
        items=[ItemReading(task_ref=1, kind="quote", amount=2500, currency="USD",
                           quote_text="We can license it at $2,500.", confidence=0.95)]))
    token = thread_token(SessionTest, sent_packet["packet"]["id"])

    first = deliver(accepted, token, "We can license it at $2,500.", message_id="dup-1")
    second = deliver(accepted, token, "We can license it at $2,500.", message_id="dup-1")

    assert first.json()["status"] == "stored"
    assert second.json()["status"] == "duplicate"
    assert second.json()["inbound_id"] == first.json()["inbound_id"]

    changes = accepted.get(
        f"/api/projects/{sent_packet['packet']['project_id']}/proposed-changes").json()
    assert len(changes) == 1


def test_a_bad_signature_is_refused(accepted, monkeypatch):
    monkeypatch.setattr(get_settings(), "inbound_webhook_secret", "shhh")
    r = accepted.post("/api/mail/inbound", json={"MessageID": "x", "TextBody": "hi"},
                      headers={"X-Clearcut-Signature": "not-the-right-digest"})
    assert r.status_code == 401
    monkeypatch.setattr(get_settings(), "inbound_webhook_secret", None)


def test_a_correct_signature_is_accepted(accepted, monkeypatch):
    import hashlib
    import hmac
    import json

    monkeypatch.setattr(get_settings(), "inbound_webhook_secret", "shhh")
    payload = {"MessageID": "signed-1", "FromFull": {"Email": "a@b.example"}, "TextBody": "hello"}
    raw = json.dumps(payload).encode()
    digest = hmac.new(b"shhh", raw, hashlib.sha256).hexdigest()

    r = accepted.post("/api/mail/inbound", content=raw,
                      headers={"Content-Type": "application/json", "X-Clearcut-Signature": digest})
    assert r.status_code == 200
    monkeypatch.setattr(get_settings(), "inbound_webhook_secret", None)


# ---------------------------------------------------------------- reading a reply

def test_a_quote_becomes_a_proposal_and_moves_nothing_on_its_own(
        accepted, sent_packet, SessionTest, monkeypatch):
    stub_parser(monkeypatch, ReplyReading(
        kind="quote", confidence=0.96, summary="Sony quoted $2,500 for the master.",
        reasoning="They name a figure for the only item asked about.",
        items=[ItemReading(task_ref=1, kind="quote", amount=2500, currency="USD",
                           quote_text="we can license the master at $2,500",
                           confidence=0.96, note="One-time fee.")]))
    token = thread_token(SessionTest, sent_packet["packet"]["id"])
    deliver(accepted, token, "Happy to help — we can license the master at $2,500.")

    # The task has not moved.
    task = accepted.get(f"/api/tasks/{sent_packet['task_id']}").json()
    assert task["stage"] == "outreach_sent"
    assert task["quoted_amount"] is None

    [change] = accepted.get(
        f"/api/projects/{sent_packet['packet']['project_id']}/proposed-changes").json()
    assert change["status"] == "pending"
    assert change["kind"] == "quote"
    assert Decimal(change["quoted_amount"]) == Decimal("2500.00")
    assert change["to_stage"] == "quote_received"
    assert change["blocked_reason"] is None
    # The producer confirms against the rightsholder's own words.
    assert change["quote_text"] == "we can license the master at $2,500"
    assert change["asset_title"]


def test_confirming_a_proposal_moves_the_task_and_records_the_fee(
        accepted, sent_packet, SessionTest, monkeypatch):
    stub_parser(monkeypatch, ReplyReading(
        kind="quote", confidence=0.96, summary="Quoted $2,500.",
        items=[ItemReading(task_ref=1, kind="quote", amount=2500, currency="USD",
                           quote_text="$2,500", confidence=0.96)]))
    token = thread_token(SessionTest, sent_packet["packet"]["id"])
    deliver(accepted, token, "We can do $2,500.")
    [change] = accepted.get(
        f"/api/projects/{sent_packet['packet']['project_id']}/proposed-changes").json()

    r = accepted.post(f"/api/proposed-changes/{change['id']}/apply", json={})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "applied"

    task = accepted.get(f"/api/tasks/{sent_packet['task_id']}").json()
    assert task["stage"] == "quote_received"
    assert Decimal(task["quoted_amount"]) == Decimal("2500.00")


def test_the_parsed_figure_can_be_corrected_at_the_moment_of_confirmation(
        accepted, sent_packet, SessionTest, monkeypatch):
    """The producer reads the quote themselves; the model's number is a starting point."""
    stub_parser(monkeypatch, ReplyReading(
        kind="quote", confidence=0.7, summary="Quoted 2500.",
        items=[ItemReading(task_ref=1, kind="quote", amount=2500,
                           quote_text="$2,500 per use", confidence=0.7)]))
    token = thread_token(SessionTest, sent_packet["packet"]["id"])
    deliver(accepted, token, "It is $2,500 per use, and you need two uses.")
    [change] = accepted.get(
        f"/api/projects/{sent_packet['packet']['project_id']}/proposed-changes").json()

    accepted.post(f"/api/proposed-changes/{change['id']}/apply", json={"quoted_amount": "5000.00"})
    task = accepted.get(f"/api/tasks/{sent_packet['task_id']}").json()
    assert Decimal(task["quoted_amount"]) == Decimal("5000.00")


def test_rejecting_a_proposal_leaves_the_task_alone(accepted, sent_packet, SessionTest, monkeypatch):
    stub_parser(monkeypatch, ReplyReading(
        kind="denied", confidence=0.9, summary="Refused.",
        items=[ItemReading(task_ref=1, kind="denied", quote_text="we cannot license this",
                           confidence=0.9)]))
    token = thread_token(SessionTest, sent_packet["packet"]["id"])
    deliver(accepted, token, "Sorry, we cannot license this.")
    [change] = accepted.get(
        f"/api/projects/{sent_packet['packet']['project_id']}/proposed-changes").json()

    r = accepted.post(f"/api/proposed-changes/{change['id']}/reject", json={"reason": "Misread"})
    assert r.json()["status"] == "rejected"
    assert accepted.get(f"/api/tasks/{sent_packet['task_id']}").json()["stage"] == "outreach_sent"
    # And it cannot then be applied.
    assert accepted.post(f"/api/proposed-changes/{change['id']}/apply", json={}).status_code == 409


def test_an_approval_with_no_fee_is_blocked_rather_than_guessed(
        accepted, sent_packet, SessionTest, monkeypatch):
    """The workflow will not advance past outreach without a figure, and the queue says so."""
    stub_parser(monkeypatch, ReplyReading(
        kind="approved", confidence=0.93, summary="Approved, no fee named.",
        items=[ItemReading(task_ref=1, kind="approved", amount=None,
                           quote_text="Yes, you may use it.", confidence=0.93)]))
    token = thread_token(SessionTest, sent_packet["packet"]["id"])
    deliver(accepted, token, "Yes, you may use it.")

    [change] = accepted.get(
        f"/api/projects/{sent_packet['packet']['project_id']}/proposed-changes").json()
    assert change["quoted_amount"] is None
    assert "No fee named" in change["blocked_reason"]
    assert accepted.post(f"/api/proposed-changes/{change['id']}/apply", json={}).status_code == 409
    # Supplying the figure at confirmation time unblocks it.
    r = accepted.post(f"/api/proposed-changes/{change['id']}/apply", json={"quoted_amount": "0"})
    assert r.status_code == 200
    assert accepted.get(f"/api/tasks/{sent_packet['task_id']}").json()["stage"] == "quote_received"


def test_correspondence_produces_no_stage_change(accepted, sent_packet, SessionTest, monkeypatch):
    stub_parser(monkeypatch, ReplyReading(
        kind="needs_info", confidence=0.88, summary="They want the scene context.",
        items=[ItemReading(task_ref=1, kind="needs_info",
                           quote_text="can you send the scene", confidence=0.88)]))
    token = thread_token(SessionTest, sent_packet["packet"]["id"])
    deliver(accepted, token, "Before we quote, can you send the scene it appears in?")

    [change] = accepted.get(
        f"/api/projects/{sent_packet['packet']['project_id']}/proposed-changes").json()
    assert change["to_stage"] is None
    assert "Correspondence only" in change["blocked_reason"]


def test_a_reading_for_an_unknown_item_is_dropped(accepted, sent_packet, SessionTest, monkeypatch):
    stub_parser(monkeypatch, ReplyReading(
        kind="quote", confidence=0.9, summary="Quoted something.",
        items=[ItemReading(task_ref=99, kind="quote", amount=100, quote_text="$100",
                           confidence=0.9)]))
    token = thread_token(SessionTest, sent_packet["packet"]["id"])
    r = deliver(accepted, token, "$100 for the second item.")
    assert r.json()["proposals"] == 0


def test_a_reply_survives_an_unavailable_parser(accepted, sent_packet, SessionTest, monkeypatch):
    """No credentials must cost us the reply, only the reading."""
    def unavailable(_settings):
        raise replies.ParserUnavailable("No Claude credentials found.")

    monkeypatch.setattr(replies, "_client", unavailable)
    token = thread_token(SessionTest, sent_packet["packet"]["id"])
    r = deliver(accepted, token, "We can license it at $2,500.")
    assert r.status_code == 200
    assert r.json()["proposals"] == 0

    [message] = accepted.get(f"/api/projects/{sent_packet['packet']['project_id']}/inbox").json()
    assert message["text_body"] == "We can license it at $2,500."
    assert message["intent"] is None
    assert "No Claude credentials" in message["error"]


def test_a_crashing_parser_does_not_lose_the_reply(accepted, sent_packet, SessionTest, monkeypatch):
    class Boom:
        class messages:  # noqa: N801
            @staticmethod
            def parse(**_kwargs):
                raise RuntimeError("upstream exploded")

    monkeypatch.setattr(replies, "_client", lambda _s: Boom())
    token = thread_token(SessionTest, sent_packet["packet"]["id"])
    assert deliver(accepted, token, "We can license it at $2,500.").status_code == 200

    [message] = accepted.get(f"/api/projects/{sent_packet['packet']['project_id']}/inbox").json()
    assert message["status"] == "failed"
    assert message["text_body"] == "We can license it at $2,500."


def test_applying_one_proposal_supersedes_the_others_for_that_task(
        accepted, sent_packet, SessionTest, monkeypatch):
    reading = ReplyReading(
        kind="quote", confidence=0.95, summary="Quoted.",
        items=[ItemReading(task_ref=1, kind="quote", amount=2500, quote_text="$2,500",
                           confidence=0.95)])
    stub_parser(monkeypatch, reading)
    token = thread_token(SessionTest, sent_packet["packet"]["id"])
    deliver(accepted, token, "$2,500.", message_id="m-1")
    deliver(accepted, token, "Correction: $2,500 firm.", message_id="m-2")

    project_id = sent_packet["packet"]["project_id"]
    changes = accepted.get(f"/api/projects/{project_id}/proposed-changes").json()
    assert len(changes) == 2

    accepted.post(f"/api/proposed-changes/{changes[0]['id']}/apply", json={})
    after = {c["id"]: c["status"] for c in
             accepted.get(f"/api/projects/{project_id}/proposed-changes?status_filter=all").json()}
    assert after[changes[0]["id"]] == "applied"
    assert after[changes[1]["id"]] == "superseded"


# ---------------------------------------------------------------- auto-apply

def test_auto_apply_is_off_by_default(sent_packet, accepted, SessionTest, monkeypatch):
    stub_parser(monkeypatch, ReplyReading(
        kind="denied", confidence=1.0, summary="Refused.",
        items=[ItemReading(task_ref=1, kind="denied", quote_text="we cannot", confidence=1.0)]))
    token = thread_token(SessionTest, sent_packet["packet"]["id"])
    deliver(accepted, token, "We cannot license this.")

    [change] = accepted.get(
        f"/api/projects/{sent_packet['packet']['project_id']}/proposed-changes").json()
    assert change["status"] == "pending"


def test_auto_apply_never_touches_a_proposal_carrying_money(sent_packet, accepted, SessionTest,
                                                            monkeypatch):
    """A wrong stage is visible on the board; a wrong fee becomes a number in a budget."""
    settings = get_settings()
    monkeypatch.setattr(settings, "auto_apply_replies", True)
    monkeypatch.setattr(settings, "auto_apply_min_confidence", 0.5)
    stub_parser(monkeypatch, ReplyReading(
        kind="quote", confidence=1.0, summary="Quoted $2,500.",
        items=[ItemReading(task_ref=1, kind="quote", amount=2500, quote_text="$2,500",
                           confidence=1.0)]))
    token = thread_token(SessionTest, sent_packet["packet"]["id"])
    deliver(accepted, token, "$2,500.")

    [change] = accepted.get(
        f"/api/projects/{sent_packet['packet']['project_id']}/proposed-changes").json()
    assert change["status"] == "pending"
    assert accepted.get(f"/api/tasks/{sent_packet['task_id']}").json()["stage"] == "outreach_sent"


def test_auto_apply_moves_a_confident_non_financial_change_when_switched_on(
        sent_packet, accepted, SessionTest, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "auto_apply_replies", True)
    monkeypatch.setattr(settings, "auto_apply_min_confidence", 0.9)
    stub_parser(monkeypatch, ReplyReading(
        kind="denied", confidence=0.99, summary="Refused outright.",
        items=[ItemReading(task_ref=1, kind="denied", quote_text="we cannot license this",
                           confidence=0.99)]))
    token = thread_token(SessionTest, sent_packet["packet"]["id"])
    deliver(accepted, token, "We cannot license this.")

    assert accepted.get(f"/api/tasks/{sent_packet['task_id']}").json()["stage"] == "denied"
    [change] = accepted.get(
        f"/api/projects/{sent_packet['packet']['project_id']}"
        f"/proposed-changes?status_filter=applied").json()
    assert change["decided_by"] == "system:auto_apply"


def test_auto_apply_respects_the_confidence_floor(sent_packet, accepted, SessionTest, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "auto_apply_replies", True)
    monkeypatch.setattr(settings, "auto_apply_min_confidence", 0.95)
    stub_parser(monkeypatch, ReplyReading(
        kind="denied", confidence=0.6, summary="Probably refused.",
        items=[ItemReading(task_ref=1, kind="denied", quote_text="cannot", confidence=0.6)]))
    token = thread_token(SessionTest, sent_packet["packet"]["id"])
    deliver(accepted, token, "I think we cannot do this one.")

    [change] = accepted.get(
        f"/api/projects/{sent_packet['packet']['project_id']}/proposed-changes").json()
    assert change["status"] == "pending"


# ---------------------------------------------------------------- audit

def test_the_ledger_records_the_model_and_the_person_separately(
        accepted, sent_packet, SessionTest, monkeypatch):
    stub_parser(monkeypatch, ReplyReading(
        kind="quote", confidence=0.95, summary="Quoted $2,500.",
        items=[ItemReading(task_ref=1, kind="quote", amount=2500, quote_text="$2,500",
                           confidence=0.95)]))
    token = thread_token(SessionTest, sent_packet["packet"]["id"])
    deliver(accepted, token, "$2,500.")
    [change] = accepted.get(
        f"/api/projects/{sent_packet['packet']['project_id']}/proposed-changes").json()
    accepted.post(f"/api/proposed-changes/{change['id']}/apply", json={})

    audit = accepted.get("/api/audit", params={"limit": 500}).json()
    # The reading is attributed to the model...
    assert any(r["table_name"] == "reply_intents" and r["actor_type"] == "llm" for r in audit)
    # ...and the task only moved under a named person.
    moves = [r for r in audit if r["table_name"] == "clearance_tasks"
             and "stage" in r["changes"] and r["changes"]["stage"][1] == "quote_received"]
    assert moves and all(r["actor_type"] == "user" for r in moves)
    assert any("reply reading" in (r["reason"] or "") for r in moves)


# ---------------------------------------------------------------- cost ledger

def test_ledger_reports_estimate_quote_and_signed_side_by_side(accepted, project):
    [res] = ingest(accepted, project["id"], {"url": RICK, "usage_seconds": 45})
    tasks = tasks_by_layer(accepted, res["asset_id"])
    master = tasks["master_recording"]

    ledger = accepted.get(f"/api/projects/{project['id']}/ledger").json()
    line = next(l for l in ledger["lines"] if l["task_id"] == master["id"])
    assert line["basis"] == "estimate"
    assert line["variance"] is None
    assert Decimal(line["exposure"]) == Decimal(line["estimate_high"])

    accepted.post(f"/api/tasks/{master['id']}/transition", json={"to": "budget_approved"})
    accepted.post(f"/api/tasks/{master['id']}/transition", json={"to": "outreach_sent"})
    accepted.patch(f"/api/tasks/{master['id']}", json={"quoted_amount": "9000.00"})

    ledger = accepted.get(f"/api/projects/{project['id']}/ledger").json()
    line = next(l for l in ledger["lines"] if l["task_id"] == master["id"])
    assert line["basis"] == "quoted"
    assert Decimal(line["exposure"]) == Decimal("9000.00")
    # Variance is measured against the top of the range, which is what a producer planned to.
    assert Decimal(line["variance"]) == Decimal("9000.00") - Decimal(line["estimate_high"])
    assert ledger["totals"]["over_estimate_tasks"] >= 1


def test_the_signed_figure_outranks_the_quote(accepted, project):
    [res] = ingest(accepted, project["id"], {"url": RICK, "usage_seconds": 45})
    master = tasks_by_layer(accepted, res["asset_id"])["master_recording"]
    for stage in ("budget_approved", "outreach_sent"):
        accepted.post(f"/api/tasks/{master['id']}/transition", json={"to": stage})
    accepted.patch(f"/api/tasks/{master['id']}", json={"quoted_amount": "9000.00"})
    accepted.post(f"/api/tasks/{master['id']}/transition", json={"to": "quote_received"})
    accepted.patch(f"/api/tasks/{master['id']}", json={"agreed_amount": "7500.00"})
    accepted.post(f"/api/tasks/{master['id']}/transition", json={"to": "deal_memo_signed"})

    ledger = accepted.get(f"/api/projects/{project['id']}/ledger").json()
    line = next(l for l in ledger["lines"] if l["task_id"] == master["id"])
    assert line["basis"] == "agreed"
    assert Decimal(line["exposure"]) == Decimal("7500.00")
    assert Decimal(ledger["totals"]["committed"]) == Decimal("7500.00")


def test_dropped_tasks_stay_visible_but_cost_nothing(accepted, project):
    [res] = ingest(accepted, project["id"], {"url": RICK, "usage_seconds": 45})
    master = tasks_by_layer(accepted, res["asset_id"])["master_recording"]
    accepted.post(f"/api/tasks/{master['id']}/transition", json={"to": "dropped"})

    ledger = accepted.get(f"/api/projects/{project['id']}/ledger").json()
    line = next(l for l in ledger["lines"] if l["task_id"] == master["id"])
    assert line["closed"] is True
    assert Decimal(line["exposure"]) == Decimal(0)
    assert ledger["totals"]["closed_tasks"] == 1


def test_contingency_covers_only_the_part_still_being_guessed(accepted, project):
    """Once a task is quoted, holding 15% on top of a real number is double counting."""
    [res] = ingest(accepted, project["id"], {"url": RICK, "usage_seconds": 45})
    tasks = tasks_by_layer(accepted, res["asset_id"])
    before = accepted.get(f"/api/projects/{project['id']}/ledger").json()["totals"]

    master = tasks["master_recording"]
    for stage in ("budget_approved", "outreach_sent"):
        accepted.post(f"/api/tasks/{master['id']}/transition", json={"to": stage})
    accepted.patch(f"/api/tasks/{master['id']}", json={"quoted_amount": "2500.00"})

    after = accepted.get(f"/api/projects/{project['id']}/ledger").json()["totals"]
    assert Decimal(after["recommended_contingency"]) < Decimal(before["recommended_contingency"])
