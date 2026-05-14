import asyncio
import json
import re
import urllib.error
import urllib.request
from collections import defaultdict
from typing import Any

from nonebot import on_message
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.rule import Rule


MATCH_URL_TEMPLATE = "https://osu.ppy.sh/community/matches/{match_id}"
DEFAULT_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "User-Agent": "osu-match-score-fetcher/1.0",
}
USERNAME_PREFIX = "[SHK]"


def is_shk_match_command() -> Rule:
    async def _check(event: MessageEvent) -> bool:
        text = event.message.extract_plain_text().strip()
        return text.startswith("sm or SM")

    return Rule(_check)


shk_match_score = on_message(rule=is_shk_match_command(), priority=2)


def extract_match_id(value: str) -> str:
    text = value.strip()
    if text.isdigit():
        return text

    match = re.search(r"/community/matches/(\d+)", text)
    if match:
        return match.group(1)

    raise ValueError(f"Cannot extract match id from: {value}")


def http_get_text(url: str, timeout: float) -> str:
    request = urllib.request.Request(url, headers=DEFAULT_HEADERS, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} for {url}\n{body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Request failed for {url}: {exc}") from exc


def fetch_match_page_state(match_id: str, timeout: float = 20.0) -> dict[str, Any]:
    html = http_get_text(MATCH_URL_TEMPLATE.format(match_id=match_id), timeout=timeout)
    script_pattern = re.compile(r"<script[^>]*>(.*?)</script>", re.DOTALL | re.IGNORECASE)

    for match in script_pattern.finditer(html):
        raw_script = match.group(1).strip()
        if not raw_script.startswith("{"):
            continue
        if '"events"' not in raw_script or '"users"' not in raw_script:
            continue

        try:
            payload = json.loads(raw_script)
        except json.JSONDecodeError:
            continue

        if isinstance(payload, dict):
            return payload

    raise RuntimeError("Could not find embedded match JSON in page HTML.")


def build_user_index(payload: dict[str, Any]) -> dict[int, str]:
    users = payload.get("users", [])
    mapping: dict[int, str] = {}

    if not isinstance(users, list):
        return mapping

    for user in users:
        if not isinstance(user, dict):
            continue
        user_id = user.get("id")
        username = user.get("username")
        if isinstance(user_id, int) and isinstance(username, str) and username:
            mapping[user_id] = username

    return mapping


def get_shk_match_rows(match_value: str, timeout: float = 20.0) -> list[dict[str, Any]]:
    match_id = extract_match_id(match_value)
    payload = fetch_match_page_state(match_id, timeout=timeout)
    user_index = build_user_index(payload)
    events = payload.get("events", [])
    rows: list[dict[str, Any]] = []

    if not isinstance(events, list):
        return rows

    for event in events:
        if not isinstance(event, dict):
            continue
        game = event.get("game")
        if not isinstance(game, dict):
            continue
        scores = game.get("scores")
        if not isinstance(scores, list):
            continue

        beatmap = game.get("beatmap")
        version = None
        if isinstance(beatmap, dict):
            version = beatmap.get("version")

        for score in scores:
            if not isinstance(score, dict):
                continue
            user_id = score.get("user_id")
            username = user_index.get(user_id)
            if not username or not username.startswith(USERNAME_PREFIX):
                continue

            rows.append(
                {
                    "username": username,
                    "user_id": user_id,
                    "game_id": game.get("id"),
                    "beatmap_id": score.get("beatmap_id", game.get("beatmap_id")),
                    "beatmap_version": version,
                    "ended_at": score.get("ended_at", game.get("end_time")),
                    "total_score": score.get("total_score"),
                    "legacy_total_score": score.get("legacy_total_score"),
                    "accuracy": score.get("accuracy"),
                    "max_combo": score.get("max_combo"),
                    "rank": score.get("rank"),
                    "passed": score.get("passed"),
                    "mods": score.get("mods", game.get("mods", [])),
                }
            )

    return rows


def format_mods(mods: Any) -> str:
    if not isinstance(mods, list) or not mods:
        return ""

    names: list[str] = []
    for mod in mods:
        if isinstance(mod, dict):
            acronym = mod.get("acronym")
            if isinstance(acronym, str) and acronym:
                names.append(acronym)
        elif isinstance(mod, str) and mod:
            names.append(mod)

    return "+".join(names)


def format_shk_match_message(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "No [SHK]-prefixed player scores found"

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["username"]].append(row)

    lines: list[str] = []
    for username in sorted(grouped):
        lines.append(f"{username}:")
        for item in sorted(
            grouped[username],
            key=lambda row: (row.get("ended_at") or "", str(row.get("game_id") or "")),
        ):
            score = item.get("total_score")
            if score is None:
                score = item.get("legacy_total_score")

            rank = item.get("rank") or "?"
            beatmap = item.get("beatmap_version") or f"beatmap {item.get('beatmap_id')}"
            mod_text = format_mods(item.get("mods"))
            if mod_text:
                lines.append(f"{beatmap}: {score}({rank}) [{mod_text}]")
            else:
                lines.append(f"{beatmap}: {score}({rank})")

    return "\n".join(lines)


@shk_match_score.handle()
async def handle_shk_match_score(event: MessageEvent) -> None:
    text = event.message.extract_plain_text().strip()
    match_value = text[len("sm"):].strip()

    if not match_value:
        await shk_match_score.finish("Usage: sm <match url or match id>")

    try:
        rows = await asyncio.to_thread(get_shk_match_rows, match_value)
    except ValueError:
        await shk_match_score.finish("Invalid match url or match id")
    except RuntimeError as exc:
        await shk_match_score.finish(f"Failed to fetch scores: {exc}")

    await shk_match_score.finish(format_shk_match_message(rows))
