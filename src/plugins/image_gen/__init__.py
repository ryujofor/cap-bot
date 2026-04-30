import sys
from pathlib import Path

# 添加项目根目录到 sys.path 以便导入 gen_image
sys.path.insert(0, str(Path(__file__).parents[2]))

import base64

from nonebot import on_message, get_driver
from nonebot.adapters import Message
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, MessageSegment
from nonebot.params import EventMessage
from nonebot.rule import Rule

from gen_image import create_image

driver = get_driver()
image_api_key = str(getattr(driver.config, "image_api_key", ""))


# 仅私聊且消息以 "i2" 开头时触发
def is_private_i2() -> Rule:
    async def _check(event: MessageEvent) -> bool:
        if event.message_type != "private":
            return False
        text = event.message.extract_plain_text().strip()
        return text.startswith("i2")
    return Rule(_check)


image_gen = on_message(rule=is_private_i2(), priority=10)


@image_gen.handle()
async def handle_image_gen(bot: Bot, event: MessageEvent, msg: Message = EventMessage()):
    # 提取 @bot 之后的文本内容
    text_parts = []
    for seg in msg:
        if seg.type == "text":
            text_parts.append(seg.data.get("text", "").strip())

    prompt = " ".join(filter(None, text_parts))
    if prompt.startswith("i2"):
        prompt = prompt[2:].strip()
    if not prompt:
        await image_gen.finish("请输入图片描述，例如：i2 一只可爱的猫")

    await image_gen.send("正在生成图片，请稍候...")

    try:
        result = create_image(prompt, image_api_key)
        b64_json = result["data"][0]["b64_json"]
        image_bytes = base64.b64decode(b64_json)
        await image_gen.finish(MessageSegment.image(image_bytes))
    except Exception as e:
        await image_gen.finish(f"图片生成失败: {str(e)}")
