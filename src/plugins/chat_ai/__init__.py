import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

import json
import time

import httpx

from nonebot import on_message, get_driver
from nonebot.adapters import Message
from nonebot.adapters.onebot.v11 import Bot, MessageEvent
from nonebot.params import EventMessage
from nonebot.rule import Rule

driver = get_driver()
chat_api_key = str(getattr(driver.config, "chat_api_key", ""))
chat_api_base = str(getattr(driver.config, "chat_api_base", "https://api.jucode.cn/v1"))

# 上下文窗口: {chat_id: {"messages": [...], "expires": timestamp}}
context_windows: dict[str, dict] = {}
CONTEXT_TTL = 600  # 10 分钟


def get_chat_id(event: MessageEvent) -> str:
    if event.message_type == "private":
        return f"private_{event.user_id}"
    return f"group_{event.group_id}"


def is_chat_trigger() -> Rule:
    """私聊直接触发，群聊需要 @机器人"""
    async def _check(event: MessageEvent) -> bool:
        if event.message_type == "private":
            return True
        for seg in event.message:
            if seg.type == "at" and str(seg.data.get("qq", "")) == str(event.self_id):
                return True
        return False
    return Rule(_check)


def extract_user_text(event: MessageEvent) -> str:
    """提取用户文本，群聊中自动去除 @bot"""
    text_parts = []
    for seg in event.message:
        if seg.type == "text":
            text = seg.data.get("text", "").strip()
            if text:
                text_parts.append(text)
    return " ".join(text_parts)


def get_or_create_context(chat_id: str) -> list[dict]:
    now = time.time()
    ctx = context_windows.get(chat_id)
    if ctx and ctx["expires"] > now:
        ctx["expires"] = now + CONTEXT_TTL
        return ctx["messages"]
    context_windows[chat_id] = {"messages": [], "expires": now + CONTEXT_TTL}
    return context_windows[chat_id]["messages"]


chat_handler = on_message(rule=is_chat_trigger(), priority=9)


@chat_handler.handle()
async def handle_chat(bot: Bot, event: MessageEvent, msg: Message = EventMessage()):
    chat_id = get_chat_id(event)
    user_text = extract_user_text(event)
    if not user_text:
        return

    messages = get_or_create_context(chat_id)
    messages.append({"role": "user", "content": user_text})

    url = f"{chat_api_base}/chat/completions"
    headers = {
        "Authorization": f"Bearer {chat_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "gpt-4o",
        "messages": messages,
        "stream": True,
    }

    assistant_text = ""
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    chunk = json.loads(data)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        assistant_text += content
    except Exception as e:
        await chat_handler.finish(f"回复失败: {str(e)}")

    if assistant_text:
        messages.append({"role": "assistant", "content": assistant_text})
        await chat_handler.finish(assistant_text)
    else:
        await chat_handler.finish("AI 未返回有效回复")
