"""Playwright-based Google Trends scraper for TrendReporter.

Flow per country:
  1. Navigate to trending page, wait for Angular rendering
  2. Extract up to 25 keywords
  3. For each keyword:
     a. Click → wait for sidebar/panel to appear
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


# ── Page loading helpers ──────────────────────────────────────────────────────

async def _wait_for_content(page: Page) -> None:
    """Wait for Angular/JS-rendered content to fully appear."""
    try:
        await page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    # Angular needs extra time after network is idle
    await page.wait_for_timeout(6000)


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
                await page.wait_for_timeout(2000)
                return
        except Exception:
            pass


async def _save_debug_html(page: Page, label: str) -> None:
    """Save page HTML and a summary of found elements for debugging."""
    content = await page.content()
    html_path = Path(f"debug_{label}_page.html")
    html_path.write_text(content, encoding="utf-8")

    # Also print a structural summary so the user sees it in terminal
    summary = await page.evaluate("""() => {
        const candidates = [
            'feed-item', 'feed-list', 'trending-searches-list',
            '[class*="trending"]', '[class*="feed"]', '[class*="explore"]',
            'a[href*="/trending"]', 'a[href*="/trends"]',
        ];
        const counts = {};
        for (const sel of candidates) {
            counts[sel] = document.querySelectorAll(sel).length;
        }
        return counts;
    }""")
    non_zero = {k: v for k, v in summary.items() if v > 0}
    print(f"  [debug] 頁面元素: {non_zero}")
    print(f"  [debug] HTML 已儲存: {html_path}")


# ── News extraction helpers ───────────────────────────────────────────────────

async def _get_external_news_from_page(page: Page, limit: int = 3) -> list[dict]:
    """Extract external news links from sidebar or page body."""
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
        const skipWords = ['搜尋', 'Search', '検索', '검색', 'MORE', '更多', 'View more',
                           'Google 搜尋', 'Google Search'];

        const anchors = root.querySelectorAll('a[href^="http"]');
        for (const a of anchors) {
            const href = a.href;
            const text = (a.innerText || a.textContent || '').trim();

            if (!href || !text) continue;
            if (googleHosts.some(h => href.includes(h))) continue;
            if (text.length < 6 || text.length > 350) continue;
            if (seen.has(href)) continue;
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

    clicked = False
    for selector in _SEARCH_BTN_SELECTORS:
        try:
            btn = page.locator(selector).first
            if await btn.count() > 0:
                await btn.click(timeout=4000)
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=15000)
                except Exception:
                    pass
                clicked = True
                break
        except Exception:
            pass

    if not clicked:
        encoded = keyword.replace(" ", "+")
        await page.goto(
            f"https://www.google.com/search?q={encoded}&tbm=nws",
            wait_until="domcontentloaded",
            timeout=20000,
        )

    await page.wait_for_timeout(2000)

    if "tbm=nws" not in page.url:
        for selector in _NEWS_TAB_SELECTORS:
            try:
                tab = page.locator(selector).first
                if await tab.count() > 0:
                    await tab.click(timeout=4000)
                    try:
                        await page.wait_for_load_state("domcontentloaded", timeout=10000)
                    except Exception:
                        pass
                    break
            except Exception:
                pass

    await page.wait_for_timeout(1500)

    news = await page.evaluate(
        """(googleHosts) => {
        const results = [];
        const seen = new Set();
        const selectors = [
            'div[data-news-doc-id] a', '.SoaBEf a', '.WlydOe',
            'g-card a[href^="http"]', 'article a[href^="http"]',
            '.dbsr a', 'a.WlydOe',
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

async def _get_keyword_elements(page: Page) -> list[tuple[str, object]]:
    """Return up to 25 (keyword_text, locator) pairs.

    Tries multiple strategies in order:
      1. Links to /trending/explore pages (most reliable)
      2. feed-item components
      3. JavaScript broad extraction
    """

    # Strategy 1: anchor tags pointing to trending detail pages
    for selector in [
        "a[href*='/trending/explore']",
        "a[href*='/trends/explore']",
        "a[href*='trending/explore']",
        "a[href*='trends/explore']",
    ]:
        elements = await page.locator(selector).all()
        if len(elements) >= 3:
            pairs = []
            for el in elements[:25]:
                try:
                    text = (await el.inner_text()).strip()
                    if text and 2 < len(text) < 200:
                        pairs.append((text, el))
                except Exception:
                    pass
            if len(pairs) >= 3:
                return pairs

    # Strategy 2: feed-item .title sub-elements (various selector variants)
    for title_sel in [
        "feed-item .title a",
        "feed-item .details .title",
        "feed-item .title",
        "feed-item [class*='title']",
        "feed-item a:first-child",
    ]:
        elements = await page.locator(title_sel).all()
        if len(elements) >= 3:
            pairs = []
            for el in elements[:25]:
                try:
                    text = (await el.inner_text()).strip().split("\n")[0].strip()
                    if text and 2 < len(text) < 200:
                        pairs.append((text, el))
                except Exception:
                    pass
            if len(pairs) >= 3:
                return pairs

    # Strategy 3: whole feed-item clicks
    elements = await page.locator("feed-item").all()
    if len(elements) >= 3:
        pairs = []
        for el in elements[:25]:
            try:
                raw = await el.inner_text()
                text = raw.strip().split("\n")[0].strip()
                if text and 2 < len(text) < 200:
                    pairs.append((text, el))
            except Exception:
                pass
        if len(pairs) >= 3:
            return pairs

    # Strategy 4: JavaScript broad extraction
    texts: list[str] = await page.evaluate("""() => {
        // Try links pointing to explore detail pages
        const exploreLinks = Array.from(document.querySelectorAll('a[href]'))
            .filter(a => a.href.includes('/trending/explore') || a.href.includes('/trends/explore'));
        if (exploreLinks.length >= 3) {
            return exploreLinks.slice(0, 25)
                .map(a => a.innerText.trim())
                .filter(t => t && t.length > 2 && t.length < 200);
        }

        // Try feed-item components (Angular custom element)
        const feedItems = document.querySelectorAll('feed-item');
        if (feedItems.length >= 3) {
            return Array.from(feedItems).slice(0, 25).map(item => {
                for (const sel of ['[class*="title"] a', '[class*="title"]', 'a']) {
                    const el = item.querySelector(sel);
                    if (el) {
                        const t = el.innerText.trim().split('\\n')[0].trim();
                        if (t && t.length > 2 && t.length < 200) return t;
                    }
                }
                return item.innerText.trim().split('\\n')[0].trim();
            }).filter(t => t && t.length > 2 && t.length < 200);
        }

        // Last resort: look for any list-like structure with multiple items
        for (const containerSel of ['[class*="trending-list"]', '[class*="feed-list"]', 'main ul', 'main ol']) {
            const container = document.querySelector(containerSel);
            if (!container) continue;
            const items = container.querySelectorAll('li, [class*="item"]');
            if (items.length >= 3) {
                return Array.from(items).slice(0, 25)
                    .map(i => i.innerText.trim().split('\\n')[0].trim())
                    .filter(t => t && t.length > 2 && t.length < 200);
            }
        }
        return [];
    }""")

    return [(t, None) for t in texts[:25]]


# ── Per-keyword scraping ──────────────────────────────────────────────────────

async def _scrape_one_keyword(
    page: Page,
    keyword: str,
    element: object,
    list_url: str,
    idx: int,
    debug: bool,
) -> dict:
    result: dict = {"keyword": keyword, "keyword_zh": keyword, "news": []}
    original_url = page.url

    # Click: prefer the stored element, fall back to get_by_text
    clicked = False

    if element is not None:
        try:
            await element.scroll_into_view_if_needed()
            await element.click(timeout=6000)
            clicked = True
        except Exception:
            pass

    if not clicked:
        for locator in [
            page.locator(f"a[href*='/trending/explore']").nth(idx),
            page.get_by_text(keyword, exact=True).first,
            page.locator(f"text={keyword}").first,
        ]:
            try:
                if await locator.count() > 0:
                    await locator.click(timeout=6000)
                    clicked = True
                    break
            except Exception:
                pass

    if not clicked:
        print(f"    ⚠ 無法點擊: {keyword[:30]}")
        return result

    # ── Wait for sidebar or page change ─────────────────────��────────────────
    # First check if URL changed (navigated to detail page)
    try:
        await page.wait_for_url(lambda url: url != original_url, timeout=4000)
    except Exception:
        pass  # No navigation → sidebar mode

    await page.wait_for_timeout(3000)  # Wait for sidebar/panel to render

    # Try to wait for sidebar to appear
    for sel in _PANEL_SELECTORS + ["[class*='article']", "[class*='news']"]:
        try:
            await page.wait_for_selector(sel, timeout=3000)
            break
        except Exception:
            pass

    if debug:
        safe = "".join(c if c.isalnum() else "_" for c in keyword[:20])
        await page.screenshot(path=f"debug_{safe}.png")

    navigated = page.url != original_url

    # ── Extract news ───────────────────────────────────────────────────────��──
    news = await _get_external_news_from_page(page)

    if not news:
        news = await _try_search_fallback(page, keyword, original_url)

    result["news"] = [
        {"title": n["title"], "title_zh": n["title"], "url": n["url"]} for n in news[:3]
    ]

    # ── Return to list page ───────────────────────────────────────────────────
    if page.url != list_url:
        try:
            await page.goto(list_url, wait_until="domcontentloaded", timeout=25000)
            await page.wait_for_timeout(3000)
        except Exception:
            pass
    elif navigated:
        try:
            await page.go_back(wait_until="domcontentloaded", timeout=15000)
            await page.wait_for_timeout(2000)
        except Exception:
            pass
    else:
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(1000)

    return result


# ── Country scraping ──────────────────────────────────────────────────────────

async def scrape_country(
    page: Page, country_code: str, debug: bool = False
) -> list[dict]:
    url = COUNTRY_URLS[country_code]
    print(f"\n[{country_code}] 開啟 {url}")

    # Load page and wait for Angular rendering
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await _wait_for_content(page)
    await _dismiss_consent(page)
    await page.wait_for_timeout(2000)  # Extra wait after consent dialog

    if debug:
        await page.screenshot(path=f"debug_{country_code}_list.png")
        await _save_debug_html(page, country_code)

    kw_pairs = await _get_keyword_elements(page)

    if not kw_pairs:
        print(f"[{country_code}] ⚠ 未找到關鍵字")
        if not debug:
            # Auto-save debug info on failure even without --debug flag
            await _save_debug_html(page, country_code)
        return []

    keywords = [kw for kw, _ in kw_pairs]
    print(f"[{country_code}] 找到 {len(keywords)} 個關鍵字，開始擷取新聞...")

    list_url = page.url
    results: list[dict] = []

    for idx, (keyword, element) in enumerate(kw_pairs[:25], 1):
        print(f"  [{idx:02d}/{min(len(kw_pairs), 25)}] {keyword[:40]}")
        item = await _scrape_one_keyword(page, keyword, element, list_url, idx - 1, debug)
        results.append(item)
        print(f"       → {len(item.get('news', []))} 則新聞")
        await asyncio.sleep(0.3)

        # Re-anchor list_url in case a redirect happened
        if page.url == list_url and "trending" in page.url:
            pass
        else:
            list_url = url  # Reset to original if drifted

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
