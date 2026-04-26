"""Settings loader for TrendReporter."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Settings:
    sender: str
    receiver: list[str]
    app_password: str
    ai_provider: str = "gemini"
    gemini_api_key: str = ""
    anthropic_api_key: str = ""
    ai_model: str = ""
    browser_mode: str = "headless"


def load_settings(path: Optional[Path] = None) -> Settings:
    if path is None:
        path = Path(__file__).parent / "MailSetting.txt"

    raw: dict[str, str] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                raw[key.strip()] = value.strip()

    required = ["Sender", "Receiver", "AppPassword"]
    for r in required:
        if not raw.get(r):
            raise ValueError(f"MailSetting.txt 缺少必要欄位: {r}")

    return Settings(
        sender=raw["Sender"],
        receiver=[r.strip() for r in raw["Receiver"].split(";") if r.strip()],
        app_password=raw["AppPassword"].replace(" ", ""),
        ai_provider=raw.get("AIProvider", "gemini").lower(),
        gemini_api_key=raw.get("GeminiAPIKey", ""),
        anthropic_api_key=raw.get("AnthropicAPIKey", ""),
        ai_model=raw.get("AIModel", ""),
        browser_mode=raw.get("BrowserMode", "headless").lower(),
    )
