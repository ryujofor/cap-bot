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

# 每个聊天窗口的 JSON 文件存储目录
CONTEXT_DIR = Path(__file__).parent / "contexts"
CONTEXT_DIR.mkdir(exist_ok=True)
CONTEXT_TTL = 600  # 10 分钟


def get_chat_id(event: MessageEvent) -> str:
    if event.message_type == "private":
        return f"private_{event.user_id}"
    return f"group_{event.group_id}"


def get_context_file(chat_id: str) -> Path:
    return CONTEXT_DIR / f"{chat_id}.json"


def load_context(chat_id: str) -> list[dict]:
    """加载上下文 JSON 文件，如果过期则返回空"""
    file = get_context_file(chat_id)
    if not file.exists():
        return []
    now = time.time()
    data = json.loads(file.read_text(encoding="utf-8"))
    if data.get("expires", 0) < now:
        # 过期则删除文件（下次自动创建新上下文）
        file.unlink(missing_ok=True)
        return []
    # 续期
    data["expires"] = now + CONTEXT_TTL
    file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data.get("messages", [])


def save_context(chat_id: str, messages: list[dict]):
    """保存上下文到 JSON 文件"""
    now = time.time()
    file = get_context_file(chat_id)
    data = {"chat_id": chat_id, "expires": now + CONTEXT_TTL, "messages": messages}
    file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


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


chat_handler = on_message(rule=is_chat_trigger(), priority=3)


@chat_handler.handle()
async def handle_chat(bot: Bot, event: MessageEvent, msg: Message = EventMessage()):
    chat_id = get_chat_id(event)
    user_text = extract_user_text(event)
    if not user_text:
        return

    messages = load_context(chat_id)
    messages.append({"role": "user", "content": user_text})

    url = f"{chat_api_base}/chat/completions"
    headers = {
        "Authorization": f"Bearer {chat_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "gpt-4o",
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            *messages,
        ],
        "temperature": 0.7,
        "stream": False,
    }

    assistant_text = ""
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            assistant_text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    except Exception as e:
        await chat_handler.finish(f"回复失败: {str(e)}")

    if assistant_text:
        messages.append({"role": "assistant", "content": assistant_text})
        save_context(chat_id, messages)
        await chat_handler.finish(assistant_text)
    else:
        await chat_handler.finish("AI 未返回有效回复")
