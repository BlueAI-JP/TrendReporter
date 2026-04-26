#!/usr/bin/env python3
"""
main.py — 阿Vi每日趨勢報 主程式

用法:
  python main.py                    # 完整執行四國擷取 + 翻譯 + 寄信
  python main.py --country JP       # 只處理日本
  python main.py --no-email         # 只擷取+翻譯，不寄信（存成 trend_data.json）
  python main.py --from-json        # 從現有 trend_data.json 直接翻譯並寄信
  python main.py --test             # 寄送測試信確認 SMTP 設定
  python main.py --debug            # 開啟瀏覽器視窗 + 儲存除錯截圖
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from config import load_settings, Settings
from scraper import scrape_country, create_browser, close_browser, COUNTRY_ORDER
from translator import translate_country_data
from mailer import send_email, send_notification, build_html

BASE_DIR = Path(__file__).parent
DATA_FILE = BASE_DIR / "trend_data.json"


# ── Test mode ─────────────────────────────────────────────────────────────────

def run_test(settings: Settings) -> None:
    test_items = [
        {
            "keyword": "拓荒者 對 馬刺",
            "keyword_zh": "拓荒者 對 馬刺",
            "news": [
                {
                    "title": "NBA》Wembanyama腦震盪缺陣馬刺仍壓制拓荒者取得領先",
                    "title_zh": "NBA》Wembanyama腦震盪缺陣馬刺仍壓制拓荒者取得領先",
                    "url": "https://tw.sports.yahoo.com/news/nba",
                },
                {
                    "title": "NBA馬刺首輸輕鬆打？拓荒者下剋上有機會嗎",
                    "title_zh": "NBA馬刺首輸輕鬆打？拓荒者下剋上有機會嗎",
                    "url": "https://www.youtube.com/watch?v=example",
                },
            ],
        },
        {
            "keyword": "宮古島",
            "keyword_zh": "宮古島",
            "news": [
                {
                    "title": "「島に住めなくなるかもしれない」国民保護計画に先島の議員ら危機感",
                    "title_zh": "「我們可能再也無法在島上生活了」先島群島議員對國家保護計畫表示擔憂",
                    "url": "https://ryukyushimpo.jp/politics/entry-example.html",
                }
            ],
        },
    ]
    print("=== 測試模式：寄送台灣範例信 ===")
    send_email(settings, "TW", test_items)
    print("測試完成！請檢查收件匣。")


# ── From existing JSON ────────────────────────────────────────────────────────

def run_from_json(settings: Settings, countries: list[str]) -> None:
    if not DATA_FILE.exists():
        print(f"找不到 {DATA_FILE}，請先執行擷取程式。")
        sys.exit(1)

    with open(DATA_FILE, encoding="utf-8") as f:
        all_data: dict = json.load(f)

    for code in countries:
        items = all_data.get(code, [])
        if not items:
            print(f"[{code}] JSON 中無資料，跳過")
            continue
        print(f"\n[{code}] 翻譯 {len(items)} 條資料...")
        items, trans_error = translate_country_data(items, settings, code)
        send_email(settings, code, items)
        if trans_error:
            send_notification(settings, code, trans_error)


# ── Main scrape + translate + email ──────────────────────────────────────────

async def run_full(
    settings: Settings,
    countries: list[str],
    no_email: bool,
    debug: bool,
) -> None:
    headless = settings.browser_mode == "headless" and not debug

    pw, browser, ctx, page = await create_browser(headless=headless)
    all_data: dict = {}

    try:
        for code in countries:
            try:
                items = await scrape_country(page, code, debug=debug)
            except Exception as e:
                print(f"[{code}] ⚠ 擷取失敗: {e}")
                items = []

            all_data[code] = items

            # Save after each country in case of later failure
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(all_data, f, ensure_ascii=False, indent=2)

            if not items:
                continue

            print(f"[{code}] 開始批次翻譯...")
            items, trans_error = translate_country_data(items, settings, code)
            all_data[code] = items

            # Update JSON with translations
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(all_data, f, ensure_ascii=False, indent=2)

            if not no_email:
                send_email(settings, code, items)
                if trans_error:
                    send_notification(settings, code, trans_error)

    finally:
        await close_browser(pw, browser)

    print(f"\n資料已儲存至: {DATA_FILE}")

    if no_email:
        print("--no-email 模式：未寄送郵件。")
    else:
        print("所有郵件已寄送完畢。")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="阿Vi每日趨勢報")
    parser.add_argument("--country", help="只處理指定國家 (TW/HK/JP/KR)")
    parser.add_argument("--no-email", action="store_true", help="只擷取+翻譯，不寄信")
    parser.add_argument("--from-json", action="store_true", help="從現有 JSON 翻譯並寄信")
    parser.add_argument("--test", action="store_true", help="寄送測試信")
    parser.add_argument("--debug", action="store_true", help="顯示瀏覽器視窗 + 截圖")
    args = parser.parse_args()

    settings = load_settings()
    countries = [args.country.upper()] if args.country else COUNTRY_ORDER

    print(f"=== 阿Vi每日趨勢報 {datetime.now().strftime('%Y-%m-%d %H:%M')} ===")
    print(f"AI 提供商: {settings.ai_provider}  |  收件人: {settings.receiver}")

    if args.test:
        run_test(settings)
    elif args.from_json:
        run_from_json(settings, countries)
    else:
        asyncio.run(
            run_full(
                settings,
                countries,
                no_email=args.no_email,
                debug=args.debug,
            )
        )


if __name__ == "__main__":
    main()
