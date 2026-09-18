"""Gemini via Google SDKs with multi-key rotation and resilient OpenAI fallback."""
from __future__ import annotations

import asyncio
import io
import logging
import os
import re
import time

log = logging.getLogger("Dabot.Gemini")

_MODELS = (
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-flash-latest",
    "gemini-2.0-flash",
)
_cool: dict[str, float] = {}
_key_cool: dict[str, float] = {}

def _rate_limit_wait(err) -> int | None:
    text = str(err).lower()
    if not any(tok in text for tok in ("429", "resource_exhausted", "quota", "rate limit", "ratelimit")):
        return None
    m = re.search(r"retry[\s\w]*?(\d+(?:\.\d+)?)\s*s", text)
    if m:
        return min(600, max(20, int(float(m.group(1))) + 8))
    return 180


def _order() -> list[str]:
    now = time.time()
    ready = [m for m in _MODELS if _cool.get(m, 0) <= now]
    return ready or list(_MODELS)


_NEW = None
_OLD = None
try:
    from google import genai as genai_new
    from google.genai import types as genai_types
    _NEW = True
except Exception:
    _NEW = False
try:
    import google.generativeai as genai_old
    _OLD = True
except Exception:
    _OLD = False


def _keys() -> list[str]:
    raw = os.getenv("GEMINI_API_KEY") or ""
    return [k.strip() for k in raw.split(",") if k.strip()]


def _available_keys() -> list[str]:
    now = time.time()
    all_k = _keys()
    ready = [k for k in all_k if _key_cool.get(k, 0) <= now]
    return ready or all_k


async def generate_text(prompt: str, *, timeout: float = 12) -> str | None:
    keys = _available_keys()
    last_err = None

    for key_idx, key in enumerate(keys):
        if _NEW:
            try:
                client = genai_new.Client(api_key=key)
                for name in _order():
                    try:
                        def _run(model=name, cl=client):
                            resp = cl.models.generate_content(model=model, contents=prompt)
                            return (resp.text or "").strip()
                        res = await asyncio.wait_for(asyncio.to_thread(_run), timeout=timeout)
                        if res:
                            return res
                    except Exception as e:
                        last_err = e
                        wait = _rate_limit_wait(e)
                        if wait:
                            _cool[name] = time.time() + wait
                            _key_cool[key] = time.time() + wait
                            log.warning("🧊 Gemini Key #%s / %s en pausa %ss (rate limit). Probando siguiente...", key_idx + 1, name, wait)
                            break
                        else:
                            log.info("google.genai text %s failed: %s", name, e)
            except Exception as e:
                last_err = e

        if _OLD:
            try:
                genai_old.configure(api_key=key)
                for name in _order():
                    try:
                        model = genai_old.GenerativeModel(name)
                        resp = await asyncio.wait_for(
                            asyncio.to_thread(model.generate_content, prompt),
                            timeout=timeout,
                        )
                        res = (resp.text or "").strip()
                        if res:
                            return res
                    except Exception as e:
                        last_err = e
                        wait = _rate_limit_wait(e)
                        if wait:
                            _cool[name] = time.time() + wait
                            _key_cool[key] = time.time() + wait
                            log.warning("🧊 Legacy Gemini Key #%s / %s en pausa %ss (rate limit). Probando siguiente...", key_idx + 1, name, wait)
                            break
                        else:
                            log.info("legacy generativeai text %s failed: %s", name, e)
            except Exception as e:
                last_err = e

    # Fallback to OpenAI gpt-4o-mini if all Gemini keys are cooling or exhausted
    oa_key = os.getenv("OPENAI_API_KEY")
    if oa_key:
        try:
            import openai
            client = openai.AsyncOpenAI(api_key=oa_key)
            resp = await asyncio.wait_for(
                client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=1000
                ),
                timeout=timeout
            )
            text = (resp.choices[0].message.content or "").strip()
            if text:
                log.info("⚡ Fallback a OpenAI (gpt-4o-mini) ejecutado con éxito en generate_text.")
                return text
        except Exception as e:
            log.warning("OpenAI fallback failed in gemini_client: %s", e)

    if last_err:
        log.info("gemini text exhausted: %s", last_err)
    return None


async def generate_vision(prompt: str, image, *, timeout: float = 8) -> str | None:
    """image: PIL.Image.Image"""
    keys = _available_keys()
    if not keys:
        return None
    thumb = image.copy()
    thumb.thumbnail((768, 768))
    buf = io.BytesIO()
    thumb.save(buf, format="JPEG", quality=75)
    raw = buf.getvalue()

    last_err = None
    for key_idx, key in enumerate(keys):
        if _NEW:
            try:
                client = genai_new.Client(api_key=key)
                part = genai_types.Part.from_bytes(data=raw, mime_type="image/jpeg")
                for name in _order():
                    try:
                        def _run(model=name, cl=client, pt=part):
                            resp = cl.models.generate_content(model=model, contents=[prompt, pt])
                            return (resp.text or "").strip()
                        res = await asyncio.wait_for(asyncio.to_thread(_run), timeout=timeout)
                        if res:
                            return res
                    except Exception as e:
                        last_err = e
                        wait = _rate_limit_wait(e)
                        if wait:
                            _cool[name] = time.time() + wait
                            _key_cool[key] = time.time() + wait
                            log.warning("🧊 Gemini Vision Key #%s / %s en pausa %ss. Probando siguiente...", key_idx + 1, name, wait)
                            break
                        else:
                            log.info("google.genai vision %s failed: %s", name, e)
            except Exception as e:
                last_err = e

        if _OLD:
            try:
                from PIL import Image
                genai_old.configure(api_key=key)
                img = Image.open(io.BytesIO(raw))
                for name in _order():
                    try:
                        model = genai_old.GenerativeModel(name)
                        resp = await asyncio.wait_for(
                            asyncio.to_thread(model.generate_content, [prompt, img]),
                            timeout=timeout,
                        )
                        res = (resp.text or "").strip()
                        if res:
                            return res
                    except Exception as e:
                        last_err = e
                        wait = _rate_limit_wait(e)
                        if wait:
                            _cool[name] = time.time() + wait
                            _key_cool[key] = time.time() + wait
                            log.warning("🧊 Legacy Vision Key #%s / %s en pausa %ss. Probando siguiente...", key_idx + 1, name, wait)
                            break
                        else:
                            log.info("legacy vision %s failed: %s", name, e)
            except Exception as e:
                last_err = e

    if last_err:
        log.info("gemini vision exhausted: %s", last_err)
    return None
