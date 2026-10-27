"""Nightly 9 PM Telegram update to Simon's family group: everything submitted since the last update,
grouped by class.

Run by .github/workflows/nightly-update.yml. Reads homework.txt (the "# done <date> <time> | ..." lines),
posts one message through the Telegram bot, and records the send time in update-state.json so the
next update starts where this one ended.

Environment:
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID   repo secrets
  MODE=test        send now with "[Test]" in front; doesn't count as tonight's update
  MODE=find-group  list the groups the bot has been added to, so you can copy the chat ID
  DRY_RUN=1        print the message instead of sending it
"""

import html
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
TZ = ZoneInfo("America/Vancouver")
SEND_HOUR = 21
STATE_FILE = ROOT / "update-state.json"
PAGE_URL = "https://slmonsays.github.io/homework-updates/"
DONE_RE = re.compile(r"^#\s*done\s+(\d{4}-\d{2}-\d{2})\s+(\d{1,2}):(\d{2})\s*\|\s*(.*)$")


def class_order():
    """The class list lives in index.html; read it from there so the two never drift apart."""
    src = (ROOT / "index.html").read_text()
    block = re.search(r"const CLASSES = \[(.*?)\];", src, re.S).group(1)
    return re.findall(r'"([^"]+)"', block)


def submitted_since(since, until):
    """(class, title) for each item checked off in (since, until], grouped in class order."""
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
    """The message, in Telegram's HTML formatting. No times, on purpose."""
    day = now.strftime("%A, %B ") + str(now.day)
    lines = ["📚 <b>Simon's Homework Updates</b>", f"Submitted today · {day}", ""]
    if items:
        n = len(items)
        lines += [f"<b>{n} assignment{'s' if n != 1 else ''} submitted</b>", ""]
        current = None
        for cls, title in items:
            if cls != current:
                if current is not None:
                    lines.append("")
                lines.append(f"<b>{html.escape(cls.upper(), quote=False)}</b>")
                current = cls
            lines.append(f"  • {html.escape(title, quote=False)}")
    else:
        lines.append("Nothing was checked off today.")
    lines += ["", f'🔗 <a href="{PAGE_URL}">Open the homework page</a>']
    return "\n".join(lines)


def telegram(method, token, payload=None):
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=json.dumps(payload or {}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return json.load(e)   # Telegram explains errors in the body, e.g. a wrong token or chat ID


def find_group(token):
    """Print the groups the bot can see. Telegram only keeps these for about a day."""
    me = telegram("getMe", token).get("result", {})
    username = me.get("username", "your_bot")
    got = telegram("getUpdates", token)
    if not got.get("ok"):
        sys.exit(f"Telegram returned an error: {got.get('description', got)}")
    updates = got.get("result", [])
    chats = {}
    for u in updates:
        for key in ("message", "my_chat_member", "chat_member", "edited_message"):
            chat = (u.get(key) or {}).get("chat")
            if chat and chat.get("type") in ("group", "supergroup"):
                chats[chat["id"]] = chat.get("title", "")
    print(f"Bot @{username} can see {len(updates)} recent update(s).")
    if not chats:
        sys.exit("No groups found yet. In Telegram:\n"
                 f"  1. Make sure @{username} is a member of your family group.\n"
                 f"  2. In the group, send exactly:  /hello@{username}\n"
                 "     (bots in groups ignore normal messages; a command with the bot's name gets through)\n"
                 "  3. Run 'Find my group' again within a day.\n"
                 "If it still finds nothing, remove the bot from the group, add it back, and repeat.")
    for chat_id, title in chats.items():
        # This log is public on a public repo, so only hint at the group's name.
        print(f"Group starting with '{title[:1]}' ({len(title)} letters): TELEGRAM_CHAT_ID = {chat_id}")


def main():
    mode = os.environ.get("MODE", "")
    dry = os.environ.get("DRY_RUN") == "1"
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    if mode == "find-group":
        if not token:
            sys.exit("Add the TELEGRAM_BOT_TOKEN secret first.")
        find_group(token)
        return

    test = mode == "test"
    now = datetime.now(TZ)
    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    last = datetime.fromisoformat(state["last_sent"]).replace(tzinfo=TZ) if state.get("last_sent") else None

    # Two runs are scheduled (one for summer time, one for winter); only the one at 9 PM local sends.
    if not test and not dry:
        if now.hour < SEND_HOUR:
            print(f"It's {now:%H:%M} in Vancouver; waiting for the 9 PM run.")
            return
        if last and last.date() == now.date():
            print("Tonight's update was already sent.")
            return

    since = last or now - timedelta(days=1)
    text = build(submitted_since(since, now), now)
    if test:
        text = "[Test] " + text

    if dry:
        print(text)
        return

    if not (token and chat_id):
        sys.exit("Missing the TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID secret.")
    result = telegram("sendMessage", token, {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "link_preview_options": {"is_disabled": True},
    })
    if not result.get("ok"):
        sys.exit(f"Telegram said no: {result}")
    print("Sent.")

    if not test:
        STATE_FILE.write_text(json.dumps({"last_sent": now.strftime("%Y-%m-%dT%H:%M")}) + "\n")


if __name__ == "__main__":
    main()
