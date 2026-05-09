"""Cervello AI centralizzato — Groq only.

Tutti i cog importano da qui. Nessun altro file istanzia client AI,
definisce modelli o conosce il provider attivo.

Architettura a 2 livelli:
  1. Groq primary   (llama-3.3-70b-versatile)  — modello principale
  2. Groq fallback  (llama-3.1-8b-instant)     — se primary è down/rate-limited

Per cambiare modello: modifica MODELS qui sotto, non toccare altro.

API pubblica
------------
  MODELS                   dict con 'primary', 'fallback'
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
# MODELLI — modifica solo qui per cambiare versione
# ══════════════════════════════════════════════════════════════════════════════

MODELS = {
    "primary":  "llama-3.3-70b-versatile",  # Groq principale
    "fallback": "llama-3.1-8b-instant",     # Groq backup (se primary rate-limited/down)
}

# ── Client singleton ──────────────────────────────────────────────────────────────────────────
_groq_client = None


def _get_groq():
    global _groq_client
    if _groq_client is None:
        import groq
        _groq_client = groq.AsyncGroq(api_key=Config.GROQ_API_KEY)
    return _groq_client


# ── Utility ────────────────────────────────────────────────────────────────────────────────

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


# ── Chiamata Groq ─────────────────────────────────────────────────────────────────────────

async def _call_groq(
    messages: list[dict],
    max_tokens: int,
    temperature: float,
    model: str,
) -> tuple[str, str]:
    import groq as groq_lib

    client = _get_groq()
    try:
        resp = await client.chat.completions.create(
            model=model,
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
        log.debug(tag("AI", f"Risposta da {b(model)} ({len(reply)} chars)"))
        return reply, model
    except (groq_lib.APIStatusError, groq_lib.APIConnectionError, groq_lib.RateLimitError) as e:
        log.error(tag("AI", f"Groq {b(model)} fallito: {e}"))
        raise


# ── API pubblica ──────────────────────────────────────────────────────────────────────────

async def chat(
    messages: list[dict],
    max_tokens: int = 1024,
    temperature: float = 0.85,
    **_: Any,
) -> tuple[str, str]:
    """Chiamata AI con fallback a 2 livelli: Groq primary → Groq fallback.

    Parametri
    ---------
    messages    : lista dict {role, content} formato OpenAI
    max_tokens  : token massimi nella risposta
    temperature : creatività (0.0 = deterministico, 1.0 = creativo)

    Ritorna
    -------
    (reply, model_usato)
    """
    if not Config.GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY non configurata nel .env — il modulo AI non è disponibile.")

    try:
        return await _call_groq(messages, max_tokens, temperature, MODELS["primary"])
    except Exception as e:
        log.warning(tag("AI", f"Primary {b(MODELS['primary'])} fallito — provo fallback: {e}"))

    return await _call_groq(messages, max_tokens, temperature, MODELS["fallback"])


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
