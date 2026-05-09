"""Cervello AI centralizzato.

Tutti i cog importano da qui. Nessun altro file istanzia client AI,
definisce modelli o conosce il provider attivo.

Architettura a 3 livelli:
  1. Gemini primary   (gemini-2.5-flash)      — modello principale
  2. Gemini fallback  (gemini-2.0-flash)      — se primary è 404/overload
  3. Groq emergency   (llama-3.1-8b-instant)  — se Gemini è completamente down

Per cambiare modello: modifica MODELS qui sotto, non toccare altro.

API pubblica
------------
  MODELS                   dict con 'primary', 'fallback', 'emergency'
  chat(messages, **kw)     → (reply: str, model: str)
  generate(prompt, **kw)   → str   (one-shot, senza memoria)
  load_prompt(path)        → str   (legge .txt con cache LRU)
  invalidate_prompt_cache()         resetta la cache LRU dei prompt
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from config import Config
from core.log_colors import tag, b

log = logging.getLogger("pitonazz.ai_client")

# ══════════════════════════════════════════════════════════════════════════════
# MODELLI — modifica solo qui per cambiare provider/versione
# ══════════════════════════════════════════════════════════════════════════════

MODELS = {
    "primary":   "gemini-2.5-flash",       # Gemini principale
    "fallback":  "gemini-2.0-flash",       # Gemini backup (se primary down)
    "emergency": "llama-3.1-8b-instant",   # Groq solo se Gemini è irraggiungibile
}

# ── Client singleton ──────────────────────────────────────────────────────────
_gemini_client = None
_groq_client   = None


def _get_gemini():
    global _gemini_client
    if _gemini_client is None:
        from google import genai
        _gemini_client = genai.Client(api_key=Config.GEMINI_API_KEY)
    return _gemini_client


def _get_groq():
    global _groq_client
    if _groq_client is None:
        import groq
        _groq_client = groq.AsyncGroq(api_key=Config.GROQ_API_KEY)
    return _groq_client


# ── Utility ───────────────────────────────────────────────────────────────────

@lru_cache(maxsize=8)
def load_prompt(path: str) -> str:
    """Legge un file di prompt con cache LRU. Usa invalidate_prompt_cache() per forzare rilettura."""
    p = Path(path)
    if not p.exists():
        log.warning(tag("AI", f"Prompt non trovato: {path}"))
        return ""
    return p.read_text(encoding="utf-8").strip()


def invalidate_prompt_cache() -> None:
    """Resetta la cache LRU di load_prompt, forzando la rilettura dal disco al prossimo accesso."""
    load_prompt.cache_clear()
    log.info(tag("AI", "Cache prompt invalidata."))


def _build_gemini_contents(messages: list[dict]):
    """Converte formato OpenAI → google-genai (system separato, roles user/model)."""
    from google.genai import types as t
    system = ""
    contents = []
    for msg in messages:
        role, content = msg["role"], msg["content"]
        if role == "system":
            system = content
        elif role == "user":
            contents.append(t.Content(role="user",  parts=[t.Part(text=content)]))
        elif role == "assistant":
            contents.append(t.Content(role="model", parts=[t.Part(text=content)]))
    return system, contents


# ── Chiamata Gemini ───────────────────────────────────────────────────────────

async def _call_gemini(
    messages: list[dict],
    max_tokens: int,
    temperature: float,
) -> tuple[str, str]:
    """Prova primary, poi fallback interno Gemini."""
    from google.genai import types as t

    client = _get_gemini()
    system, contents = _build_gemini_contents(messages)
    config = t.GenerateContentConfig(
        system_instruction=system or None,
        max_output_tokens=max_tokens,
        temperature=temperature,
    )

    for model in [MODELS["primary"], MODELS["fallback"]]:
        try:
            resp = await client.aio.models.generate_content(
                model=model, contents=contents, config=config
            )
            reply = resp.text.strip()
            log.debug(tag("AI", f"Risposta da {b(model)} ({len(reply)} chars)"))
            return reply, model
        except Exception as e:
            if model == MODELS["primary"]:
                log.warning(tag("AI", f"Primary fallito — provo fallback: {e}"))
                continue
            raise

    raise RuntimeError("Entrambi i modelli Gemini non disponibili.")


# ── Chiamata Groq (emergency) ─────────────────────────────────────────────────

async def _call_groq(
    messages: list[dict],
    max_tokens: int,
    temperature: float,
) -> tuple[str, str]:
    """Emergency fallback su Groq. Solo se Gemini è completamente irraggiungibile."""
    import groq as groq_lib

    client = _get_groq()
    try:
        resp = await client.chat.completions.create(
            model=MODELS["emergency"],
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        if not getattr(resp, "choices", None):
            raise RuntimeError("Groq ha restituito una risposta senza choices.")
        content = resp.choices[0].message.content
        reply = (content or "").strip()
        if not reply:
            raise RuntimeError("Groq ha restituito una risposta vuota.")
        log.warning(tag("AI", f"Emergency Groq attivo — {b(MODELS['emergency'])}"))
        return reply, MODELS["emergency"]
    except (groq_lib.APIStatusError, groq_lib.APIConnectionError, groq_lib.RateLimitError) as e:
        log.error(tag("AI", f"Emergency Groq fallito: {e}"))
        raise


# ── API pubblica ──────────────────────────────────────────────────────────────

async def chat(
    messages: list[dict],
    max_tokens: int = 1024,
    temperature: float = 0.85,
    **_: Any,
) -> tuple[str, str]:
    """Chiamata AI con fallback a 3 livelli: Gemini primary → Gemini fallback → Groq emergency.

    Parametri
    ---------
    messages    : lista dict {role, content} formato OpenAI
    max_tokens  : token massimi nella risposta
    temperature : creatività (0.0 = deterministico, 1.0 = creativo)

    Ritorna
    -------
    (reply, model_usato)
    """
    if Config.GEMINI_API_KEY:
        try:
            return await _call_gemini(messages, max_tokens, temperature)
        except Exception as e:
            log.error(tag("AI", f"Gemini completamente down: {e}"))

    if Config.GROQ_API_KEY:
        log.warning(tag("AI", "Gemini irraggiungibile — attivo emergency Groq"))
        return await _call_groq(messages, max_tokens, temperature)

    raise RuntimeError("Nessun provider AI disponibile (controlla GEMINI_API_KEY / GROQ_API_KEY nel .env).")


async def generate(
    prompt: str,
    max_tokens: int = 200,
    temperature: float = 1.0,
    **kw: Any,
) -> str:
    """One-shot: singolo messaggio utente, ritorna solo il testo."""
    reply, _ = await chat(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        temperature=temperature,
        **kw,
    )
    return reply
