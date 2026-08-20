#!/usr/bin/env python3
"""
CS2 Tier-1 дайджест -> Telegram суваг.

Эх сурвалж: bo3.gg нээлттэй JSON API (HLTV нь Cloudflare-аар хаагддаг тул).

12 цаг тутам ажиллана:
  - сүүлийн 12 цагт дууссан tier-1 тоглолтын үр дүн
  - дараагийн 24 цагт болох тоглолтын хуваарь
  - тоглолт бүрийн тэмцээн ба шат (Playoffs, Group Stage гэх мэт)

Орчны хувьсагч:
  TELEGRAM_BOT_TOKEN   BotFather-аас авсан токен
  TELEGRAM_CHAT_ID     @сувгийн_нэр эсвэл -100... хэлбэрийн ID
  RESULT_WINDOW_HOURS  анхдагч 12
  UPCOMING_HOURS       анхдагч 24
  MAX_RANK             анхдагч 20 — энэ зэрэглэлээс дээш багийг оруулна
  DRY_RUN              1 бол илгээхгүй, зөвхөн хэвлэнэ
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

# ---------------------------------------------------------------- тохиргоо

API = "https://api.bo3.gg/api/v1/matches"
SITE = "https://bo3.gg/matches/"
UB = timezone(timedelta(hours=8))  # Asia/Ulaanbaatar

RESULT_WINDOW_HOURS = int(os.environ.get("RESULT_WINDOW_HOURS", "12"))
UPCOMING_HOURS = int(os.environ.get("UPCOMING_HOURS", "24"))
MAX_RANK = int(os.environ.get("MAX_RANK", "20"))
DRY_RUN = os.environ.get("DRY_RUN") == "1"

TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")

HEADERS = {
    "User-Agent": "cs2-tier1-digest/1.0 (Telegram channel bot)",
    "Accept": "application/json",
}

TIERS = "s,a"  # bo3.gg-ийн tier ангилал: s = хамгийн дээд


# ---------------------------------------------------------------- туслахууд

def api_get(status: str, sort: str, limit: int = 60) -> list[dict]:
    """bo3.gg-ээс тоглолтын жагсаалт татна."""
    params = {
        "filter[matches.status][in]": status,
        "filter[matches.tier][in]": TIERS,
        "sort": sort,
        "page[limit]": str(limit),
        "with": "teams,tournament,stage",
    }
    last = None
    for attempt in range(4):
        try:
            r = requests.get(API, params=params, headers=HEADERS, timeout=30)
            if r.status_code == 200:
                return r.json().get("results", [])
            last = f"HTTP {r.status_code}"
        except (requests.RequestException, ValueError) as exc:
            last = str(exc)
        time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"bo3.gg API татаж чадсангүй ({status}): {last}")


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UB)
    except ValueError:
        return None


def esc(text) -> str:
    return (
        str(text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def team_of(match: dict, side: str) -> tuple[str, int]:
    """Багийн нэр ба зэрэглэлийг буцаана. Зэрэглэлгүй бол 999."""
    node = match.get(side) or {}
    name = node.get("name") or side
    rank = node.get("rank")
    return name, (rank if isinstance(rank, int) and rank > 0 else 999)


def is_tier1(match: dict) -> bool:
    """S зэрэглэлийн тэмцээн, эсвэл top-N багтай тоглолт."""
    if match.get("tier") == "s":
        return True
    _, r1 = team_of(match, "team1")
    _, r2 = team_of(match, "team2")
    return min(r1, r2) <= MAX_RANK


def stage_of(match: dict) -> str:
    """Шатны нэрийг тэмцээний нэрээр давхардуулахгүйгээр буцаана."""
    stage = (match.get("stage") or {}).get("title") or ""
    tournament = (match.get("tournament") or {}).get("name") or ""
    if tournament and stage.startswith(tournament):
        stage = stage[len(tournament):].strip(" -–—:")
    return stage


def bo_label(match: dict) -> str:
    bo = match.get("bo_type")
    return f"bo{bo}" if isinstance(bo, int) and bo > 0 else ""


# ---------------------------------------------------------------- цуглуулах

def collect_results(since: datetime) -> list[dict]:
    out = []
    for m in api_get("finished", "-start_date"):
        when = parse_dt(m.get("end_date")) or parse_dt(m.get("start_date"))
        if when is None or when < since:
            continue
        if not is_tier1(m):
            continue
        t1, _ = team_of(m, "team1")
        t2, _ = team_of(m, "team2")
        out.append(
            {
                "time": when,
                "t1": t1,
                "t2": t2,
                "s1": m.get("team1_score", 0),
                "s2": m.get("team2_score", 0),
                "winner": m.get("winner_team_id"),
                "id1": m.get("team1_id"),
                "tournament": (m.get("tournament") or {}).get("name", ""),
                "stage": stage_of(m),
                "bo": bo_label(m),
                "url": SITE + m["slug"] if m.get("slug") else "",
            }
        )
    out.sort(key=lambda x: x["time"], reverse=True)
    return out


def collect_upcoming(now: datetime, until: datetime) -> list[dict]:
    out = []
    for m in api_get("upcoming,current", "start_date"):
        when = parse_dt(m.get("start_date"))
        if when is None or when > until:
            continue
        if when < now - timedelta(hours=4):
            continue
        if not is_tier1(m):
            continue
        t1, r1 = team_of(m, "team1")
        t2, r2 = team_of(m, "team2")
        out.append(
            {
                "time": when,
                "t1": t1,
                "t2": t2,
                "r1": r1,
                "r2": r2,
                "tournament": (m.get("tournament") or {}).get("name", ""),
                "stage": stage_of(m),
                "bo": bo_label(m),
                "live": m.get("status") == "current" or when <= now,
                "url": SITE + m["slug"] if m.get("slug") else "",
            }
        )
    out.sort(key=lambda x: x["time"])
    return out


# ---------------------------------------------------------------- мессеж

def link(url: str, label: str) -> str:
    return f'<a href="{url}">{label}</a>' if url else label


def build_message(results: list[dict], upcoming: list[dict], now: datetime) -> str:
    L: list[str] = []
    L.append("<b>CS2 TIER-1 ДАЙДЖЕСТ</b>")
    L.append(f"<i>{now.strftime('%Y.%m.%d %H:%M')} · УБ цагаар</i>")
    L.append("")

    L.append(f"<b>ҮР ДҮН · сүүлийн {RESULT_WINDOW_HOURS} цаг</b>")
    if results:
        for m in results:
            a = esc(m["t1"])
            b = esc(m["t2"])
            if m["winner"] == m["id1"]:
                a = f"<b>{a}</b>"
            elif m["winner"]:
                b = f"<b>{b}</b>"
            label = "{} {}–{} {}".format(a, m["s1"], m["s2"], b)
            L.append("{} · {}".format(m["time"].strftime("%H:%M"), link(m["url"], label)))
            meta = " · ".join(x for x in (m["tournament"], m["stage"], m["bo"]) if x)
            L.append(f"      <i>{esc(meta)}</i>")
    else:
        L.append("<i>Дууссан tier-1 тоглолт байхгүй.</i>")
    L.append("")

    L.append(f"<b>ХУВААРЬ · дараагийн {UPCOMING_HOURS} цаг</b>")
    if upcoming:
        day = None
        for m in upcoming:
            d = m["time"].strftime("%m.%d")
            if d != day:
                day = d
                L.append(f"<u>{d}</u>")
            mark = "🔴 LIVE" if m["live"] else m["time"].strftime("%H:%M")
            pair = link(m["url"], f"{esc(m['t1'])} vs {esc(m['t2'])}")
            L.append(f"{mark} · {pair}")
            meta = " · ".join(x for x in (m["tournament"], m["stage"], m["bo"]) if x)
            L.append(f"      <i>{esc(meta)}</i>")
    else:
        L.append("<i>Товлогдсон tier-1 тоглолт байхгүй.</i>")

    L.append("")
    L.append('<a href="https://bo3.gg/">bo3.gg</a>')
    return "\n".join(L)


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


def send(text: str) -> None:
    if DRY_RUN:
        print(text)
        return
    if not TG_TOKEN or not TG_CHAT:
        raise SystemExit("TELEGRAM_BOT_TOKEN болон TELEGRAM_CHAT_ID тохируулаагүй байна")

    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    for chunk in split_text(text):
        r = requests.post(
            url,
            data={
                "chat_id": TG_CHAT,
                "text": chunk,
                "parse_mode": "HTML",
                "disable_web_page_preview": "true",
            },
            timeout=30,
        )
        payload = r.json()
        if not payload.get("ok"):
            raise SystemExit(f"Telegram алдаа: {payload}")
        print(f"Илгээлээ ({len(chunk)} тэмдэгт)")
        time.sleep(1)


# ---------------------------------------------------------------- үндсэн

def main() -> int:
    now = datetime.now(UB)
    since = now - timedelta(hours=RESULT_WINDOW_HOURS)
    until = now + timedelta(hours=UPCOMING_HOURS)

    print(f"Ажиллаж эхэллээ: {now:%Y-%m-%d %H:%M} УБ")

    results = collect_results(since)
    print(f"Үр дүн: {len(results)}")

    upcoming = collect_upcoming(now, until)
    print(f"Хуваарь: {len(upcoming)}")

    send(build_message(results, upcoming, now))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"АЛДАА: {exc}", file=sys.stderr)
        sys.exit(1)
