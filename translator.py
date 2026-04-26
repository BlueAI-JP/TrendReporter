"""Batch AI translation for TrendReporter.

Translates all keywords and news titles for one country in a single API call
to minimise token usage.
"""

import json
import re
from typing import Optional

from config import Settings


# ── Language detection ────────────────────────────────────────────────────────

def _needs_translation(text: str) -> bool:
    """Return True if text contains Japanese, Korean, or Latin characters."""
    if not text.strip():
        return False
    for ch in text:
        cp = ord(ch)
        # Japanese hiragana / katakana
        if 0x3040 <= cp <= 0x30FF:
            return True
        # Korean hangul
        if 0xAC00 <= cp <= 0xD7AF or 0x1100 <= cp <= 0x11FF:
            return True
    # Has ASCII letters (English/Romanised text) and no CJK → translate
    has_latin = any(c.isalpha() and ord(c) < 128 for c in text)
    has_cjk = any(0x4E00 <= ord(c) <= 0x9FFF for c in text)
    if has_latin and not has_cjk:
        return True
    return False


# ── Prompt builder ────────────────────────────────────────────────────────────

def _build_prompt(texts: list[str]) -> str:
    items = "\n".join(f'{i + 1}. "{t}"' for i, t in enumerate(texts))
    return (
        "Translate each text to Traditional Chinese (繁體中文). Rules:\n"
        "- Already Traditional Chinese → keep unchanged\n"
        "- Simplified Chinese → convert to Traditional Chinese\n"
        "- Japanese / Korean / English / other → translate to Traditional Chinese\n"
        "- Keep brand names, proper nouns, and URLs unchanged\n"
        "- Return ONLY a JSON array with translations in the same order, no explanation\n\n"
        f"Texts:\n{items}\n\n"
        'Return format: ["translation1", "translation2", ...]'
    )


def _parse_response(text: str, expected: int) -> list[str]:
    match = re.search(r"\[.*?\]", text, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group())
            if isinstance(result, list) and len(result) == expected:
                return [str(r) for r in result]
        except json.JSONDecodeError:
            pass
    # Fallback: return empty strings (caller fills with originals)
    return [""] * expected


# ── API callers ───────────────────────────────────────────────────────────────

def _call_gemini(texts: list[str], api_key: str, model: str) -> list[str]:
    from google import genai  # type: ignore  (google-genai package)

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model or "gemini-2.0-flash",
        contents=_build_prompt(texts),
    )
    return _parse_response(response.text, len(texts))


def _call_anthropic(texts: list[str], api_key: str, model: str) -> list[str]:
    import anthropic  # type: ignore

    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model=model or "claude-haiku-4-5-20251001",
        max_tokens=8192,
        messages=[{"role": "user", "content": _build_prompt(texts)}],
    )
    return _parse_response(msg.content[0].text, len(texts))


# ── Public API ────────────────────────────────────────────────────────────────

TRANSLATE_COUNTRIES = {"JP", "KR"}


def translate_country_data(
    items: list[dict], settings: Settings, country_code: str = ""
) -> tuple[list[dict], Optional[str]]:
    """Batch-translate all text for one country in a single AI API call.

    Returns (items, error_message).
    error_message is None on success; a non-empty string if the API failed
    (items will still be filled with original text as fallback).
    """

    if country_code and country_code not in TRANSLATE_COUNTRIES:
        _fill_missing(items)
        return items, None

    texts: list[str] = []
    positions: list[tuple] = []  # (item_idx, 'keyword' | 'news', news_idx)

    for i, item in enumerate(items):
        kw = item.get("keyword", "")
        if kw and _needs_translation(kw):
            texts.append(kw)
            positions.append((i, "keyword", -1))
        else:
            item["keyword_zh"] = kw

        for j, news in enumerate(item.get("news", [])):
            title = news.get("title", "")
            if title and _needs_translation(title):
                texts.append(title)
                positions.append((i, "news", j))
            else:
                news["title_zh"] = title

    if not texts:
        _fill_missing(items)
        return items, None

    print(f"  翻譯 {len(texts)} 條文字 (單次 API 呼叫)...")

    error_msg: Optional[str] = None
    try:
        if settings.ai_provider == "gemini":
            if not settings.gemini_api_key or settings.gemini_api_key.startswith("YOUR_"):
                raise ValueError("請在 MailSetting.txt 填入 GeminiAPIKey")
            translations = _call_gemini(texts, settings.gemini_api_key, settings.ai_model)
        elif settings.ai_provider == "anthropic":
            if not settings.anthropic_api_key or settings.anthropic_api_key.startswith("YOUR_"):
                raise ValueError("請在 MailSetting.txt 填入 AnthropicAPIKey")
            translations = _call_anthropic(texts, settings.anthropic_api_key, settings.ai_model)
        else:
            raise ValueError(f"不支援的 AIProvider: {settings.ai_provider}")

        for (i, field, j), translated in zip(positions, translations):
            if not translated:
                continue
            if field == "keyword":
                items[i]["keyword_zh"] = translated
            else:
                items[i]["news"][j]["title_zh"] = translated

    except Exception as e:
        error_msg = str(e)
        print(f"  ⚠ 翻譯 API 失敗: {error_msg}，改用原文")

    _fill_missing(items)
    return items, error_msg


def _fill_missing(items: list[dict]) -> None:
    """Fill any untranslated fields with the original text."""
    for item in items:
        if "keyword_zh" not in item:
            item["keyword_zh"] = item.get("keyword", "")
        for news in item.get("news", []):
            if "title_zh" not in news:
                news["title_zh"] = news.get("title", "")
