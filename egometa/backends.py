"""VLM backends: ollama + gemini + claude. label_frames(frames, ctx) -> dict."""
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

# Ollama runs locally; override the model/host via env if needed.
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "gemma3")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_TIMEOUT_S = 300.0


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


async def _ollama_call(frames: List[bytes], ctx: Dict) -> Dict:
    import ollama

    client = ollama.AsyncClient(host=OLLAMA_HOST, timeout=OLLAMA_TIMEOUT_S)
    images = [base64.b64encode(f).decode("ascii") for f in frames]

    total_bytes = sum(len(f) for f in frames)
    log.info("VLM call (ollama %s): %d frames, %d bytes total",
             OLLAMA_MODEL, len(frames), total_bytes)

    try:
        resp = await client.chat(
            model=OLLAMA_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_INSTRUCTION},
                {"role": "user", "content": _build_prompt(ctx), "images": images},
            ],
            format="json",
            options={"temperature": 0.2},
        )
    except ollama.ResponseError as e:
        if getattr(e, "status_code", None) == 404:
            raise RuntimeError(
                f"Ollama model '{OLLAMA_MODEL}' not found. Run: ollama pull {OLLAMA_MODEL}"
            ) from e
        raise

    text = resp["message"]["content"]
    parsed = json.loads(_strip_json(text))
    return _normalize(parsed, ctx)


GEMINI_TIMEOUT_MS = 180_000  # google-genai HttpOptions.timeout is in milliseconds


async def _gemini_call(frames: List[bytes], ctx: Dict) -> Dict:
    from google import genai
    from google.genai import types
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")
    client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=GEMINI_TIMEOUT_MS))
    parts = [types.Part.from_bytes(data=f, mime_type="image/jpeg") for f in frames]
    parts.append(types.Part.from_text(text=_build_prompt(ctx)))

    total_bytes = sum(len(f) for f in frames)
    if total_bytes > 2_000_000:
        log.warning("VLM call payload is unusually large: %d frames, %d bytes total",
                    len(frames), total_bytes)
    else:
        log.info("VLM call: %d frames, %d bytes total", len(frames), total_bytes)

    resp = await client.aio.models.generate_content(
        model=GEMINI_MODEL,
        contents=parts,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
            temperature=0.2,
        ),
    )
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


def _is_quota_exhausted(e: Exception) -> bool:
    """True for a daily/quota 429 that no amount of retrying within this run can fix."""
    try:
        from google.genai.errors import ClientError
        if isinstance(e, ClientError) and getattr(e, "code", None) == 429:
            return True
    except ImportError:
        pass
    return "429" in str(e) and "quota" in str(e).lower()


def _is_transient_server_error(e: Exception) -> bool:
    """True for a timeout/server-side hiccup (504/503/500) worth retrying patiently."""
    try:
        from google.genai.errors import ServerError
        if isinstance(e, ServerError):
            return True
    except ImportError:
        pass
    msg = str(e)
    return any(code in msg for code in ("504", "503", "500", "Deadline expired", "TimeoutError"))


async def label_frames(frames: List[bytes], ctx: Dict, backend: str) -> Dict:
    fn = {"ollama": _ollama_call, "gemini": _gemini_call, "claude": _claude_call}.get(backend)
    if not fn:
        raise ValueError(f"unknown backend: {backend}")
    last_err = None
    max_attempts = 3
    for attempt in range(max_attempts):
        try:
            return await fn(frames, ctx)
        except (json.JSONDecodeError, ValueError) as e:
            last_err = e
            log.warning("VLM JSON parse failed (attempt %d): %s", attempt + 1, e)
            await asyncio.sleep(1.5 * (attempt + 1))
        except Exception as e:
            last_err = e
            if _is_quota_exhausted(e):
                # Daily quota is exhausted; no amount of retrying in this run will help.
                log.warning("VLM call failed (quota exhausted, not retrying): %s", e)
                raise RuntimeError(f"VLM backend {backend} quota exhausted: {e}") from e
            if _is_transient_server_error(e):
                # Give the backend real time to recover instead of a quick 2-6s backoff.
                delay = min(20.0 * (2 ** attempt), 90.0)
                log.warning(
                    "VLM call failed (transient server error, attempt %d/%d, retrying in %.0fs): %s",
                    attempt + 1, max_attempts, delay, e,
                )
                await asyncio.sleep(delay)
                continue
            log.warning("VLM call failed (attempt %d): %s", attempt + 1, e)
            await asyncio.sleep(2.0 * (attempt + 1))
    raise RuntimeError(f"VLM backend {backend} failed after retries: {last_err}")


def resolved_model_id(backend: str) -> str:
    return {
        "ollama": OLLAMA_MODEL,
        "gemini": GEMINI_MODEL,
        "claude": CLAUDE_MODEL,
    }.get(backend, backend)
