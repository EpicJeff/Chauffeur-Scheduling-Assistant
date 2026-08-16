"""Outbound mail — invites, verification and password resets (auth arc S3).

Inbound mail already existed (intake polls a dedicated mailbox over IMAP);
this is the first time the app SENDS anything.

The decision that shapes the module: **the sender is its own configuration,
with reuse of the intake mailbox offered as a toggle rather than assumed.**
A Gmail app password authenticates SMTP as well as IMAP, so reuse costs no new
credential — but the intake mailbox ANALYSES EVERY MESSAGE THAT ARRIVES IN IT,
that being the whole design of intake. Invites sent from that address bring
their delivery noise home: bounces, out-of-office autoreplies and "did you
actually send me this?" answers all land in the mailbox and get extracted into
event proposals. A grandparent's vacation autoresponder should not become a
proposal on the family's queue.

And mail is never a hard dependency. With nothing configured, `send()` reports
that it could not send and the caller shows a copyable one-time link instead —
same token, same expiry, one less moving part. That is the same
degrade-gracefully rule every HA touchpoint in this app already follows.
"""
import logging
import re
import smtplib
from email.message import EmailMessage
from typing import Optional

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def valid_email(address: str) -> bool:
    return bool(_EMAIL_RE.match((address or '').strip()))


def config(settings: dict = None) -> dict:
    """Resolved sender settings, with the reuse toggle applied.

    `smtp_use_intake` mirrors the intake mailbox's credentials rather than
    copying them into new keys: copying would fossilise a password that the
    family later changes in one place and not the other."""
    if settings is None:
        from services import storage
        settings = storage.get_settings() or {}

    if settings.get('smtp_use_intake'):
        host = (settings.get('ingest_email_host') or '').strip()
        user = (settings.get('ingest_email_user') or '').strip()
        password = settings.get('ingest_email_password') or ''
        # IMAP host -> SMTP host for the common providers. A family that has
        # typed imap.gmail.com should not have to know the outgoing name.
        smtp_host = host.replace('imap.', 'smtp.') if host.startswith('imap.') else host
        return {'host': smtp_host, 'port': int(settings.get('smtp_port') or 587),
                'user': user, 'password': password, 'from': user,
                'source': 'intake'}

    return {'host': (settings.get('smtp_host') or '').strip(),
            'port': int(settings.get('smtp_port') or 587),
            'user': (settings.get('smtp_user') or '').strip(),
            'password': settings.get('smtp_password') or '',
            'from': (settings.get('smtp_from') or settings.get('smtp_user') or '').strip(),
            'source': 'own'}


def configured(settings: dict = None) -> bool:
    cfg = config(settings)
    return bool(cfg['host'] and cfg['user'] and cfg['password'] and cfg['from'])


def from_address_warning(settings: dict = None) -> Optional[str]:
    """Most providers refuse to send from a `From` the authenticated account
    does not own, and the failure arrives as a silent bounce rather than an
    error at save time. Say so in the form instead."""
    cfg = config(settings)
    if not cfg['user'] or not cfg['from']:
        return None
    if cfg['from'].strip().lower() == cfg['user'].strip().lower():
        return None
    return (f"Sending as {cfg['from']} while signed in as {cfg['user']}. Most "
            f"providers reject that unless it is a verified alias, and the "
            f"rejection arrives as a bounce rather than an error here.")


def send(to: str, subject: str, body: str, settings: dict = None) -> dict:
    """Best effort. Returns {'sent': bool, 'reason': str|None}.

    Never raises: every caller has a fallback that is better than a 500 — the
    copyable link — and an invite failing to send is not a reason for the
    parent's click to look broken."""
    if not valid_email(to):
        return {'sent': False, 'reason': 'no valid address'}
    if not configured(settings):
        return {'sent': False, 'reason': 'no mail sender configured'}

    cfg = config(settings)
    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = cfg['from']
    msg['To'] = to
    msg.set_content(body)

    try:
        if cfg['port'] == 465:
            server = smtplib.SMTP_SSL(cfg['host'], cfg['port'], timeout=20)
        else:
            server = smtplib.SMTP(cfg['host'], cfg['port'], timeout=20)
        with server:
            if cfg['port'] != 465:
                server.starttls()
            server.login(cfg['user'], cfg['password'])
            server.send_message(msg)
        return {'sent': True, 'reason': None}
    except Exception as e:
        logger.error(f"Mail send failed to {to}: {e}")
        return {'sent': False, 'reason': str(e)}


# --- the messages -----------------------------------------------------------
# Plain text on purpose. These are read on a phone lock screen by people who
# did not ask for an email, and the one thing that must survive every client
# is the link.

def invite_body(name: str, household: str, link: str) -> str:
    return (f"Hi {name},\n\n"
            f"You've been added to {household}'s Chauffeur — the app the "
            f"family uses for schedules, driving and messages.\n\n"
            f"Set your password here:\n{link}\n\n"
            f"The link works once and expires in seven days. If you weren't "
            f"expecting this, you can ignore it.\n")


def reset_body(name: str, link: str) -> str:
    return (f"Hi {name},\n\n"
            f"Someone asked to reset your Chauffeur password.\n\n"
            f"Set a new one here:\n{link}\n\n"
            f"The link works once and expires in two hours. If that wasn't "
            f"you, nothing has changed and you can ignore this.\n")
