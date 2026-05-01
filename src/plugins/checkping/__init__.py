from nonebot import on_message
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.rule import Rule


def is_private_keyword(keyword: str) -> Rule:
    async def _check(event: MessageEvent) -> bool:
        return event.message_type == "private" and str(event.message).strip() == keyword

    return Rule(_check)


check_ping = on_message(rule=is_private_keyword("测试"), priority=1)


@check_ping.handle()
async def handle_check_ping():
    await check_ping.finish("我在")
