import time

START_TIME: float = time.time()

contexts: dict[tuple[str, str], dict] = {}
conversations: dict[str, list] = {}
suppressed: set[str] = set()
auto_reply_counts: dict[str, int] = {}


def upsert_context(scope: str, context_id: str, version: int,
                   payload: dict) -> tuple[bool, str]:
    key = (scope, context_id)
    current = contexts.get(key)

    if current is None:
        contexts[key] = {"version": version, "payload": payload}
        return (True, "stored")

    if current["version"] == version:
        return (True, "no_op")

    if current["version"] > version:
        return (False, "stale_version")

    contexts[key] = {"version": version, "payload": payload}
    return (True, "stored")


def get_context(scope: str, context_id: str) -> dict | None:
    entry = contexts.get((scope, context_id))
    return entry["payload"] if entry else None


def get_category_for_merchant(merchant_payload: dict) -> dict | None:
    if not merchant_payload:
        return None
    slug = merchant_payload.get("category_slug")
    if not slug:
        return None
    return get_context("category", slug)


def count_contexts() -> dict:
    counts = {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}
    for (scope, _) in contexts.keys():
        if scope in counts:
            counts[scope] += 1
    return counts


def is_suppressed(key: str) -> bool:
    return key in suppressed


def mark_suppressed(key: str) -> None:
    if key:
        suppressed.add(key)


def append_turn(conv_id: str, from_role: str, body: str,
                turn_number: int) -> None:
    if conv_id not in conversations:
        conversations[conv_id] = []
    conversations[conv_id].append({
        "from": from_role,
        "body": body,
        "turn": turn_number
    })


def get_turns(conv_id: str) -> list:
    return conversations.get(conv_id, [])


def clear_all() -> None:
    contexts.clear()
    conversations.clear()
    suppressed.clear()
    auto_reply_counts.clear()
