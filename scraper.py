"""Playwright-based Google Trends scraper for TrendReporter.

Flow per country:
  1. Navigate to trending page
  2. Extract up to 25 keywords
  3. For each keyword:
     a. Click → wait for sidebar/panel
     b. Extract top-3 news links from sidebar
     c. If no news → click search button → Google Search News tab → extract top-3
  4. Return raw data list (no translation yet)
"""

import asyncio
from pathlib import Path
from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
    TimeoutError as PlaywrightTimeout,
)


COUNTRY_URLS = {
    "JP": "https://trends.google.com.tw/trending?geo=JP&hours=4",
    "KR": "https://trends.google.com.tw/trending?geo=KR&hours=4",
    "HK": "https://trends.google.com.tw/trending?geo=HK&hours=4",
    "TW": "https://trends.google.com.tw/trending?geo=TW&hours=4",
}

COUNTRY_ORDER = ["JP", "KR", "HK", "TW"]

# Google-internal URL prefixes to skip when looking for news links
_GOOGLE_HOSTS = ("trends.google", "google.com", "googleapis.com", "goo.gl", "google.co")

# Sidebar/panel container selectors (try in order)
_PANEL_SELECTORS = [
    "explore-sidebar",
    ".explore-sidebar",
    "[class*='sidebar']",
    "[class*='detail-panel']",
    "[class*='details-panel']",
    ".panel-right",
]

# Selectors for the "Google Search" button inside the panel
_SEARCH_BTN_SELECTORS = [
    "button:has-text('Google 搜尋')",
    "button:has-text('Google Search')",
    "button:has-text('Google検索')",
    "button:has-text('Google 검색')",
    "a:has-text('Google Search')",
    "[aria-label*='Search']",
    "button[jsaction*='search']",
]

# Selectors for the "News" tab on Google Search results
_NEWS_TAB_SELECTORS = [
    "a[href*='tbm=nws']",
    "div[role='tab']:has-text('新聞')",
    "div[role='tab']:has-text('News')",
    "div[role='tab']:has-text('ニュース')",
    "div[role='tab']:has-text('뉴스')",
    "a:has-text('News')",
    "a:has-text('新聞')",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_google_url(url: str) -> bool:
    return any(h in url for h in _GOOGLE_HOSTS)


async def _dismiss_consent(page: Page) -> None:
    """Dismiss cookie consent / sign-in dialogs if present."""
    for selector in [
        "button:has-text('接受所有')",
        "button:has-text('Accept all')",
        "button:has-text('すべて同意')",
        "button:has-text('모두 동의')",
        "button:has-text('Reject all')",
        "button:has-text('拒絕全部')",
        "[aria-label='Accept all']",
    ]:
        try:
            btn = page.locator(selector).first
            if await btn.count() > 0:
                await btn.click(timeout=3000)
                await page.wait_for_timeout(1000)
                return
        except Exception:
            pass


async def _get_external_news_from_page(page: Page, limit: int = 3) -> list[dict]:
    """Extract external news links visible on the current page (used for sidebar + search)."""
    return await page.evaluate(
        """(args) => {
        const { panelSelectors, googleHosts, limit } = args;

        let container = null;
        for (const sel of panelSelectors) {
            container = document.querySelector(sel);
            if (container) break;
        }
        const root = container || document.body;

        const results = [];
        const seen = new Set();

        const anchors = root.querySelectorAll('a[href^="http"]');
        for (const a of anchors) {
            const href = a.href;
            const text = (a.innerText || a.textContent || '').trim();

            if (!href || !text) continue;
            if (googleHosts.some(h => href.includes(h))) continue;
            if (text.length < 6 || text.length > 350) continue;
            if (seen.has(href)) continue;

            // Skip navigation/button-like text
            const skipWords = ['搜尋', 'Search', '検索', '검색', 'MORE', '更多', 'View more'];
            if (skipWords.includes(text)) continue;

            seen.add(href);
            results.push({ title: text, url: href });
            if (results.length >= limit) break;
        }
        return results;
    }""",
        {"panelSelectors": _PANEL_SELECTORS, "googleHosts": list(_GOOGLE_HOSTS), "limit": limit},
    )


async def _try_search_fallback(page: Page, keyword: str, original_url: str) -> list[dict]:
    """Click the Search button → go to Google News tab → extract news."""

    # Try clicking the search button inside the panel
    clicked = False
    for selector in _SEARCH_BTN_SELECTORS:
        try:
            btn = page.locator(selector).first
            if await btn.count() > 0:
                await btn.click(timeout=4000)
                await page.wait_for_load_state("domcontentloaded", timeout=15000)
                clicked = True
                break
        except Exception:
            pass

    # If no search button found, navigate directly to Google News search
    if not clicked:
        encoded = keyword.replace(" ", "+")
        await page.goto(
            f"https://www.google.com/search?q={encoded}&tbm=nws",
            wait_until="domcontentloaded",
            timeout=20000,
        )

    await page.wait_for_timeout(1500)

    # If landed on general search (not news), click the News tab
    if "tbm=nws" not in page.url:
        for selector in _NEWS_TAB_SELECTORS:
            try:
                tab = page.locator(selector).first
                if await tab.count() > 0:
                    await tab.click(timeout=4000)
                    await page.wait_for_load_state("domcontentloaded", timeout=10000)
                    break
            except Exception:
                pass

    await page.wait_for_timeout(1000)

    # Extract Google News results
    news = await page.evaluate(
        """(googleHosts) => {
        const results = [];
        const seen = new Set();

        // Google News result selectors (multiple layouts)
        const selectors = [
            'div[data-news-doc-id] a',
            '.SoaBEf a',
            '.WlydOe',
            'g-card a[href^="http"]',
            'article a[href^="http"]',
            '.dbsr a',
            'a.WlydOe',
        ];

        for (const sel of selectors) {
            const els = document.querySelectorAll(sel);
            for (const a of els) {
                const href = a.href;
                const text = (a.innerText || a.textContent || '').trim();
                if (!href || !text) continue;
                if (googleHosts.some(h => href.includes(h))) continue;
                if (text.length < 6 || text.length > 350) continue;
                if (seen.has(href)) continue;
                seen.add(href);
                results.push({ title: text, url: href });
                if (results.length >= 3) return results;
            }
            if (results.length > 0) return results;
        }
        return results;
    }""",
        list(_GOOGLE_HOSTS),
    )

    return news[:3]


# ── Keyword extraction ────────────────────────────────────────────────────────

async def _get_keywords(page: Page) -> list[str]:
    """Extract up to 25 trending keyword texts from the list page."""

    # CSS selector attempts
    for selector in [
        "feed-item .title a",
        "feed-item .details .title",
        "feed-item .title",
        ".trending-searches-item .title",
        "[class*='trending'] [class*='title']",
    ]:
        try:
            elements = await page.locator(selector).all()
            if len(elements) >= 3:
                keywords = []
                for el in elements[:25]:
                    try:
                        text = (await el.inner_text()).strip()
                        if text and 1 < len(text) < 200:
                            keywords.append(text)
                    except Exception:
                        pass
                if keywords:
                    return keywords
        except Exception:
            pass

    # JavaScript fallback — tries multiple strategies
    return await page.evaluate("""() => {
        const strategies = [
            () => document.querySelectorAll('feed-item .title'),
            () => document.querySelectorAll('feed-item [class*="title"]'),
            () => document.querySelectorAll('.trending-item .title'),
            () => document.querySelectorAll('[class*="trending-search"] .title'),
        ];

        for (const fn of strategies) {
            const els = fn();
            if (els.length >= 3) {
                return Array.from(els)
                    .slice(0, 25)
                    .map(el => el.innerText.trim())
                    .filter(t => t && t.length > 1 && t.length < 200);
            }
        }

        // Last resort: get text from feed-item elements
        const items = document.querySelectorAll('feed-item');
        if (items.length >= 3) {
            return Array.from(items).slice(0, 25).map(item => {
                const link = item.querySelector('a');
                if (link) {
                    const t = link.innerText.trim();
                    if (t && t.length > 1 && t.length < 200) return t;
                }
                return (item.innerText || '').split('\\n')[0].trim();
            }).filter(t => t && t.length > 1 && t.length < 200);
        }
        return [];
    }""")


# ── Per-keyword scraping ──────────────────────────────────────────────────────

async def _scrape_one_keyword(
    page: Page, keyword: str, list_url: str, debug: bool
) -> dict:
    result: dict = {"keyword": keyword, "keyword_zh": keyword, "news": []}

    original_url = page.url

    # Click the keyword
    clicked = False
    for locator in [
        page.get_by_text(keyword, exact=True).first,
        page.locator(f"text={keyword}").first,
    ]:
        try:
            if await locator.count() > 0:
                await locator.click(timeout=5000)
                clicked = True
                break
        except Exception:
            pass

    if not clicked:
        print(f"    ⚠ 無法點擊: {keyword[:30]}")
        return result

    await page.wait_for_timeout(2500)

    if debug:
        safe = "".join(c if c.isalnum() else "_" for c in keyword[:20])
        await page.screenshot(path=f"debug_{safe}.png")

    # Navigated to a detail page?
    navigated = page.url != original_url

    # Try sidebar news first
    news = await _get_external_news_from_page(page)

    if not news:
        # Try search button / Google News fallback
        news = await _try_search_fallback(page, keyword, original_url)

    result["news"] = [
        {"title": n["title"], "title_zh": n["title"], "url": n["url"]} for n in news[:3]
    ]

    # Return to the list page
    if page.url != list_url:
        try:
            await page.goto(list_url, wait_until="domcontentloaded", timeout=25000)
            await page.wait_for_timeout(2000)
        except Exception:
            pass
    elif navigated:
        await page.go_back(wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(1000)
    else:
        # Close sidebar with Escape
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(500)

    return result


# ── Country scraping ──────────────────────────────────────────────────────────

async def scrape_country(
    page: Page, country_code: str, debug: bool = False
) -> list[dict]:
    url = COUNTRY_URLS[country_code]
    print(f"\n[{country_code}] 開啟 {url}")

    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(3000)
    await _dismiss_consent(page)

    if debug:
        await page.screenshot(path=f"debug_{country_code}_list.png")

    keywords = await _get_keywords(page)
    if not keywords:
        print(f"[{country_code}] ⚠ 未找到關鍵字，請開啟 BrowserMode=headed 手動確認")
        if debug:
            content = await page.content()
            Path(f"debug_{country_code}_page.html").write_text(content, encoding="utf-8")
        return []

    print(f"[{country_code}] 找到 {len(keywords)} 個關鍵字，開始擷取新聞...")

    results: list[dict] = []
    list_url = page.url  # May have changed after dismissing consent

    for idx, keyword in enumerate(keywords[:25], 1):
        print(f"  [{idx:02d}/{min(len(keywords), 25)}] {keyword[:40]}")
        item = await _scrape_one_keyword(page, keyword, list_url, debug)
        results.append(item)
        news_count = len(item.get("news", []))
        print(f"       → {news_count} 則新聞")
        await asyncio.sleep(0.3)  # Polite delay

    return results


# ── Browser factory ───────────────────────────────────────────────────────────

async def create_browser(headless: bool = True) -> tuple:
    """Return (playwright_instance, browser, context, page)."""
    p = await async_playwright().start()
    browser: Browser = await p.chromium.launch(
        headless=headless,
        args=["--disable-blink-features=AutomationControlled"],
    )
    context: BrowserContext = await browser.new_context(
        viewport={"width": 1280, "height": 900},
        locale="zh-TW",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    )
    page = await context.new_page()
    return p, browser, context, page


async def close_browser(playwright_instance, browser: Browser) -> None:
    await browser.close()
    await playwright_instance.stop()
