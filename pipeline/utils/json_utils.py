"""
Shared JSON parsing + AI JSON-call utilities.
Priority: OpenAI (GPT-4o-mini) -> Gemini native SDK -> Gemini OpenAI-compat.
"""
import json
import re


# Set of code points that are never valid inside JSON string values.
# Built programmatically so no whitespace can sneak in via literal pasted chars.
_BAD_CODEPOINTS = set()
for _c in range(0x00, 0x09):
    _BAD_CODEPOINTS.add(_c)                # C0 controls except \t (0x09)
_BAD_CODEPOINTS.update((0x0B, 0x0C))       # vertical tab, form feed
for _c in range(0x0E, 0x20):
    _BAD_CODEPOINTS.add(_c)                # more C0 (keeps \n=0x0a, \r=0x0d)
_BAD_CODEPOINTS.add(0x7F)                  # DEL
for _c in range(0x80, 0xA0):
    _BAD_CODEPOINTS.add(_c)                # C1 controls (incl. \x85 NEL)
_BAD_CODEPOINTS.update((0x2028, 0x2029))   # Line separator / paragraph separator
_BAD_TABLE = {c: None for c in _BAD_CODEPOINTS}


def safe_json_parse(raw: str) -> dict:
    """
    Parse JSON from an LLM response that may contain:
    - Markdown code fences
    - Trailing commas / JS comments
    - Bare control characters
    - Truncated JSON (repaired by json-repair)
    """
    text = (raw or "").strip()

    # Strip markdown code fences
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    # Strip invalid control chars (DOES NOT TOUCH SPACES, TABS, NEWLINES)
    text = text.translate(_BAD_TABLE)
    text = text.strip()

    # Attempt 1 — clean parse
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass

    # Attempt 2 — strip JS comments + trailing commas
    t2 = re.sub(r"//[^\n]*", "", text)
    t2 = re.sub(r",\s*([}\]])", r"\1", t2)
    try:
        return json.loads(t2)
    except (json.JSONDecodeError, ValueError):
        pass

    # Attempt 3 — json-repair library
    try:
        from json_repair import repair_json
        result = repair_json(text, return_objects=True)
        if isinstance(result, dict):
            return result
    except Exception:
        pass

    # Attempt 4 — extract outermost { ... } and repair
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            from json_repair import repair_json
            result = repair_json(m.group(0), return_objects=True)
            if isinstance(result, dict):
                return result
        except Exception:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass

    raise ValueError(f"Could not parse JSON (len={len(raw)}): {raw[:200]}")


def gemini_json_call(config, prompt: str, max_tokens: int = 2000) -> dict:
    """
    Make a JSON-mode AI call and return a parsed dict.
    Priority: OpenAI JSON mode -> Gemini native SDK -> Gemini OpenAI-compat.
    """
    # ── OpenAI (primary) ─────────────────────────────────────────────────
    if config.has_openai:
        client = config.make_ai_client()
        resp = client.chat.completions.create(
            model=config.ai_fast_model,
            max_tokens=max_tokens,
            temperature=0.2,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        return safe_json_parse(resp.choices[0].message.content or "")

    # ── Gemini native SDK (fallback, never truncates) ─────────────────────
    gemini = config.make_gemini_client()
    if gemini:
        from google.genai import types
        try:
            resp = gemini.models.generate_content(
                model="models/gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.2,
                    max_output_tokens=max_tokens,
                    response_mime_type="application/json",
                ),
            )
            return safe_json_parse(resp.text or "")
        except Exception:
            pass

    # ── Gemini OpenAI-compat endpoint (last resort) ───────────────────────
    client = config.make_ai_client()
    resp = client.chat.completions.create(
        model=config.ai_fast_model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return safe_json_parse(resp.choices[0].message.content or "")
