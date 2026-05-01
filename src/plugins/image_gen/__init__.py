import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

import base64
import httpx

from nonebot import on_message, get_driver
from nonebot.adapters import Message
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, MessageSegment
from nonebot.params import EventMessage
from nonebot.rule import Rule

from gen_image import create_image, edit_image

driver = get_driver()
image_api_key = str(getattr(driver.config, "image_api_key", ""))


# --- i2 图片生成：私聊或群聊以 "i2" 开头的消息 ---
def is_i2_trigger() -> Rule:
    async def _check(event: MessageEvent) -> bool:
        text = event.message.extract_plain_text().strip()
        return text.startswith("i2")
    return Rule(_check)


i2_handler = on_message(rule=is_i2_trigger(), priority=10)


@i2_handler.handle()
async def handle_i2_gen(bot: Bot, event: MessageEvent, msg: Message = EventMessage()):
    text_parts = []
    for seg in msg:
        if seg.type == "text":
            text_parts.append(seg.data.get("text", "").strip())

    prompt = " ".join(filter(None, text_parts))
    if prompt.startswith("i2"):
        prompt = prompt[2:].strip()
    if not prompt:
        await i2_handler.finish("请输入图片描述，例如：i2 一只可爱的猫")

    await i2_handler.send("正在生成图片，请稍候...")

    try:
        result = create_image(prompt, image_api_key)
        b64_json = result["data"][0]["b64_json"]
        image_bytes = base64.b64decode(b64_json)
        await i2_handler.finish(MessageSegment.image(image_bytes))
    except Exception as e:
        await i2_handler.finish(f"图片生成失败: {str(e)}")


# --- ie 图片编辑：仅私聊以 "ie" 开头，需附带图片 ---
def is_ie_private() -> Rule:
    async def _check(event: MessageEvent) -> bool:
        if event.message_type != "private":
            return False
        text = event.message.extract_plain_text().strip()
        return text.startswith("ie")
    return Rule(_check)


ie_handler = on_message(rule=is_ie_private(), priority=10)


@ie_handler.handle()
async def handle_ie_edit(bot: Bot, event: MessageEvent, msg: Message = EventMessage()):
    # 提取图片和文本
    image_url = None
    text_parts = []
    for seg in msg:
        if seg.type == "image":
            image_url = seg.data.get("url", "") or seg.data.get("file", "")
        elif seg.type == "text":
            text_parts.append(seg.data.get("text", "").strip())

    prompt = " ".join(filter(None, text_parts))
    if prompt.startswith("ie"):
        prompt = prompt[2:].strip()

    if not image_url:
        await ie_handler.finish("请发送图片并输入编辑描述，例如：ie 把背景换成星空")
    if not prompt:
        await ie_handler.finish("请输入编辑描述，例如：ie 把背景换成星空")

    await ie_handler.send("正在编辑图片，请稍候...")

    try:
        # 下载图片
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(image_url)
            resp.raise_for_status()
            image_bytes = resp.content

        result = edit_image(image_bytes, prompt, image_api_key)
        b64_json = result["data"][0]["b64_json"]
        edited_bytes = base64.b64decode(b64_json)
        await ie_handler.finish(MessageSegment.image(edited_bytes))
    except Exception as e:
        await ie_handler.finish(f"图片编辑失败: {str(e)}")
