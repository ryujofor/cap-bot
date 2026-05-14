#!/usr/bin/env python3
"""
Fetch player scores from an osu! multiplayer room page.

Source page:
  https://osu.ppy.sh/multiplayer/rooms/{room_id}/events

The room event page embeds the full room state in an inline script, including
`users` and each `playlist_item.scores` entry. This script extracts that JSON
directly, so it does not require osu! API OAuth credentials.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from typing import Any


ROOM_URL_TEMPLATE = "https://osu.ppy.sh/multiplayer/rooms/{room_id}/events"
DEFAULT_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "User-Agent": "osu-room-score-fetcher/1.0",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract player scores from an osu! multiplayer room."
    )
    parser.add_argument(
        "room",
        nargs="?",
        default="2877544",
        help="Room ID or room/events URL. Default: 2877544",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print raw extracted score rows as JSON.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="HTTP timeout in seconds. Default: 20",
    )
    return parser.parse_args()


def extract_room_id(value: str) -> str:
    value = value.strip()
    if value.isdigit():
        return value

    match = re.search(r"/multiplayer/rooms/(\d+)", value)
    if match:
        return match.group(1)

    raise ValueError(f"Cannot extract room id from: {value}")


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


def fetch_room_page_state(room_id: str, timeout: float) -> dict[str, Any]:
    url = ROOM_URL_TEMPLATE.format(room_id=room_id)
    html = http_get_text(url, timeout=timeout)

    script_pattern = re.compile(r"<script[^>]*>(.*?)</script>", re.DOTALL | re.IGNORECASE)
    for match in script_pattern.finditer(html):
        raw_script = match.group(1).strip()
        if not raw_script.startswith("{"):
            continue
        if '"playlist_items"' not in raw_script or '"users"' not in raw_script:
            continue

        try:
            payload = json.loads(raw_script)
        except json.JSONDecodeError:
            continue

        if isinstance(payload, dict):
            return payload

    raise RuntimeError("Could not find embedded room JSON in page HTML.")


def walk_json(node: Any):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk_json(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk_json(item)


def maybe_get_username(node: dict[str, Any]) -> str | None:
    user = node.get("user")
    if isinstance(user, dict):
        username = user.get("username") or user.get("name")
        if isinstance(username, str) and username.strip():
            return username.strip()

    username = node.get("username") or node.get("name")
    if isinstance(username, str) and username.strip():
        return username.strip()

    return None


def maybe_get_user_id(node: dict[str, Any]) -> int | None:
    user = node.get("user")
    if isinstance(user, dict):
        value = user.get("id")
        if isinstance(value, int):
            return value

    value = node.get("user_id") or node.get("id")
    if isinstance(value, int):
        return value

    return None


def maybe_get_score(node: dict[str, Any]) -> int | None:
    for key in ("total_score", "score", "legacy_total_score"):
        value = node.get(key)
        if isinstance(value, int):
            return value
    return None


def looks_like_score_entry(node: dict[str, Any]) -> bool:
    user_id = maybe_get_user_id(node)
    score = maybe_get_score(node)
    if user_id is None or score is None:
        return False

    hints = {
        "accuracy",
        "max_combo",
        "rank",
        "passed",
        "statistics",
        "mods",
        "ended_at",
        "position",
        "playlist_item_id",
    }
    return any(key in node for key in hints) or "user" in node


def normalize_score_row(
    event: dict[str, Any],
    node: dict[str, Any],
    fallback_names: dict[int, str],
) -> dict[str, Any]:
    user_id = maybe_get_user_id(node)
    username = maybe_get_username(node) or fallback_names.get(user_id or -1)

    return {
        "event_id": event.get("id"),
        "event_type": event.get("type"),
        "created_at": event.get("created_at"),
        "user_id": user_id,
        "username": username,
        "playlist_item_id": node.get("playlist_item_id"),
        "position": node.get("position"),
        "score": node.get("score"),
        "total_score": node.get("total_score"),
        "legacy_total_score": node.get("legacy_total_score"),
        "accuracy": node.get("accuracy"),
        "max_combo": node.get("max_combo"),
        "passed": node.get("passed"),
        "rank": node.get("rank"),
        "ended_at": node.get("ended_at"),
    }


def extract_score_rows(
    events: list[dict[str, Any]],
    fallback_names: dict[int, str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()

    for event in events:
        for node in walk_json(event):
            if not looks_like_score_entry(node):
                continue

            row = normalize_score_row(event, node, fallback_names)
            dedupe_key = (
                row["event_id"],
                row["user_id"],
                row["playlist_item_id"],
                row["score"],
                row["total_score"],
                row["legacy_total_score"],
                row["ended_at"],
            )
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            rows.append(row)

    return rows


def normalize_user_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    for row in rows:
        normalized.append(
            {
                "user_id": row.get("id"),
                "username": row.get("username") or row.get("name"),
                "country_code": row.get("country_code"),
            }
        )
    return normalized


def build_name_index(user_rows: list[dict[str, Any]]) -> dict[int, str]:
    mapping: dict[int, str] = {}
    for row in normalize_user_rows(user_rows):
        user_id = row.get("user_id")
        username = row.get("username")
        if isinstance(user_id, int) and isinstance(username, str) and username.strip():
            mapping[user_id] = username.strip()
    return mapping


def extract_score_rows_from_page(
    payload: dict[str, Any],
    fallback_names: dict[int, str],
) -> list[dict[str, Any]]:
    room_events = payload.get("events")
    playlist_items = payload.get("playlist_items")

    event_index: dict[int, dict[str, Any]] = {}
    if isinstance(room_events, list):
        for event in room_events:
            if not isinstance(event, dict):
                continue
            if event.get("event_type") != "game_completed":
                continue
            playlist_item_id = event.get("playlist_item_id")
            if isinstance(playlist_item_id, int):
                event_index[playlist_item_id] = event

    rows: list[dict[str, Any]] = []
    if not isinstance(playlist_items, list):
        return rows

    for item in playlist_items:
        if not isinstance(item, dict):
            continue
        playlist_item_id = item.get("id")
        scores = item.get("scores")
        if not isinstance(scores, list):
            continue

        matched_event = (
            event_index.get(playlist_item_id) if isinstance(playlist_item_id, int) else None
        )
        for score in scores:
            if not isinstance(score, dict):
                continue
            row = {
                "event_id": matched_event.get("id") if matched_event else None,
                "event_type": matched_event.get("event_type") if matched_event else "game_completed",
                "created_at": matched_event.get("created_at") if matched_event else item.get("played_at"),
                "user_id": score.get("user_id"),
                "username": fallback_names.get(score.get("user_id")),
                "playlist_item_id": score.get("playlist_item_id", playlist_item_id),
                "position": score.get("position"),
                "score": score.get("score"),
                "total_score": score.get("total_score"),
                "legacy_total_score": score.get("legacy_total_score"),
                "accuracy": score.get("accuracy"),
                "max_combo": score.get("max_combo"),
                "passed": score.get("passed"),
                "rank": score.get("rank"),
                "ended_at": score.get("ended_at"),
                "beatmap_id": score.get("beatmap_id", item.get("beatmap_id")),
                "solo_score_id": score.get("solo_score_id") or score.get("id"),
            }
            rows.append(row)

    return rows


def get_score_rows(room: str, timeout: float = 20.0) -> list[dict[str, Any]]:
    room_id = extract_room_id(room)
    payload = fetch_room_page_state(room_id, timeout=timeout)
    user_rows = payload.get("users", [])
    fallback_names = build_name_index(user_rows if isinstance(user_rows, list) else [])
    return extract_score_rows_from_page(payload, fallback_names)


def format_score_message(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "没有找到玩家分数"

    grouped: dict[tuple[int | None, str | None], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row.get("user_id"), row.get("username"))].append(row)

    def sort_score(item: dict[str, Any]) -> int:
        for key in ("total_score", "score", "legacy_total_score"):
            value = item.get(key)
            if isinstance(value, int):
                return value
        return -1

    lines: list[str] = []
    for (_, username), items in sorted(
        grouped.items(),
        key=lambda pair: max(sort_score(item) for item in pair[1]),
        reverse=True,
    ):
        name = username or "未知玩家"
        scores = []
        for item in sorted(
            items,
            key=lambda row: (
                row.get("created_at") or "",
                row.get("ended_at") or "",
                sort_score(row),
            ),
        ):
            score = sort_score(item)
            rank = item.get("rank")
            if rank:
                scores.append(f"{score}({rank})")
            else:
                scores.append(str(score))
        lines.append(f"{name}: {' / '.join(scores)}")

    return "\n".join(lines)


def print_event_summary(rows: list[dict[str, Any]]) -> None:
    grouped: dict[tuple[int | None, str | None], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row.get("user_id"), row.get("username"))].append(row)

    def score_value(item: dict[str, Any]) -> int:
        for key in ("total_score", "score", "legacy_total_score"):
            value = item.get(key)
            if isinstance(value, int):
                return value
        return -1

    for (user_id, username), items in sorted(
        grouped.items(),
        key=lambda kv: max(score_value(item) for item in kv[1]),
        reverse=True,
    ):
        label = username or f"user_id={user_id}"
        print(f"{label} ({user_id})")
        for row in sorted(
            items,
            key=lambda item: (
                item.get("created_at") or "",
                item.get("ended_at") or "",
                score_value(item),
            ),
        ):
            score = row.get("total_score")
            if score is None:
                score = row.get("score")
            if score is None:
                score = row.get("legacy_total_score")

            parts = [f"score={score}"]
            if row.get("playlist_item_id") is not None:
                parts.append(f"playlist_item_id={row['playlist_item_id']}")
            if row.get("accuracy") is not None:
                parts.append(f"accuracy={row['accuracy']}")
            if row.get("max_combo") is not None:
                parts.append(f"max_combo={row['max_combo']}")
            if row.get("rank") is not None:
                parts.append(f"rank={row['rank']}")
            if row.get("ended_at") is not None:
                parts.append(f"ended_at={row['ended_at']}")
            if row.get("beatmap_id") is not None:
                parts.append(f"beatmap_id={row['beatmap_id']}")
            if row.get("event_type") is not None:
                parts.append(f"event_type={row['event_type']}")
            print("  - " + ", ".join(parts))
        print()


def main() -> int:
    args = parse_args()

    try:
        room_id = extract_room_id(args.room)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    try:
        score_rows = get_score_rows(room_id, timeout=args.timeout)

        if score_rows:
            if args.json:
                print(json.dumps(score_rows, ensure_ascii=False, indent=2))
            else:
                print_event_summary(score_rows)
            return 0

        print("No score rows were found in the room page.", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
