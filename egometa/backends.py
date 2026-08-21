"""VLM backends: gemini + claude. label_frames(frames, ctx) -> dict."""
import asyncio
import base64
import json
import os
import re
from typing import Dict, List

from .util import get_logger

log = get_logger()

GEMINI_MODEL = "gemini-3.5-flash"
CLAUDE_MODEL = "claude-haiku-4-5-20251001"


SYSTEM_INSTRUCTION = (
    "You are labeling egocentric (head-mounted camera) video frames from a factory or household "
    "task. You will receive N frames from ONE session performed by ONE worker. "
    "Return STRICT JSON only. No prose. No markdown fences."
)


def _build_prompt(ctx: Dict) -> str:
    return (
        f"Task context:\n"
        f"- Vertical: {ctx.get('company_type')}\n"
        f"- Task description: {ctx.get('task_description')}\n"
        f"- Candidate actions: {ctx.get('action_candidates')}\n"
        f"- Candidate objects: {ctx.get('object_candidates')}\n"
        f"- Candidate sub-tasks: {ctx.get('subtask_candidates')}\n"
        f"- Default indoor_outdoor: {ctx.get('indoor_outdoor')}\n\n"
        "From the frames provided, output STRICT JSON with keys:\n"
        '  "actions": [2 or 3 strings],\n'
        '  "objects": [up to 8 strings],\n'
        '  "sub_tasks": [2 or 3 strings],\n'
        '  "handedness": "Right-handed" | "Left-handed" | "Ambidextrous",\n'
        '  "task_difficulty": "easy" | "medium" | "hard",\n'
        '  "indoor_outdoor": "Indoor" | "Outdoor".\n'
        "Rules: prefer labels observed in the frames; you MAY use candidates when appropriate; "
        "handedness must reflect the dominant hand visible in the frames; if unclear default "
        "to Right-handed. Output JSON only."
    )


def _strip_json(text: str) -> str:
    from json_repair import repair_json
    text = text.strip()
    text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"```$", "", text).strip()
    start = text.find("{")
    if start == -1:
        return repair_json(text)
    # Try strict parse first (fastest); fall back to repair for malformed LLM output.
    try:
        obj, _ = json.JSONDecoder().raw_decode(text, start)
        return json.dumps(obj)
    except json.JSONDecodeError:
        return repair_json(text[start:])


def _normalize(parsed: Dict, ctx: Dict) -> Dict:
    def as_list(v):
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        if isinstance(v, str) and v.strip():
            return [v.strip()]
        return []

    actions = as_list(parsed.get("actions"))
    objects = as_list(parsed.get("objects"))
    sub_tasks = as_list(parsed.get("sub_tasks") or parsed.get("subtasks"))
    handedness = str(parsed.get("handedness") or "Right-handed").strip()
    if handedness not in ("Right-handed", "Left-handed", "Ambidextrous"):
        handedness = "Right-handed"
    difficulty = str(parsed.get("task_difficulty") or ctx.get("default_difficulty") or "medium").lower().strip()
    if difficulty not in ("easy", "medium", "hard"):
        difficulty = ctx.get("default_difficulty") or "medium"
    io_ = str(parsed.get("indoor_outdoor") or ctx.get("indoor_outdoor") or "Indoor").strip().title()
    if io_ not in ("Indoor", "Outdoor"):
        io_ = ctx.get("indoor_outdoor") or "Indoor"
    return {
        "actions": actions,
        "objects": objects,
        "sub_tasks": sub_tasks,
        "handedness": handedness,
        "task_difficulty": difficulty,
        "indoor_outdoor": io_,
    }


async def _gemini_call(frames: List[bytes], ctx: Dict) -> Dict:
    import google.generativeai as genai
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(GEMINI_MODEL, system_instruction=SYSTEM_INSTRUCTION)
    parts = [{"mime_type": "image/jpeg", "data": f} for f in frames]
    parts.append(_build_prompt(ctx))

    def _sync():
        return model.generate_content(
            parts,
            generation_config={"response_mime_type": "application/json", "temperature": 0.2},
        )

    resp = await asyncio.to_thread(_sync)
    text = resp.text if hasattr(resp, "text") else str(resp)
    parsed = json.loads(_strip_json(text))
    return _normalize(parsed, ctx)


async def _claude_call(frames: List[bytes], ctx: Dict) -> Dict:
    import anthropic
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    client = anthropic.Anthropic(api_key=api_key)
    content = []
    for f in frames:
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg",
                       "data": base64.b64encode(f).decode("ascii")},
        })
    content.append({"type": "text", "text": _build_prompt(ctx)})

    def _sync():
        return client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            system=SYSTEM_INSTRUCTION,
            messages=[{"role": "user", "content": content}],
        )

    resp = await asyncio.to_thread(_sync)
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    parsed = json.loads(_strip_json(text))
    return _normalize(parsed, ctx)


async def label_frames(frames: List[bytes], ctx: Dict, backend: str) -> Dict:
    fn = {"gemini": _gemini_call, "claude": _claude_call}.get(backend)
    if not fn:
        raise ValueError(f"unknown backend: {backend}")
    last_err = None
    for attempt in range(3):
        try:
            return await fn(frames, ctx)
        except (json.JSONDecodeError, ValueError) as e:
            last_err = e
            log.warning("VLM JSON parse failed (attempt %d): %s", attempt + 1, e)
            await asyncio.sleep(1.5 * (attempt + 1))
        except Exception as e:
            last_err = e
            log.warning("VLM call failed (attempt %d): %s", attempt + 1, e)
            await asyncio.sleep(2.0 * (attempt + 1))
    raise RuntimeError(f"VLM backend {backend} failed after retries: {last_err}")


def resolved_model_id(backend: str) -> str:
    return GEMINI_MODEL if backend == "gemini" else CLAUDE_MODEL
