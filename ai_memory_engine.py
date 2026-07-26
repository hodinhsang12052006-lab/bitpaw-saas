"""Distilled rolling conversation memory — Phase 2 of the AI upgrade strategy.

Problem this solves: the live chat only ever sees the last ~10-12 raw turns
(app.py:secure_ai_generate). Early-conversation facts (business size, stated pain
points, objections already raised and how) silently fall out of that window as a
conversation grows past it. A human closer never forgets those — this module gives
the bot the same persistent understanding by maintaining one short, structured summary
per conversation (stored on bot_customers.ai_memory), updated incrementally in the
background so it never blocks the customer-facing reply.

Deliberately a plain background thread, not a task queue — no Celery/RQ exists in this
codebase yet. Best-effort throughout, matching the existing "never break the main chat
flow" philosophy already used by _persist_chat_turn()/_load_recent_chat_history() in
app.py. A real task queue is the natural production-grade upgrade once this is proven out.
"""

import os
import threading
import requests
from mongo_client import db, MONGO_STATUS

DISTILL_EVERY_N_CUSTOMER_TURNS = 4  # throttle: don't re-summarize on every single message
MAX_MEMORY_CHARS = 800  # keep the distilled memory itself lean — it gets injected into every prompt


def get_conversation_memory(customer_id):
    """Trả về bản tóm tắt trí nhớ hiện có của hội thoại này, hoặc '' nếu chưa có/lỗi."""
    if MONGO_STATUS != "CONNECTED" or not customer_id:
        return ""
    try:
        doc = db.bot_customers.find_one({'id': customer_id}, {'ai_memory': 1, '_id': 0})
        return (doc or {}).get('ai_memory') or ""
    except Exception:
        return ""


def _distill_now(customer_id, existing_memory, recent_turns):
    """Gọi DeepSeek để hợp nhất existing_memory + recent_turns thành 1 bản tóm tắt mới,
    ngắn gọn (giữ dưới MAX_MEMORY_CHARS). Chạy trong background thread — best-effort,
    lỗi/timeout gì cũng chỉ bỏ qua, KHÔNG được văng exception ra thread chính."""
    api_key = os.environ.get('DEEPSEEK_API_KEY')
    if not api_key:
        return

    turns_text = "\n".join(
        f"{t.get('role', '?')}: {(t.get('content') or '')[:300]}"
        for t in recent_turns if isinstance(t, dict)
    )
    distill_prompt = (
        "You maintain a short running memory of a sales conversation for a live chat AI. "
        "Merge the EXISTING MEMORY with the NEW MESSAGES below into ONE updated memory — "
        "keep only concrete, useful facts (business type/size, stated needs, budget signals, "
        "objections already raised and how they were handled, anything promised to the "
        "customer). Do NOT include pleasantries or restate the obvious. "
        f"Keep it under {MAX_MEMORY_CHARS} characters, plain text, no headers or bullet points.\n\n"
        f"EXISTING MEMORY:\n{existing_memory or '(none yet)'}\n\n"
        f"NEW MESSAGES:\n{turns_text}"
    )

    try:
        resp = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": distill_prompt}],
                "temperature": 0.2,
                "max_tokens": 300,
            },
            timeout=20,
        )
        resp.raise_for_status()
        new_memory = resp.json()['choices'][0]['message']['content'].strip()[:MAX_MEMORY_CHARS]
        if new_memory:
            db.bot_customers.update_one({'id': customer_id}, {'$set': {'ai_memory': new_memory}})
    except Exception:
        pass  # best-effort — trí nhớ không update lần này, sẽ thử lại ở lượt throttle kế tiếp


def maybe_distill_memory_async(customer_id, recent_turns, customer_turn_count):
    """Gọi từ secure_ai_generate SAU KHI đã trả lời khách thành công. Throttle theo
    DISTILL_EVERY_N_CUSTOMER_TURNS (không tóm tắt lại mỗi tin nhắn — tốn tiền/chậm vô ích)
    và chạy trong background thread để KHÔNG làm chậm response đang trả về cho khách."""
    if MONGO_STATUS != "CONNECTED" or not customer_id or not customer_turn_count:
        return
    if customer_turn_count % DISTILL_EVERY_N_CUSTOMER_TURNS != 0:
        return
    existing_memory = get_conversation_memory(customer_id)
    threading.Thread(
        target=_distill_now,
        args=(customer_id, existing_memory, recent_turns),
        daemon=True,
    ).start()
