"""Outbound email and inbound webhook normalization.

Three things live here, in order of how much they matter:

1. **Guards on sending.** This is the first part of the system that can reach a real person,
   and the seed directory is full of plausible-looking but unverified addresses. Sending is
   refused to reserved TLDs and to unverified placeholder contacts unless the caller
   explicitly overrides, and the default provider does not touch the network at all.
2. **A provider seam.** Postmark and SendGrid differ in payload shape and signature scheme,
   so both are normalized to the same `InboundPayload` before anything else sees them.
3. **Signature verification.** The reply-to token is routing, not authentication — it rides in
   the headers of every message we send. The webhook signature is what makes an inbound
   message trustworthy, so an unverified one is refused rather than parsed.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import re
import secrets
from dataclasses import dataclass, field

import httpx

from app.config import Settings

log = logging.getLogger(__name__)

TOKEN_BYTES = 18

# Reserved for documentation and testing (RFC 2606 / 6761). The seed directory uses
# `.example` deliberately, so refusing these by default is what stops a dev box mailing a
# real licensing desk.
RESERVED_TLDS = {"example", "invalid", "test", "localhost"}

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# `reply+<token>@domain`; sub-addressing survives every provider we support.
ADDRESS_RE = re.compile(r"([A-Za-z0-9_-]+)\+([A-Za-z0-9_-]{8,64})@")


class MailError(RuntimeError):
    """Sending was refused or failed. The message is shown to the user verbatim."""


class SignatureError(MailError):
    """An inbound webhook could not be authenticated."""


@dataclass
class Outgoing:
    to_email: str
    subject: str
    body_html: str
    body_text: str
    reply_to: str
    from_email: str
    from_name: str


@dataclass
class SendResult:
    provider: str
    message_id: str | None
    delivered: bool
    note: str | None = None


@dataclass
class InboundPayload:
    """A reply, flattened to the fields we actually use."""

    provider: str
    message_id: str
    from_email: str
    to_email: str | None
    subject: str | None
    text_body: str
    from_name: str | None = None
    recipients: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- addressing


def new_thread_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def reply_to_address(token: str, settings: Settings) -> str:
    return f"{settings.inbound_mailbox}+{token}@{settings.inbound_domain}"


def token_from_address(*addresses: str | None) -> str | None:
    """Pull the thread token out of whichever address carries it.

    Providers disagree about which field holds the address we were reached on — `To`,
    `OriginalRecipient`, an envelope recipient — so every candidate is checked rather than
    trusting one.
    """
    for address in addresses:
        if not address:
            continue
        match = ADDRESS_RE.search(address)
        if match:
            return match.group(2)
    return None


def is_reserved(email: str) -> bool:
    domain = email.rsplit("@", 1)[-1].strip().lower().rstrip(".")
    return domain.rsplit(".", 1)[-1] in RESERVED_TLDS


def check_recipient(email: str | None, settings: Settings, *, is_placeholder: bool,
                    allow_unverified: bool) -> None:
    """Refuse to send before anything is recorded, not after."""
    if not email or not EMAIL_RE.match(email.strip()):
        raise MailError("This packet has no usable recipient address. Add one before sending.")
    if is_reserved(email) and not settings.allow_reserved_tld_recipients:
        raise MailError(
            f"'{email}' is a reserved documentation domain, which the seed directory uses on "
            "purpose. Set CLEARCUT_ALLOW_RESERVED_TLD_RECIPIENTS=true to send to it anyway.")
    if is_placeholder and not allow_unverified:
        raise MailError(
            "This contact is unverified placeholder data. Verify the licensing address in the "
            "directory, or resend with allow_unverified=true if you have checked it yourself.")


# ---------------------------------------------------------------- sending


def send(message: Outgoing, settings: Settings, *, client: httpx.Client | None = None) -> SendResult:
    provider = (settings.mail_provider or "console").lower()
    if provider == "console":
        return _send_console(message)
    if provider == "postmark":
        return _send_postmark(message, settings, client)
    if provider == "sendgrid":
        return _send_sendgrid(message, settings, client)
    raise MailError(f"Unknown mail provider '{provider}'. Use console, postmark or sendgrid.")


def _send_console(message: Outgoing) -> SendResult:
    """Record the message as sent without a network call.

    The default, so a fresh checkout exercises the whole loop — thread, ledger, reply
    parsing — without the risk of actually mailing anyone.
    """
    log.info("[mail:console] to=%s reply-to=%s subject=%s", message.to_email, message.reply_to,
             message.subject)
    return SendResult("console", f"console-{secrets.token_hex(8)}", delivered=False,
                      note="Logged locally. Set CLEARCUT_MAIL_PROVIDER to send for real.")


def _post(client: httpx.Client | None, url: str, *, headers: dict, json: dict) -> httpx.Response:
    if client is not None:
        return client.post(url, headers=headers, json=json)
    with httpx.Client(timeout=20.0) as owned:
        return owned.post(url, headers=headers, json=json)


def _send_postmark(message: Outgoing, settings: Settings, client) -> SendResult:
    if not settings.postmark_server_token:
        raise MailError("CLEARCUT_POSTMARK_SERVER_TOKEN is not set.")
    try:
        response = _post(
            client, "https://api.postmarkapp.com/email",
            headers={"X-Postmark-Server-Token": settings.postmark_server_token,
                     "Accept": "application/json"},
            json={"From": f"{message.from_name} <{message.from_email}>", "To": message.to_email,
                  "ReplyTo": message.reply_to, "Subject": message.subject,
                  "HtmlBody": message.body_html, "TextBody": message.body_text,
                  "MessageStream": "outbound"})
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise MailError(f"Postmark rejected the message: {exc}") from exc
    return SendResult("postmark", response.json().get("MessageID"), delivered=True)


def _send_sendgrid(message: Outgoing, settings: Settings, client) -> SendResult:
    if not settings.sendgrid_api_key:
        raise MailError("CLEARCUT_SENDGRID_API_KEY is not set.")
    try:
        response = _post(
            client, "https://api.sendgrid.com/v3/mail/send",
            headers={"Authorization": f"Bearer {settings.sendgrid_api_key}"},
            json={"personalizations": [{"to": [{"email": message.to_email}]}],
                  "from": {"email": message.from_email, "name": message.from_name},
                  "reply_to": {"email": message.reply_to},
                  "subject": message.subject,
                  "content": [{"type": "text/plain", "value": message.body_text},
                              {"type": "text/html", "value": message.body_html}]})
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise MailError(f"SendGrid rejected the message: {exc}") from exc
    return SendResult("sendgrid", response.headers.get("X-Message-Id"), delivered=True)


# ---------------------------------------------------------------- inbound


def verify_signature(raw_body: bytes, headers: dict, settings: Settings) -> None:
    """Authenticate a webhook, or refuse it.

    With no secret configured the check is skipped and a warning is logged — usable on a
    machine the webhook cannot reach from outside, and loud enough not to be mistaken for
    a working configuration in production.
    """
    secret = settings.inbound_webhook_secret
    if not secret:
        log.warning("Inbound webhook signature check skipped: CLEARCUT_INBOUND_WEBHOOK_SECRET is unset.")
        return

    lower = {k.lower(): v for k, v in headers.items()}
    provided = lower.get("x-clearcut-signature") or lower.get("x-webhook-signature")
    if not provided:
        raise SignatureError("Missing webhook signature header.")

    digest = hmac.new(secret.encode(), raw_body, hashlib.sha256)
    # Accept either encoding: providers differ, and both are the same bytes.
    candidates = (digest.hexdigest(), base64.b64encode(digest.digest()).decode())
    if not any(hmac.compare_digest(provided.strip(), c) for c in candidates):
        raise SignatureError("Webhook signature did not match.")


def normalize_inbound(payload: dict, settings: Settings) -> InboundPayload:
    provider = (settings.mail_provider or "console").lower()
    if provider == "sendgrid":
        return _normalize_sendgrid(payload)
    # Postmark's shape doubles as our own test/console shape.
    return _normalize_postmark(payload, provider if provider != "sendgrid" else "postmark")


def _first_text(*values) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _normalize_postmark(payload: dict, provider: str) -> InboundPayload:
    from_full = payload.get("FromFull") or {}
    recipients = [r.get("Email", "") for r in (payload.get("ToFull") or []) if r.get("Email")]
    to_email = payload.get("OriginalRecipient") or payload.get("To") or (recipients[0] if recipients else None)
    message_id = _first_text(payload.get("MessageID"), payload.get("MessageId"))
    if not message_id:
        raise MailError("Inbound payload has no message id.")
    return InboundPayload(
        provider=provider,
        message_id=message_id,
        from_email=_first_text(from_full.get("Email"), payload.get("From")),
        from_name=from_full.get("Name") or None,
        to_email=to_email,
        subject=payload.get("Subject"),
        text_body=_first_text(payload.get("TextBody"), payload.get("StrippedTextReply")),
        recipients=recipients,
    )


def _normalize_sendgrid(payload: dict) -> InboundPayload:
    message_id = _first_text(payload.get("message_id"), payload.get("sg_message_id"),
                             payload.get("Message-ID"))
    if not message_id:
        raise MailError("Inbound payload has no message id.")
    envelope = payload.get("envelope") or {}
    if isinstance(envelope, str):
        import json as _json

        try:
            envelope = _json.loads(envelope)
        except ValueError:
            envelope = {}
    return InboundPayload(
        provider="sendgrid",
        message_id=message_id,
        from_email=_first_text(payload.get("from")),
        to_email=_first_text(payload.get("to"), *(envelope.get("to") or [])) or None,
        subject=payload.get("subject"),
        text_body=_first_text(payload.get("text"), payload.get("html")),
        recipients=list(envelope.get("to") or []),
    )


# Quoted history below these markers is the letter we sent, echoed back. Trimming it keeps
# the parser reading the reply rather than re-reading our own ask.
QUOTE_MARKERS = (
    re.compile(r"^On .{5,80}wrote:\s*$", re.MULTILINE),
    re.compile(r"^-{2,}\s*Original Message\s*-{2,}\s*$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^_{10,}\s*$", re.MULTILINE),
    re.compile(r"^From:\s.+$", re.MULTILINE),
)


def strip_quoted(text: str) -> str:
    """Cut the reply down to what the sender actually typed.

    Conservative on purpose: if trimming would leave almost nothing, the full text is kept,
    because a short reply like "Approved, $2,500" must survive intact.
    """
    earliest = len(text)
    for marker in QUOTE_MARKERS:
        match = marker.search(text)
        if match:
            earliest = min(earliest, match.start())

    head = text[:earliest]
    # Drop trailing `>` quote lines the markers did not catch.
    lines = [line for line in head.splitlines() if not line.lstrip().startswith(">")]
    trimmed = "\n".join(lines).strip()
    return trimmed if len(trimmed) >= 12 else text.strip()
