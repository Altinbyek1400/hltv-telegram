#!/usr/bin/env python3
"""
CS2 Tier-1 дайджест -> Telegram суваг (баннер зурагтай).

Эх сурвалж: bo3.gg нээлттэй JSON API.

Илгээх зүйл:
  - тэмцээний баннер зураг (хамгийн том тэмцээнийх)
  - сүүлийн 12 цагт дууссан tier-1 тоглолтын үр дүн
  - дараагийн 24 цагт болох тоглолтын хуваарь
  - улсын туг, зэрэглэл, тэмцээн, шат, формат

Орчны хувьсагч:
  TELEGRAM_BOT_TOKEN   BotFather-аас авсан токен
  TELEGRAM_CHAT_ID     @сувгийн_нэр эсвэл -100... ID
  RESULT_WINDOW_HOURS  анхдагч 12
  UPCOMING_HOURS       анхдагч 24
  MAX_RANK             анхдагч 20
  NO_PHOTO             1 бол зураггүй, зөвхөн текст
  DRY_RUN              1 бол илгээхгүй, зөвхөн хэвлэнэ
"""

from __future__ import annotations

import io
import os
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone

import requests

# ---------------------------------------------------------------- тохиргоо

API = "https://api.bo3.gg/api/v1"
SITE = "https://bo3.gg/matches/"
UB = timezone(timedelta(hours=8))

RESULT_WINDOW_HOURS = int(os.environ.get("RESULT_WINDOW_HOURS", "12"))
UPCOMING_HOURS = int(os.environ.get("UPCOMING_HOURS", "24"))
MAX_RANK = int(os.environ.get("MAX_RANK", "20"))
NO_PHOTO = os.environ.get("NO_PHOTO") == "1"
DRY_RUN = os.environ.get("DRY_RUN") == "1"

TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")

HEADERS = {
    "User-Agent": "cs2-tier1-digest/2.0 (Telegram channel bot)",
    "Accept": "application/json",
}

TIERS = "s,a"
RULE = "━━━━━━━━━━━━━━━━━━"

WEEKDAYS = ["Даваа", "Мягмар", "Лхагва", "Пүрэв", "Баасан", "Бямба", "Ням"]

# Онцлон тэмдэглэх багууд (монгол үзэгчдэд)
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
    data = api_get(
        "matches",
        {
            "filter[matches.status][in]": status,
            "filter[matches.tier][in]": TIERS,
            "sort": sort,
            "page[limit]": str(limit),
            "with": "teams,tournament,stage",
        },
    )
    return data.get("results", [])


def country_flags() -> dict[int, str]:
    """country_id -> туг эможи."""
    out: dict[int, str] = {}
    try:
        data = api_get("countries", {"page[limit]": "300"})
    except RuntimeError:
        return out
    for c in data.get("results", []):
        code = (c.get("code") or "").upper()
        if len(code) == 2 and code.isalpha():
            out[c["id"]] = "".join(chr(0x1F1E6 + ord(ch) - ord("A")) for ch in code)
    return out


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


def team_of(match: dict, side: str, flags: dict[int, str]) -> dict:
    node = match.get(side) or {}
    rank = node.get("rank")
    return {
        "name": node.get("name") or "TBD",
        "rank": rank if isinstance(rank, int) and 0 < rank < 999 else None,
        "flag": flags.get(node.get("country_id"), "🏳"),
    }


def is_tier1(match: dict) -> bool:
    if match.get("tier") == "s":
        return True
    for side in ("team1", "team2"):
        rank = (match.get(side) or {}).get("rank")
        if isinstance(rank, int) and 0 < rank <= MAX_RANK:
            return True
    return False


def stage_of(match: dict) -> str:
    stage = (match.get("stage") or {}).get("title") or ""
    name = (match.get("tournament") or {}).get("name") or ""
    if name and stage.startswith(name):
        stage = stage[len(name):].strip(" -–—:")
    return stage


def bo_label(match: dict) -> str:
    bo = match.get("bo_type")
    return f"bo{bo}" if isinstance(bo, int) and bo > 0 else ""


def meta_line(entry: dict) -> str:
    parts = [p for p in (entry["tournament"], entry["stage"], entry["bo"]) if p]
    return esc(" · ".join(parts))


def name_with_star(team: dict) -> str:
    """Онцлох багийг тодруулна."""
    label = esc(team["name"])
    if team["name"].lower() in SPOTLIGHT:
        label = f"{label} ⭐"
    return label


# ---------------------------------------------------------------- цуглуулах

def collect(now: datetime, flags: dict[int, str]) -> tuple[list, list]:
    since = now - timedelta(hours=RESULT_WINDOW_HOURS)
    until = now + timedelta(hours=UPCOMING_HOURS)

    results = []
    for m in matches("finished", "-start_date"):
        when = parse_dt(m.get("end_date")) or parse_dt(m.get("start_date"))
        if when is None or when < since or not is_tier1(m):
            continue
        results.append(
            {
                "time": when,
                "a": team_of(m, "team1", flags),
                "b": team_of(m, "team2", flags),
                "sa": m.get("team1_score", 0),
                "sb": m.get("team2_score", 0),
                "a_won": m.get("winner_team_id") == m.get("team1_id"),
                "b_won": m.get("winner_team_id") == m.get("team2_id"),
                "tournament": (m.get("tournament") or {}).get("name", ""),
                "stage": stage_of(m),
                "bo": bo_label(m),
                "url": SITE + m["slug"] if m.get("slug") else "",
                "_t": m.get("tournament") or {},
            }
        )
    results.sort(key=lambda x: x["time"], reverse=True)

    upcoming = []
    for m in matches("upcoming,current", "start_date"):
        when = parse_dt(m.get("start_date"))
        if when is None or when > until or when < now - timedelta(hours=4):
            continue
        if not is_tier1(m):
            continue
        upcoming.append(
            {
                "time": when,
                "a": team_of(m, "team1", flags),
                "b": team_of(m, "team2", flags),
                "tournament": (m.get("tournament") or {}).get("name", ""),
                "stage": stage_of(m),
                "bo": bo_label(m),
                "live": m.get("status") == "current" or when <= now,
                "url": SITE + m["slug"] if m.get("slug") else "",
                "_t": m.get("tournament") or {},
            }
        )
    upcoming.sort(key=lambda x: x["time"])

    return results, upcoming


def pick_banner(entries: list[dict]) -> tuple[str, str]:
    """Хамгийн олон тоглолттой тэмцээний баннер ба нэрийг буцаана."""
    counts = Counter()
    lookup = {}
    for e in entries:
        t = e["_t"]
        tid = t.get("id")
        if not tid:
            continue
        counts[tid] += 2 if t.get("tier") == "s" else 1
        lookup[tid] = t
    for tid, _ in counts.most_common():
        t = lookup[tid]
        versions = t.get("banner_image_versions") or {}
        url = (
            versions.get("1000x100")
            or t.get("banner_image_url")
            or versions.get("webp")
            or t.get("image_url")
        )
        if url:
            return url, t.get("name", "")
    return "", ""


# ---------------------------------------------------------------- мессеж

def link(url: str, label: str) -> str:
    return f'<a href="{url}">{label}</a>' if url else label


def build_message(results: list, upcoming: list, now: datetime, event: str) -> str:
    L: list[str] = []

    weekday = WEEKDAYS[now.weekday()]
    L.append(f"⚡️ <b>CS2 TIER-1</b> · {now.strftime('%m.%d')} {weekday}")
    if event:
        L.append(f"<i>{esc(event)}</i>")
    L.append(f"<i>{now.strftime('%H:%M')} · Улаанбаатарын цагаар</i>")
    L.append("")

    # ---------- үр дүн
    L.append(f"🏆 <b>ҮР ДҮН</b> · сүүлийн {RESULT_WINDOW_HOURS} цаг")
    L.append(RULE)
    if results:
        for m in results:
            a, b = m["a"], m["b"]
            na, nb = name_with_star(a), name_with_star(b)
            if m["a_won"]:
                na = f"<b>{na}</b>"
            if m["b_won"]:
                nb = f"<b>{nb}</b>"
            score = f"<b>{m['sa']} — {m['sb']}</b>"
            L.append(f"{a['flag']} {na}  {score}  {nb} {b['flag']}")
            L.append(f"      └ {link(m['url'], meta_line(m))}")
            L.append("")
    else:
        L.append("<i>Энэ хугацаанд дууссан тоглолт алга.</i>")
        L.append("")

    # ---------- хуваарь
    L.append(f"📅 <b>ХУВААРЬ</b> · дараагийн {UPCOMING_HOURS} цаг")
    L.append(RULE)
    if upcoming:
        day = None
        today = now.date()
        for m in upcoming:
            d = m["time"].date()
            if d != day:
                day = d
                if d == today:
                    head = f"Өнөөдөр · {d.strftime('%m.%d')}"
                elif d == today + timedelta(days=1):
                    head = f"Маргааш · {d.strftime('%m.%d')}"
                else:
                    head = d.strftime("%m.%d")
                L.append(f"<b>▸ {head}</b>")
            a, b = m["a"], m["b"]
            when = "🔴 <b>LIVE</b>" if m["live"] else f"<code>{m['time'].strftime('%H:%M')}</code>"
            pair = f"{a['flag']} {name_with_star(a)}  vs  {name_with_star(b)} {b['flag']}"
            L.append(f"{when}  {pair}")
            L.append(f"      └ {link(m['url'], meta_line(m))}")
            L.append("")
    else:
        L.append("<i>Товлогдсон тоглолт алга.</i>")
        L.append("")

    L.append(RULE)
    L.append('<i>Эх сурвалж</i> · <a href="https://bo3.gg/">bo3.gg</a>')
    return "\n".join(L).strip()


def build_caption(results: list, upcoming: list, now: datetime, event: str) -> str:
    """Зурагны дор гарах богино толгой (1024 тэмдэгтийн хязгаартай)."""
    weekday = WEEKDAYS[now.weekday()]
    lines = [f"⚡️ <b>CS2 TIER-1</b> · {now.strftime('%m.%d')} {weekday}"]
    if event:
        lines.append(f"<i>{esc(event)}</i>")
    lines.append("")
    live = [m for m in upcoming if m["live"]]
    if live:
        lines.append(f"🔴 Одоо {len(live)} тоглолт явагдаж байна")
    lines.append(f"🏆 {len(results)} үр дүн · 📅 {len(upcoming)} товлогдсон тоглолт")
    return "\n".join(lines)


# ---------------------------------------------------------------- Telegram

def split_text(text: str, limit: int = 3900) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks, current = [], ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > limit:
            chunks.append(current.rstrip())
            current = ""
        current += line + "\n"
    if current.strip():
        chunks.append(current.rstrip())
    return chunks


def tg(method: str, **kwargs):
    r = requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/{method}", timeout=60, **kwargs)
    payload = r.json()
    if not payload.get("ok"):
        raise SystemExit(f"Telegram алдаа ({method}): {payload}")
    return payload


def fetch_image(url: str) -> bytes | None:
    """Баннерыг татаж, Telegram уншиж чадах форматад хөрвүүлнэ."""
    try:
        r = requests.get(url, headers={"User-Agent": HEADERS["User-Agent"]}, timeout=30)
        if r.status_code != 200 or not r.content:
            return None
        raw = r.content
    except requests.RequestException:
        return None

    try:
        from PIL import Image  # webp -> png
    except ImportError:
        return raw

    try:
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:  # noqa: BLE001
        return raw


def send(text: str, caption: str, banner: str) -> None:
    if DRY_RUN:
        print(f"[БАННЕР] {banner or 'байхгүй'}\n")
        print(text)
        return
    if not TG_TOKEN or not TG_CHAT:
        raise SystemExit("TELEGRAM_BOT_TOKEN болон TELEGRAM_CHAT_ID тохируулаагүй байна")

    photo_sent = False
    if banner and not NO_PHOTO:
        blob = fetch_image(banner)
        if blob:
            try:
                tg(
                    "sendPhoto",
                    data={"chat_id": TG_CHAT, "caption": caption, "parse_mode": "HTML"},
                    files={"photo": ("banner.png", blob, "image/png")},
                )
                photo_sent = True
                print("Баннер илгээлээ")
                time.sleep(1)
            except SystemExit as exc:
                print(f"Баннер илгээж чадсангүй, текстээр үргэлжлүүлнэ: {exc}")

    if not photo_sent:
        text = caption + "\n\n" + text

    for chunk in split_text(text):
        tg(
            "sendMessage",
            data={
                "chat_id": TG_CHAT,
                "text": chunk,
                "parse_mode": "HTML",
                "disable_web_page_preview": "true",
            },
        )
        print(f"Илгээлээ ({len(chunk)} тэмдэгт)")
        time.sleep(1)


# ---------------------------------------------------------------- үндсэн

def main() -> int:
    now = datetime.now(UB)
    print(f"Ажиллаж эхэллээ: {now:%Y-%m-%d %H:%M} УБ")

    flags = country_flags()
    print(f"Улсын туг: {len(flags)}")

    results, upcoming = collect(now, flags)
    print(f"Үр дүн: {len(results)}")
    print(f"Хуваарь: {len(upcoming)}")

    banner, event = pick_banner(results + upcoming)
    print(f"Баннер: {event or 'байхгүй'}")

    send(
        build_message(results, upcoming, now, event),
        build_caption(results, upcoming, now, event),
        banner,
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"АЛДАА: {exc}", file=sys.stderr)
        sys.exit(1)
