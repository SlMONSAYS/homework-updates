"""Nightly 9 PM email to Simon's parents: everything submitted since the last email, grouped by class.

Run by .github/workflows/nightly-email.yml. Reads homework.txt (the "# done <date> <time> | ..." lines),
sends one email through Gmail, and records the send time in email-state.json so the next email
starts where this one ended.

Environment:
  GMAIL_ADDRESS, GMAIL_APP_PASSWORD, PARENT_EMAIL   repo secrets
  TEST=true      send now with "[Test]" in the subject; doesn't count as tonight's email
  DRY_RUN=1      don't send; write email-preview.html instead
"""

import html
import json
import os
import re
import smtplib
import sys
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
TZ = ZoneInfo("America/Vancouver")
SEND_HOUR = 21
STATE_FILE = ROOT / "email-state.json"
PAGE_URL = "https://slmonsays.github.io/homework-updates/"
DONE_RE = re.compile(r"^#\s*done\s+(\d{4}-\d{2}-\d{2})\s+(\d{1,2}):(\d{2})\s*\|\s*(.*)$")

# Same palette as the website.
BG, CARD, TEXT, MUTED, WOOD, ACCENT = "#151815", "#1b1f1b", "#e4dfd6", "#8a857b", "#a08b72", "#7ba576"
FONT = "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"


def class_order():
    """The class list lives in index.html; read it from there so the two never drift apart."""
    src = (ROOT / "index.html").read_text()
    block = re.search(r"const CLASSES = \[(.*?)\];", src, re.S).group(1)
    return re.findall(r'"([^"]+)"', block)


def submitted_since(since, until):
    """(class, title) for each item checked off in (since, until], in file order."""
    classes = class_order()
    out = []
    for raw in (ROOT / "homework.txt").read_text().splitlines():
        m = DONE_RE.match(raw.strip())
        if not m:
            continue
        stamp = datetime.strptime(f"{m[1]} {int(m[2]):02d}:{m[3]}", "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
        if not since < stamp <= until:
            continue
        parts = [p.strip() for p in m[4].split("|")]
        if len(parts) < 3:
            continue
        title = " | ".join(parts[2:])
        title = re.sub(r"^★\s*", "", title).split(" // ")[0].strip()
        cls = next((c for c in classes if c.lower() == parts[1].lower()), parts[1])
        out.append((cls, title))
    order = {c: i for i, c in enumerate(classes)}
    return sorted(out, key=lambda x: (order.get(x[0], len(order)), x[0]))


def build(items, now):
    day_long = now.strftime("%A, %B ") + str(now.day)
    day_short = now.strftime("%a, %b ") + str(now.day)
    n = len(items)
    subject = (f"Submitted today: {n} assignment{'s' if n != 1 else ''} ({day_short})"
               if n else f"Nothing submitted today ({day_short})")

    groups = {}
    for cls, title in items:
        groups.setdefault(cls, []).append(title)

    rows = ""
    for cls, titles in groups.items():
        rows += (f'<tr><td style="padding:16px 0 6px;font-family:{FONT};font-size:11px;font-weight:600;'
                 f'letter-spacing:1.2px;text-transform:uppercase;color:{TEXT};">{html.escape(cls)}</td></tr>')
        for t in titles:
            rows += (f'<tr><td style="padding:5px 0 5px 14px;border-left:2px solid #3a3d3a;font-family:{FONT};'
                     f'font-size:15px;line-height:1.5;color:{TEXT};">{html.escape(t)}</td></tr>')
    if not n:
        rows = (f'<tr><td style="padding:8px 0 2px;font-family:{FONT};font-size:15px;color:{MUTED};">'
                f'Nothing was checked off today.</td></tr>')
    heading = f"{n} assignment{'s' if n != 1 else ''} submitted" if n else "Submitted"

    body = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<meta name="color-scheme" content="dark"><meta name="supported-color-schemes" content="dark">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600&display=swap" rel="stylesheet"></head>
<body style="margin:0;padding:0;background:{BG};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{BG};">
<tr><td align="center" style="padding:32px 16px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;">
<tr><td style="font-family:{FONT};font-size:24px;font-weight:600;letter-spacing:-0.5px;color:{TEXT};padding-bottom:4px;">Simon's Homework Updates</td></tr>
<tr><td style="font-family:{FONT};font-size:13px;color:{MUTED};padding-bottom:20px;border-bottom:1px solid #2a2d2a;">Submitted today · {day_long}</td></tr>
<tr><td style="padding-top:20px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{CARD};border-left:4px solid {WOOD};border-radius:12px;">
<tr><td style="padding:18px 20px 20px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0">
<tr><td style="font-family:{FONT};font-size:17px;font-weight:600;color:{WOOD};padding-bottom:2px;">{heading}</td></tr>
{rows}
</table></td></tr></table></td></tr>
<tr><td style="padding-top:22px;"><a href="{PAGE_URL}" style="display:inline-block;background:{ACCENT};color:#142014;font-family:{FONT};font-size:14px;font-weight:600;text-decoration:none;border-radius:8px;padding:10px 16px;">Open the homework page</a></td></tr>
<tr><td style="font-family:{FONT};font-size:12px;color:{MUTED};padding-top:22px;">Sent automatically every night at 9 PM.</td></tr>
</table></td></tr></table></body></html>"""

    text = f"Simon's Homework Updates\nSubmitted today · {day_long}\n\n"
    text += "".join(f"{cls.upper()}\n" + "".join(f"  - {t}\n" for t in ts) + "\n" for cls, ts in groups.items()) \
        if n else "Nothing was checked off today.\n\n"
    text += f"Open the homework page: {PAGE_URL}\n"
    return subject, body, text


def main():
    test = os.environ.get("TEST", "").lower() == "true"
    dry = os.environ.get("DRY_RUN") == "1"
    now = datetime.now(TZ)
    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    last = datetime.fromisoformat(state["last_sent"]).replace(tzinfo=TZ) if state.get("last_sent") else None

    # Two runs are scheduled (one for summer time, one for winter); only the one at 9 PM local sends.
    if not test and not dry:
        if now.hour < SEND_HOUR:
            print(f"It's {now:%H:%M} in Vancouver; waiting for the 9 PM run.")
            return
        if last and last.date() == now.date():
            print("Tonight's email was already sent.")
            return

    since = last or now - timedelta(days=1)
    subject, body, text = build(submitted_since(since, now), now)
    if test:
        subject = "[Test] " + subject

    if dry:
        (ROOT / "email-preview.html").write_text(body)
        print(subject, "\n\n", text, sep="")
        return

    sender, password, to = (os.environ.get(k, "") for k in ("GMAIL_ADDRESS", "GMAIL_APP_PASSWORD", "PARENT_EMAIL"))
    if not (sender and password and to):
        sys.exit("Missing GMAIL_ADDRESS, GMAIL_APP_PASSWORD or PARENT_EMAIL secret.")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr(("Simon's Homework", sender))
    msg["To"] = to
    msg.set_content(text)
    msg.add_alternative(body, subtype="html")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(sender, password)
        smtp.send_message(msg)
    print("Sent:", subject)

    if not test:
        STATE_FILE.write_text(json.dumps({"last_sent": now.strftime("%Y-%m-%dT%H:%M")}) + "\n")


if __name__ == "__main__":
    main()
