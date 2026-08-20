#!/usr/bin/env python3
"""
HLTV Tier-1 (HLTV top-20 багууд) дайджест -> Telegram суваг.

12 цаг тутам ажиллана:
  - сүүлийн 12 цагт дууссан тоглолтын үр дүн
  - дараагийн 24 цагт болох тоглолтын хуваарь
  - тоглолт бүрийн шат (Quarterfinal, Playoffs гэх мэт)

Орчны хувьсагч (environment variables):
  TELEGRAM_BOT_TOKEN   BotFather-аас авсан токен
  TELEGRAM_CHAT_ID     @сувгийн_нэр эсвэл -100... хэлбэрийн ID
  RESULT_WINDOW_HOURS  (сонголт, анхдагч 12)
  UPCOMING_HOURS       (сонголт, анхдагч 24)
  DRY_RUN              1 бол Telegram руу илгээхгүй, зөвхөн хэвлэнэ
"""

from __future__ import annotations

import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------- тохиргоо

BASE = "https://www.hltv.org"
UB = timezone(timedelta(hours=8))  # Asia/Ulaanbaatar

RESULT_WINDOW_HOURS = int(os.environ.get("RESULT_WINDOW_HOURS", "12"))
UPCOMING_HOURS = int(os.environ.get("UPCOMING_HOURS", "24"))
DRY_RUN = os.environ.get("DRY_RUN") == "1"

TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


# ---------------------------------------------------------------- туслахууд

def fetch(path: str, attempts: int = 4) -> BeautifulSoup:
    """HLTV хуудсыг татаж BeautifulSoup болгож буцаана."""
    url = path if path.startswith("http") else BASE + path
    last = None
    for i in range(attempts):
        try:
            r = SESSION.get(url, timeout=30)
            if r.status_code == 200:
                return BeautifulSoup(r.text, "html.parser")
            last = f"HTTP {r.status_code}"
        except requests.RequestException as exc:  # сүлжээний алдаа
            last = str(exc)
        time.sleep(3 * (i + 1))
    raise RuntimeError(f"{url} татаж чадсангүй: {last}")


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def esc(text: str) -> str:
    """Telegram HTML parse_mode-д зориулсан escape."""
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def unix_to_ub(ms) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).astimezone(UB)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- top-20

def top_teams(limit: int = 20) -> set[str]:
    """HLTV дэлхийн зэрэглэлийн эхний N багийн нэрийг авна."""
    soup = fetch("/ranking/teams")
    names: list[str] = []
    for box in soup.select(".ranked-team"):
        node = box.select_one(".ranking-header .name") or box.select_one(".name")
        if node:
            name = clean(node.get_text())
            if name and name not in names:
                names.append(name)
        if len(names) >= limit:
            break
    if not names:
        raise RuntimeError("Зэрэглэлийн хуудаснаас баг олдсонгүй — HLTV бүтэц өөрчлөгдсөн байж магадгүй")
    return {n.lower() for n in names}


def is_tier1(team_a: str, team_b: str, teams: set[str]) -> bool:
    a, b = team_a.lower(), team_b.lower()
    return a in teams or b in teams


# ---------------------------------------------------------------- үр дүн

def recent_results(teams: set[str], since: datetime) -> list[dict]:
    soup = fetch("/results")
    out: list[dict] = []

    for con in soup.select(".result-con"):
        when = unix_to_ub(con.get("data-zonedgrouping-entry-unix"))
        if when is None or when < since:
            continue

        cells = con.select(".team-cell .team")
        if len(cells) < 2:
            continue
        t1, t2 = clean(cells[0].get_text()), clean(cells[1].get_text())
        if not is_tier1(t1, t2, teams):
            continue

        score_node = con.select_one(".result-score")
        score = clean(score_node.get_text()).replace(" ", "") if score_node else "?"

        event_node = con.select_one(".event-name")
        event = clean(event_node.get_text()) if event_node else ""

        fmt_node = con.select_one(".map-text")
        fmt = clean(fmt_node.get_text()) if fmt_node else ""

        link = con.select_one("a[href]")
        url = BASE + link["href"] if link else ""

        won_left = bool(con.select_one(".team-cell .team-won"))
        out.append(
            {
                "time": when,
                "t1": t1,
                "t2": t2,
                "score": score,
                "event": event,
                "fmt": fmt,
                "url": url,
                "won_left": won_left,
            }
        )

    out.sort(key=lambda m: m["time"], reverse=True)
    return out


# ---------------------------------------------------------------- хуваарь

def upcoming_matches(teams: set[str], until: datetime, now: datetime) -> list[dict]:
    soup = fetch("/matches")
    out: list[dict] = []

    for box in soup.select(".upcomingMatch"):
        time_node = box.select_one(".matchTime")
        when = unix_to_ub(time_node.get("data-unix")) if time_node else None
        if when is None or when > until or when < now - timedelta(hours=3):
            continue

        names = [clean(n.get_text()) for n in box.select(".matchTeamName")]
        if len(names) < 2:
            continue  # TBD эсвэл placeholder тоглолт
        t1, t2 = names[0], names[1]
        if not is_tier1(t1, t2, teams):
            continue

        event_node = box.select_one(".matchEventName") or box.select_one(".matchEvent")
        event = clean(event_node.get_text()) if event_node else ""

        stage_node = box.select_one(".matchMeta")
        fmt = clean(stage_node.get_text()) if stage_node else ""

        # Шатны нэр (Quarterfinal, Playoffs гэх мэт) event блокоос гардаг
        stage = ""
        info = box.select_one(".matchInfoEmpty, .matchEventName")
        parent_txt = clean(box.get_text(" "))
        for keyword in (
            "Grand Final", "Final", "Semi-final", "Semifinal",
            "Quarter-final", "Quarterfinal", "Playoffs",
            "Round of 16", "Group", "Swiss", "Qualifier",
        ):
            if keyword.lower() in parent_txt.lower():
                stage = keyword
                break

        link = box.select_one("a[href]")
        url = BASE + link["href"] if link else ""

        out.append(
            {
                "time": when,
                "t1": t1,
                "t2": t2,
                "event": event,
                "fmt": fmt,
                "stage": stage,
                "url": url,
                "live": when <= now,
            }
        )

    out.sort(key=lambda m: m["time"])
    return out


# ---------------------------------------------------------------- мессеж

def build_message(results: list[dict], upcoming: list[dict], now: datetime) -> str:
    lines: list[str] = []
    lines.append(f"<b>CS2 TIER-1 ДАЙДЖЕСТ</b>")
    lines.append(f"<i>{now.strftime('%Y.%m.%d %H:%M')} (УБ цагаар)</i>")
    lines.append("")

    # --- үр дүн
    lines.append(f"<b>Сүүлийн {RESULT_WINDOW_HOURS} цагийн үр дүн</b>")
    if results:
        for m in results:
            left = f"<b>{esc(m['t1'])}</b>" if m["won_left"] else esc(m["t1"])
            right = esc(m["t2"]) if m["won_left"] else f"<b>{esc(m['t2'])}</b>"
            fmt = f" · {esc(m['fmt'])}" if m["fmt"] else ""
            head = f"{m['time'].strftime('%H:%M')}  {left} {m['score']} {right}"
            if m["url"]:
                head = f"{m['time'].strftime('%H:%M')}  <a href=\"{m['url']}\">{left} {m['score']} {right}</a>"
            lines.append(head)
            lines.append(f"      <i>{esc(m['event'])}{fmt}</i>")
    else:
        lines.append("<i>Top-20 багийн дууссан тоглолт байхгүй.</i>")
    lines.append("")

    # --- хуваарь
    lines.append(f"<b>Дараагийн {UPCOMING_HOURS} цагийн хуваарь</b>")
    if upcoming:
        current_day = None
        for m in upcoming:
            day = m["time"].strftime("%m.%d")
            if day != current_day:
                current_day = day
                lines.append(f"<u>{day}</u>")
            mark = "🔴 LIVE" if m["live"] else m["time"].strftime("%H:%M")
            stage = f" · {esc(m['stage'])}" if m["stage"] else ""
            fmt = f" · {esc(m['fmt'])}" if m["fmt"] else ""
            pair = f"{esc(m['t1'])} vs {esc(m['t2'])}"
            if m["url"]:
                pair = f"<a href=\"{m['url']}\">{pair}</a>"
            lines.append(f"{mark}  {pair}")
            lines.append(f"      <i>{esc(m['event'])}{stage}{fmt}</i>")
    else:
        lines.append("<i>Товлогдсон тоглолт байхгүй.</i>")

    lines.append("")
    lines.append('<a href="https://www.hltv.org/">hltv.org</a>')
    return "\n".join(lines)


# ---------------------------------------------------------------- Telegram

def send(text: str) -> None:
    """Telegram руу POST-оор илгээнэ. 4096 тэмдэгтээс урт бол хуваана."""
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


# ---------------------------------------------------------------- үндсэн

def main() -> int:
    now = datetime.now(UB)
    since = now - timedelta(hours=RESULT_WINDOW_HOURS)
    until = now + timedelta(hours=UPCOMING_HOURS)

    print(f"Ажиллаж эхэллээ: {now:%Y-%m-%d %H:%M} УБ")
    teams = top_teams(20)
    print(f"Top-20 баг: {len(teams)}")

    results = recent_results(teams, since)
    print(f"Үр дүн: {len(results)}")

    upcoming = upcoming_matches(teams, until, now)
    print(f"Хуваарь: {len(upcoming)}")

    send(build_message(results, upcoming, now))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"АЛДАА: {exc}", file=sys.stderr)
        sys.exit(1)
