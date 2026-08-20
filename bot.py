#!/usr/bin/env python3
"""
CS2 Tier-1 Telegram бот.

Хоёр горим:
  MODE=watch  — 10 минут тутам ажиллана
                  · тоглолт эхлэхээс N минутын өмнө "ТОГЛОЛТЫН ТОВ"
                  · тоглолт эхэлмэгц "LIVE"
                  · тоглолт дуусмагц "ҮР ДҮН"
  MODE=daily  — өдөрт нэг удаа, өнөөдрийн бүх тоглолтын тойм

Төлөвөө state.json дотор хадгалж, давхар пост тавихаас сэргийлнэ.
Эх сурвалж: bo3.gg нээлттэй JSON API.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

import card

# ---------------------------------------------------------------- тохиргоо

API = "https://api.bo3.gg/api/v1"
SITE = "https://bo3.gg/matches/"
UB = timezone(timedelta(hours=8))

MODE = os.environ.get("MODE", "watch")
TIERS = os.environ.get("TIERS", "s,a")
ANNOUNCE_MINUTES = int(os.environ.get("ANNOUNCE_MINUTES", "60"))
STATE_PATH = Path(os.environ.get("STATE_PATH", "state.json"))
KEEP_DAYS = 5
NO_PHOTO = os.environ.get("NO_PHOTO") == "1"
DRY_RUN = os.environ.get("DRY_RUN") == "1"

TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")

HEADERS = {
    "User-Agent": "cs2-tier1-bot/3.0 (Telegram channel)",
    "Accept": "application/json",
}

WEEKDAYS = ["Даваа", "Мягмар", "Лхагва", "Пүрэв", "Баасан", "Бямба", "Ням"]
MONTHS = [
    "1-р сар", "2-р сар", "3-р сар", "4-р сар", "5-р сар", "6-р сар",
    "7-р сар", "8-р сар", "9-р сар", "10-р сар", "11-р сар", "12-р сар",
]
SPOTLIGHT = {"the mongolz"}


# ---------------------------------------------------------------- API

def api_get(path: str, params: dict) -> dict:
    last = None
    for attempt in range(4):
        try:
            r = requests.get(f"{API}/{path}", params=params, headers=HEADERS, timeout=30)
            if r.status_code == 200:
                return r.json()
            last = f"HTTP {r.status_code}"
        except (requests.RequestException, ValueError) as exc:
            last = str(exc)
        time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"bo3.gg /{path} татаж чадсангүй: {last}")


def matches(status: str, sort: str, limit: int = 60) -> list[dict]:
    return api_get(
        "matches",
        {
            "filter[matches.status][in]": status,
            "filter[matches.tier][in]": TIERS,
            "sort": sort,
            "page[limit]": str(limit),
            "with": "teams,tournament,stage",
        },
    ).get("results", [])


_FLAGS: dict[int, str] | None = None


def flags() -> dict[int, str]:
    global _FLAGS
    if _FLAGS is not None:
        return _FLAGS
    out: dict[int, str] = {}
    try:
        for c in api_get("countries", {"page[limit]": "300"}).get("results", []):
            code = (c.get("code") or "").upper()
            if len(code) == 2 and code.isalpha():
                out[c["id"]] = "".join(chr(0x1F1E6 + ord(ch) - ord("A")) for ch in code)
    except RuntimeError:
        pass
    _FLAGS = out
    return out


# ---------------------------------------------------------------- төлөв

def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {}


def save_state(state: dict) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)).timestamp()
    for key in ("announced", "started", "finished"):
        seen = state.get(key, {})
        state[key] = {k: v for k, v in seen.items() if v > cutoff}
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def mark(state: dict, key: str, match_id) -> None:
    state.setdefault(key, {})[str(match_id)] = datetime.now(timezone.utc).timestamp()


def seen(state: dict, key: str, match_id) -> bool:
    return str(match_id) in state.get(key, {})


# ---------------------------------------------------------------- туслахууд

def parse_dt(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UB)
    except ValueError:
        return None


def esc(text) -> str:
    return (
        str(text if text is not None else "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def team_of(m: dict, side: str) -> dict:
    node = m.get(side) or {}
    rank = node.get("rank")
    return {
        "name": node.get("name") or "TBD",
        "rank": rank if isinstance(rank, int) and 0 < rank < 999 else None,
        "flag": flags().get(node.get("country_id"), "🏳"),
        "logo": node.get("image_url"),
        "id": node.get("id"),
    }


def stage_of(m: dict) -> str:
    stage = (m.get("stage") or {}).get("title") or ""
    name = (m.get("tournament") or {}).get("name") or ""
    if name and stage.startswith(name):
        stage = stage[len(name):].strip(" -–—:")
    return stage


def bo_of(m: dict) -> str:
    bo = m.get("bo_type")
    return f"BO{bo}" if isinstance(bo, int) and bo > 0 else ""


def label(team: dict) -> str:
    name = esc(team["name"])
    if team["name"].lower() in SPOTLIGHT:
        name += " ⭐"
    return name


def date_line(dt: datetime) -> str:
    return f"{MONTHS[dt.month - 1]}, {dt.day} · {WEEKDAYS[dt.weekday()]}"


def pack(m: dict) -> dict:
    return {
        "id": m.get("id"),
        "a": team_of(m, "team1"),
        "b": team_of(m, "team2"),
        "sa": m.get("team1_score", 0),
        "sb": m.get("team2_score", 0),
        "winner": m.get("winner_team_id"),
        "start": parse_dt(m.get("start_date")),
        "tournament": (m.get("tournament") or {}).get("name", ""),
        "stage": stage_of(m),
        "bo": bo_of(m),
        "url": SITE + m["slug"] if m.get("slug") else "",
    }


# ---------------------------------------------------------------- Telegram

def tg(method: str, **kwargs) -> dict:
    r = requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/{method}", timeout=60, **kwargs)
    payload = r.json()
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram {method}: {payload}")
    return payload


def post(text: str, image: bytes | None) -> None:
    if DRY_RUN:
        print("-" * 50)
        print(f"[зураг: {'тийм' if image else 'үгүй'}]")
        print(text)
        return
    if not TG_TOKEN or not TG_CHAT:
        raise SystemExit("TELEGRAM_BOT_TOKEN болон TELEGRAM_CHAT_ID тохируулаагүй байна")

    if image and not NO_PHOTO:
        try:
            tg(
                "sendPhoto",
                data={"chat_id": TG_CHAT, "caption": text, "parse_mode": "HTML"},
                files={"photo": ("card.png", image, "image/png")},
            )
            time.sleep(1)
            return
        except RuntimeError as exc:
            print(f"  зурагтай илгээж чадсангүй ({exc}), текстээр оролдоно")

    tg(
        "sendMessage",
        data={
            "chat_id": TG_CHAT,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        },
    )
    time.sleep(1)


def make_card(kind, m, center, sub, footer) -> bytes | None:
    if NO_PHOTO:
        return None
    try:
        return card.render(
            kind, m["a"], m["b"], center, sub, m["tournament"], m["stage"], footer
        )
    except Exception as exc:  # noqa: BLE001
        print(f"  зураг үүсгэж чадсангүй: {exc}")
        return None


# ---------------------------------------------------------------- постууд

def post_announce(m: dict) -> None:
    when = m["start"]
    body = [
        "📋 <b>ТОГЛОЛТЫН ТОВ</b>",
        "",
        f"{m['a']['flag']} <b>{label(m['a'])}</b>  vs  <b>{label(m['b'])}</b> {m['b']['flag']}",
        "",
        f"🗓 {date_line(when)}",
        f"🕘 {when.strftime('%H:%M')} · Улаанбаатарын цагаар",
    ]
    if m["bo"]:
        body.append(f"🎮 {m['bo']}")
    body += ["", f"🏆 {esc(m['tournament'])}"]
    if m["stage"]:
        body.append(f"🔸 {esc(m['stage'])}")
    if m["url"]:
        body += ["", f'▶️ <a href="{m["url"]}">Тоглолтын хуудас</a>']

    image = make_card(
        "announce", m, when.strftime("%H:%M"), m["bo"], f"{date_line(when)} · УБ цагаар"
    )
    post("\n".join(body), image)


def post_start(m: dict) -> None:
    body = [
        "🔴 <b>ТОГЛОЛТ ЭХЭЛЛЭЭ</b>",
        "",
        f"{m['a']['flag']} <b>{label(m['a'])}</b>  vs  <b>{label(m['b'])}</b> {m['b']['flag']}",
        "",
        f"🏆 {esc(m['tournament'])}",
    ]
    if m["stage"]:
        body.append(f"🔸 {esc(m['stage'])}")
    if m["bo"]:
        body.append(f"🎮 {m['bo']}")
    if m["url"]:
        body += ["", f'▶️ <a href="{m["url"]}">Шууд дагах</a>']

    image = make_card("live", m, "VS", m["bo"], "ОДОО ЯВАГДАЖ БАЙНА")
    post("\n".join(body), image)


def post_result(m: dict) -> None:
    a, b = m["a"], m["b"]
    na, nb = label(a), label(b)
    if m["winner"] == a["id"]:
        na = f"<b>{na}</b>"
    elif m["winner"] == b["id"]:
        nb = f"<b>{nb}</b>"

    body = [
        "✅ <b>ТОГЛОЛТ ДУУСЛАА</b>",
        "",
        f"{a['flag']} {na}  <b>{m['sa']} — {m['sb']}</b>  {nb} {b['flag']}",
        "",
        f"🏆 {esc(m['tournament'])}",
    ]
    if m["stage"]:
        body.append(f"🔸 {esc(m['stage'])}")
    if m["bo"]:
        body.append(f"🎮 {m['bo']}")
    if m["url"]:
        body += ["", f'▶️ <a href="{m["url"]}">Дэлгэрэнгүй</a>']

    image = make_card("result", m, f"{m['sa']} — {m['sb']}", m["bo"], "ЭЦСИЙН ДҮН")
    post("\n".join(body), image)


# ---------------------------------------------------------------- горимууд

def run_watch(state: dict) -> None:
    now = datetime.now(UB)
    first_run = not state.get("announced") and not state.get("finished")
    if first_run:
        print("Анхны ажиллагаа — одоо байгаа тоглолтуудыг зөвхөн тэмдэглэж, пост тавихгүй.")

    # --- дууссан
    for raw in matches("finished", "-start_date", 40):
        m = pack(raw)
        if seen(state, "finished", m["id"]):
            continue
        if m["start"] and m["start"] < now - timedelta(hours=8):
            mark(state, "finished", m["id"])
            continue
        mark(state, "finished", m["id"])
        mark(state, "started", m["id"])
        mark(state, "announced", m["id"])
        if first_run:
            continue
        print(f"ҮР ДҮН: {m['a']['name']} {m['sa']}–{m['sb']} {m['b']['name']}")
        post_result(m)

    # --- эхэлсэн
    for raw in matches("current", "start_date", 40):
        m = pack(raw)
        if seen(state, "started", m["id"]):
            continue
        mark(state, "started", m["id"])
        mark(state, "announced", m["id"])
        if first_run:
            continue
        print(f"LIVE: {m['a']['name']} vs {m['b']['name']}")
        post_start(m)

    # --- тов
    horizon = now + timedelta(minutes=ANNOUNCE_MINUTES)
    for raw in matches("upcoming", "start_date", 40):
        m = pack(raw)
        if m["start"] is None or m["start"] > horizon or seen(state, "announced", m["id"]):
            continue
        mark(state, "announced", m["id"])
        if first_run:
            continue
        print(f"ТОВ: {m['a']['name']} vs {m['b']['name']} — {m['start']:%H:%M}")
        post_announce(m)


def run_daily(state: dict) -> None:
    now = datetime.now(UB)
    today = now.date()
    if state.get("daily") == str(today):
        print("Өнөөдрийн тойм аль хэдийн илгээгдсэн.")
        return

    rows = []
    for raw in matches("upcoming,current", "start_date", 60):
        m = pack(raw)
        if m["start"] and m["start"].date() == today:
            rows.append(m)

    body = [
        "🗓 <b>ӨНӨӨДРИЙН ТОГЛОЛТУУД</b>",
        f"<i>{date_line(now)} · УБ цагаар</i>",
        "",
    ]
    if rows:
        current = None
        for m in rows:
            if m["tournament"] != current:
                current = m["tournament"]
                body.append(f"🏆 <b>{esc(current)}</b>")
            line = (
                f"<code>{m['start'].strftime('%H:%M')}</code>  "
                f"{m['a']['flag']} {label(m['a'])} vs {label(m['b'])} {m['b']['flag']}"
            )
            if m["bo"]:
                line += f" · {m['bo']}"
            body.append(line)
            body.append("")
    else:
        body.append("<i>Өнөөдөр tier-1 тоглолт товлогдоогүй байна.</i>")

    body.append('<i>Эх сурвалж</i> · <a href="https://bo3.gg/">bo3.gg</a>')
    post("\n".join(body).strip(), None)
    state["daily"] = str(today)
    print(f"Өдрийн тойм илгээлээ ({len(rows)} тоглолт)")


# ---------------------------------------------------------------- үндсэн

def main() -> int:
    print(f"MODE={MODE} · {datetime.now(UB):%Y-%m-%d %H:%M} УБ")
    state = load_state()

    try:
        if MODE == "daily":
            run_daily(state)
        else:
            run_watch(state)
    finally:
        # Алдаа гарсан ч аль хэдийн илгээсэн постуудаа тэмдэглэж үлдээнэ
        save_state(state)

    print("Дууслаа.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"АЛДАА: {exc}", file=sys.stderr)
        sys.exit(1)
