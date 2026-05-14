import asyncio

from nonebot import on_message
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.rule import Rule

from .osu_room_scores import format_score_message, get_score_rows


def is_raise_command() -> Rule:
    async def _check(event: MessageEvent) -> bool:
        text = event.message.extract_plain_text().strip()
        return text.startswith("raise")

    return Rule(_check)


raise_score = on_message(rule=is_raise_command(), priority=2)


@raise_score.handle()
async def handle_raise_score(event: MessageEvent) -> None:
    text = event.message.extract_plain_text().strip()
    room = text[5:].strip()

    if not room:
        await raise_score.finish("用法: raise 房间链接或房间ID")

    try:
        rows = await asyncio.to_thread(get_score_rows, room)
    except ValueError:
        await raise_score.finish("房间链接或房间ID不正确")
    except RuntimeError as exc:
        await raise_score.finish(f"获取分数失败: {exc}")

    if not rows:
        await raise_score.finish("没有找到玩家分数")

    await raise_score.finish(format_score_message(rows))
