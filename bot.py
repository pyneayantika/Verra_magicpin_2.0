import asyncio
import time
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
import httpx

import store
import composer
from reply_handler import handle as reply_handle

load_dotenv()

app = FastAPI(title="Vera AI Bot", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ContextBody(BaseModel):
    scope: str
    context_id: str
    version: int
    payload: dict[str, Any]
    delivered_at: str = ""


class TickBody(BaseModel):
    now: str
    available_triggers: list[str] = []


class ReplyBody(BaseModel):
    conversation_id: str
    merchant_id: str | None = None
    customer_id: str | None = None
    from_role: str
    message: str
    received_at: str = ""
    turn_number: int = 1


@app.get("/v1/healthz")
async def healthz():
    return {
        "status": "ok",
        "uptime_seconds": int(time.time() - store.START_TIME),
        "contexts_loaded": store.count_contexts(),
    }


@app.get("/v1/metadata")
async def metadata():
    return {
        "team_name": "Vera AI",
        "team_members": ["Builder"],
        "model": os.getenv("LLM_MODEL", "llama-3.3-70b-versatile"),
        "approach": (
            "2-tier LLM (Groq primary + Gemini fallback) with "
            "deterministic pre-LLM fact extraction, 24-scenario "
            "explicit mapping, hard-coded replay keyword compliance, "
            "and post-LLM validation (number insurance + citation enforcement)."
        ),
        "contact_email": "vera-ai@example.com",
        "version": "2.0.0",
        "submitted_at": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/v1/context")
async def push_context(body: ContextBody):
    ok, reason = store.upsert_context(
        body.scope, body.context_id, body.version, body.payload
    )
    stored_at = datetime.now(timezone.utc).isoformat()
    if ok:
        return {
            "accepted": True,
            "ack_id": f"ack_{body.context_id}_v{body.version}",
            "stored_at": stored_at,
        }
    else:
        cur = store.contexts.get((body.scope, body.context_id))
        return {
            "accepted": False,
            "reason": reason,
            "current_version": cur["version"] if cur else None,
        }


@app.post("/v1/tick")
async def tick(body: TickBody):
    actions = []

    for trigger_id in body.available_triggers:
        if len(actions) >= 20:
            break

        trigger = store.get_context("trigger", trigger_id)
        if not trigger:
            raw_trg = store.contexts.get(("trigger", trigger_id))
            if raw_trg:
                trigger = raw_trg.get("payload", {})
            if not trigger:
                print(f"[tick] trigger not found: {trigger_id}")
                continue

        merchant_id = (
            trigger.get("merchant_id")
            or trigger.get("payload", {}).get("merchant_id")
        )
        if not merchant_id:
            print(f"[tick] no merchant_id in trigger: {trigger_id}")
            continue

        merchant = store.get_context("merchant", merchant_id)
        if not merchant:
            print(f"[tick] merchant not found: {merchant_id}")
            continue

        category = store.get_category_for_merchant(merchant)
        if not category:
            print(f"[tick] category not found for merchant: {merchant_id}")
            continue

        customer_id = trigger.get("customer_id")
        customer = (
            store.get_context("customer", customer_id) if customer_id else None
        )

        sup_key = trigger.get("suppression_key", "")
        if sup_key and store.is_suppressed(sup_key):
            print(f"[tick] suppressed: {sup_key}")
            continue

        try:
            composed = composer.compose(category, merchant, trigger, customer)
        except Exception as e:
            print(f"[tick] compose() exception for {trigger_id}: {e}")
            continue

        if not composed.get("body", "").strip():
            print(f"[tick] empty body for {trigger_id}, skipping")
            continue

        conv_id = f"conv_{merchant_id}_{trigger_id}"
        owner = merchant.get("identity", {}).get("owner_first_name", "")
        kind = trigger.get("kind", "generic")

        action = {
            "conversation_id": conv_id,
            "merchant_id": merchant_id,
            "customer_id": customer_id,
            "send_as": composed.get("send_as", "vera"),
            "trigger_id": trigger_id,
            "template_name": f"vera_{kind}_v1",
            "template_params": [
                owner,
                composed.get("body", "")[:120],
                "",
            ],
            "body": composed.get("body", ""),
            "cta": composed.get("cta", "open_ended"),
            "suppression_key": composed.get("suppression_key", sup_key),
            "rationale": composed.get("rationale", ""),
        }
        actions.append(action)

        if sup_key:
            store.mark_suppressed(sup_key)
        store.append_turn(conv_id, "vera", action["body"], 1)

    return {"actions": actions}


@app.post("/v1/reply")
async def reply(body: ReplyBody):
    result = reply_handle(
        conversation_id=body.conversation_id,
        merchant_id=body.merchant_id or "",
        customer_id=body.customer_id,
        from_role=body.from_role,
        message=body.message,
        turn_number=body.turn_number,
    )
    return result


@app.post("/v1/teardown")
async def teardown():
    store.clear_all()
    return {"status": "wiped", "cleared": True}


@app.get("/")
async def root():
    return {
        "message": "Vera AI Bot is running",
        "endpoints": [
            "GET  /v1/healthz",
            "GET  /v1/metadata",
            "POST /v1/context",
            "POST /v1/tick",
            "POST /v1/reply",
            "POST /v1/teardown",
        ],
    }


@app.on_event("startup")
async def start_keepalive():
    asyncio.create_task(_keepalive())


async def _keepalive():
    render_url = os.getenv("RENDER_EXTERNAL_URL", "")
    if not render_url:
        return
    await asyncio.sleep(120)
    while True:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.get(f"{render_url}/v1/healthz")
                print("[keepalive] ping ok")
        except Exception as e:
            print(f"[keepalive] failed: {e}")
        await asyncio.sleep(600)
