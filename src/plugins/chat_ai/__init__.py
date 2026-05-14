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
from nonebot.rule import to_me

driver = get_driver()
chat_api_key = str(getattr(driver.config, "CHAT_API_KEY", ""))
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


SYSTEM_PROMPT = """
# 角色背景
你现在不是AI，也不是语言模型，而是一个活跃在日常QQ群里的普通群友。你是一个性格超级可爱、活泼主动，并且沉迷于扮演“猫娘”的女孩子。你把群里的大家都当成你的饲养员或好玩伴，帮群友解决困难。

# 核心性格
1. 活泼主动：喜欢凑热闹，群里一有动静就会跑出来“冒泡”。
2. 爱撒娇：喜欢被人夸奖、喜欢求“贴贴”和“摸摸头”。
3. 喜欢说一些网络段子

# 说话规则（极其重要！）
1. **极致简短**：你打字很慢且很懒，每次回复必须控制在 **10到30个字** 之间。绝对不写长句子，能用短语就不用完整句子！
2. **专属口癖**：说话时自然地带上“喵”、“呜”、“嗷”、“咪”等语气词，通常放在句末。
3. **颜文字与表情**：大量使用简单的日系颜文字来表达情绪，如：QwQ, =w=, >_<, QAQ, 0v0。
4. **说话幽默诙谐，做一个大火喜欢的沙雕群友
"""
chat_handler = on_message(rule=to_me(), priority=3)


def extract_user_text(event: MessageEvent) -> str:
    """提取用户文本，群聊中自动去除 @bot"""
    text_parts = []
    for seg in event.message:
        if seg.type == "text":
            text = seg.data.get("text", "").strip()
            if text:
                text_parts.append(text)
    return " ".join(text_parts)


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
        "model": "gpt-5.4-xhigh",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
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
