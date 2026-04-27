"""Playwright-based Google Trends scraper for TrendReporter.

KEY INSIGHT (discovered from debug):
  The /trending page uses Angular. "Explore" buttons are
  a[href*="/trends/explore"] links with innerText = "query_stats探索"
  (Material Icon name + label).  The actual trending keyword is stored in
  the ?q= URL parameter of those same links.
  We decode q= to get clean keyword strings, then click feed-item
  elements by index position to open the sidebar.

Flow per country:
  1. Navigate → wait for Angular rendering
  2. Extract keywords from ?q= of /trends/explore links
  3. For each keyword (click by index):
     a. Click feed-item → wait for sidebar
     b. Extract top-3 external news links from sidebar
     c. If none → Google Search News fallback
  4. Return raw data (no translation yet)
"""

import asyncio
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
)


COUNTRY_URLS = {
    "JP": "https://trends.google.com.tw/trending?geo=JP&hours=4",
    "KR": "https://trends.google.com.tw/trending?geo=KR&hours=4",
    "HK": "https://trends.google.com.tw/trending?geo=HK&hours=4",
    "TW": "https://trends.google.com.tw/trending?geo=TW&hours=4",
}

COUNTRY_ORDER = ["JP", "KR", "HK", "TW"]

_GOOGLE_HOSTS = ("trends.google", "google.com", "googleapis.com", "goo.gl", "google.co")

_PANEL_SELECTORS = [
    "explore-sidebar",
    ".explore-sidebar",
    "[class*='sidebar']",
    "[class*='detail-panel']",
    "[class*='details-panel']",
]

_SEARCH_BTN_SELECTORS = [
    "button:has-text('Google 搜尋')",
    "button:has-text('Google Search')",
    "button:has-text('Google検索')",
    "button:has-text('Google 검색')",
    "a:has-text('Google Search')",
]

_NEWS_TAB_SELECTORS = [
    "a[href*='tbm=nws']",
    "div[role='tab']:has-text('新聞')",
    "div[role='tab']:has-text('News')",
    "div[role='tab']:has-text('ニュース')",
    "div[role='tab']:has-text('뉴스')",
]


# ── Page load / consent ───────────────────────────────────────────────────────

async def _wait_for_content(page: Page) -> None:
    try:
        await page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    await page.wait_for_timeout(6000)


_ROW_SELECTOR = 'tr[jsname="oKdM2c"]'   # Wiz table row (new structure)
_KW_SELECTOR   = "div.mZ3RIc"            # keyword text cell (new structure)


async def _scroll_to_load_keywords(page: Page, target: int = 25) -> None:
    """Wheel-scroll down until `target` trend rows appear in DOM."""
    for _ in range(20):
        wiz = await page.locator(_ROW_SELECTOR).count()
        ang = await page.locator("feed-item").count()
        if max(wiz, ang) >= target:
            break
        await page.mouse.wheel(0, 700)
        await page.wait_for_timeout(1000)


async def _ensure_row(page: Page, idx: int) -> None:
    """Scroll until row at `idx` is present in DOM (either structure)."""
    for _ in range(10):
        wiz = await page.locator(_ROW_SELECTOR).count()
        ang = await page.locator("feed-item").count()
        if max(wiz, ang) > idx:
            break
        await page.mouse.wheel(0, 600)
        await page.wait_for_timeout(800)


async def _dismiss_consent(page: Page) -> None:
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


# ── Debug helpers ─────────────────────────────────────────────────────────────

async def _save_debug_html(page: Page, label: str) -> None:
    content = await page.content()
    html_path = Path(f"debug_{label}_page.html")
    html_path.write_text(content, encoding="utf-8")

    summary = await page.evaluate("""() => {
        const candidates = [
            'tr[jsname="oKdM2c"]', 'div.mZ3RIc',
            'feed-item', 'feed-list',
            'a[href*="/trends/explore"]', 'a[href*="/trending/explore"]',
        ];
        const counts = {};
        for (const s of candidates) {
            const n = document.querySelectorAll(s).length;
            if (n > 0) counts[s] = n;
        }
        return counts;
    }""")
    print(f"  [debug] 頁面元素計數: {summary}")
    print(f"  [debug] HTML 已儲存: {html_path}")


# ── Keyword extraction ────────────────────────────────────────────────────────

async def _extract_keywords(page: Page) -> list[str]:
    """Extract up to 25 trending keywords.

    Strategy 1 (primary): Wiz table — read text from div.mZ3RIc cells.
    Strategy 2 (Angular fallback): first explore link per feed-item.
    Strategy 3 (Angular fallback): feed-item clone text.
    """

    # ── Strategy 1: Wiz table structure (new) ────────────────────────────────
    keywords: list[str] = await page.evaluate("""() => {
        const cells = document.querySelectorAll('div.mZ3RIc');
        if (cells.length < 3) return [];
        const results = [];
        for (const cell of cells) {
            const t = (cell.innerText || cell.textContent || '').trim();
            if (t.length >= 2 && t.length <= 200) results.push(t);
            if (results.length >= 25) break;
        }
        return results;
    }""")

    if len(keywords) >= 3:
        print(f"  [keyword] Strategy 1 (Wiz mZ3RIc): {len(keywords)} 個")
        return keywords

    # ── Strategy 2: first explore link per feed-item (Angular) ───────────────
    keywords = await page.evaluate("""() => {
        const results = [];
        const seen = new Set();
        const feedItems = document.querySelectorAll('feed-item');
        for (const item of feedItems) {
            const links = item.querySelectorAll(
                'a[href*="/trends/explore"], a[href*="/trending/explore"]'
            );
            for (const a of links) {
                try {
                    const url = new URL(a.href);
                    const q = url.searchParams.get('q');
                    if (!q || q.length < 2 || q.length > 200) continue;
                    if (seen.has(q)) continue;
                    seen.add(q);
                    results.push(q);
                } catch (e) {}
                break;  // only first explore link per feed-item
            }
            if (results.length >= 25) break;
        }
        return results;
    }""")

    if len(keywords) >= 3:
        print(f"  [keyword] Strategy 2 (Angular feed-item): {len(keywords)} 個")
        return keywords

    # ── Strategy 3: feed-item clone text (Angular fallback) ──────────────────
    items = await page.locator("feed-item").all()
    results = []
    for el in items[:25]:
        try:
            text = await el.evaluate("""el => {
                const clone = el.cloneNode(true);
                clone.querySelectorAll('a, mat-icon').forEach(n => n.remove());
                const lines = clone.innerText.trim().split('\\n')
                    .map(l => l.trim())
                    .filter(l => l.length > 2 && !/^\\d+$/.test(l));
                return lines[0] || '';
            }""")
            if text and 2 < len(text) < 200:
                results.append(text)
        except Exception:
            pass

    if results:
        print(f"  [keyword] Strategy 3 (Angular clone): {len(results)} 個")
    return results[:25]


# ── News extraction ───────────────────────────────────────────────────────────

async def _get_external_news(page: Page, limit: int = 3) -> list[dict]:
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
        const skipWords = ['搜尋','Search','検索','검색','MORE','更多',
                           'Google 搜尋','Google Search','View more','探索','Explore'];
        for (const a of root.querySelectorAll('a[href^="http"]')) {
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


async def _news_via_google_search(page: Page, keyword: str) -> list[dict]:
    """Direct Google News search — used when sidebar has no news."""
    encoded = keyword.replace(" ", "+")
    await page.goto(
        f"https://www.google.com/search?q={encoded}&tbm=nws",
        wait_until="domcontentloaded",
        timeout=20000,
    )
    await page.wait_for_timeout(2000)

    # If not on news tab, click it
    if "tbm=nws" not in page.url:
        for sel in _NEWS_TAB_SELECTORS:
            try:
                tab = page.locator(sel).first
                if await tab.count() > 0:
                    await tab.click(timeout=4000)
                    await page.wait_for_timeout(1500)
                    break
            except Exception:
                pass

    return await page.evaluate(
        """(googleHosts) => {
        const results = [];
        const seen = new Set();
        for (const sel of ['div[data-news-doc-id] a','.SoaBEf a','.WlydOe',
                            'g-card a[href^="http"]','article a[href^="http"]']) {
            for (const a of document.querySelectorAll(sel)) {
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


# ── Per-keyword scraping ──────────────────────────────────────────────────────

async def _scrape_one_keyword(
    page: Page,
    keyword: str,
    idx: int,          # 0-based index in feed-item list
    list_url: str,
    debug: bool,
) -> dict:
    result: dict = {"keyword": keyword, "keyword_zh": keyword, "news": []}
    original_url = page.url

    # ── Click the row at this index ───────────────────────────────────────────
    # Try Wiz table rows first, then Angular feed-items as fallback.
    # Click the left 35% to avoid hitting action buttons on the right.
    clicked = False
    click_err = ""

    for locator_str in [_ROW_SELECTOR, "feed-item"]:
        try:
            rows = await page.locator(locator_str).all()
            if idx < len(rows):
                el = rows[idx]
                await el.scroll_into_view_if_needed()
                await page.wait_for_timeout(400)
                bbox = await el.bounding_box()
                if bbox:
                    x = min(bbox["width"] * 0.35, 250)
                    y = bbox["height"] * 0.5
                    await el.click(position={"x": x, "y": y}, timeout=6000)
                else:
                    await el.click(timeout=6000)
                clicked = True
                break
            else:
                click_err = f"{locator_str} 只有 {len(rows)} 個，索引 {idx} 超出範圍"
        except Exception as e:
            click_err = str(e)[:80]

    # Fallback: click by keyword text
    if not clicked:
        for loc in [
            page.get_by_text(keyword, exact=True).first,
            page.locator(f"text={keyword}").first,
        ]:
            try:
                if await loc.count() > 0:
                    await loc.scroll_into_view_if_needed()
                    await loc.click(timeout=6000)
                    clicked = True
                    break
            except Exception:
                pass

    if not clicked:
        print(f"    → 改用 Google News 搜尋" + (f" ({click_err})" if click_err else ""))
        news = await _news_via_google_search(page, keyword)
        result["news"] = [{"title": n["title"], "title_zh": n["title"], "url": n["url"]} for n in news[:3]]
        if page.url != list_url:
            await page.goto(list_url, wait_until="domcontentloaded", timeout=25000)
            await page.wait_for_timeout(3000)
        return result

    # ── Wait for sidebar / page change ────────────────────────────────────────
    try:
        await page.wait_for_url(lambda url: url != original_url, timeout=4000)
    except Exception:
        pass  # no navigation → sidebar mode

    await page.wait_for_timeout(3000)

    for sel in _PANEL_SELECTORS + ["[class*='article']", "[class*='news-item']"]:
        try:
            await page.wait_for_selector(sel, timeout=3000)
            break
        except Exception:
            pass

    if debug:
        safe = "".join(c if c.isalnum() else "_" for c in keyword[:20])
        await page.screenshot(path=f"debug_{safe}.png")

    navigated = page.url != original_url

    # ── Extract news ──────────────────────────────────────────────────────────
    news = await _get_external_news(page)

    if not news:
        # Try clicking search button inside sidebar first
        for sel in _SEARCH_BTN_SELECTORS:
            try:
                btn = page.locator(sel).first
                if await btn.count() > 0:
                    await btn.click(timeout=4000)
                    await page.wait_for_timeout(2000)
                    news = await _get_external_news(page)
                    break
            except Exception:
                pass

    if not news:
        news = await _news_via_google_search(page, keyword)

    result["news"] = [{"title": n["title"], "title_zh": n["title"], "url": n["url"]} for n in news[:3]]

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

async def scrape_country(page: Page, country_code: str, debug: bool = False) -> list[dict]:
    url = COUNTRY_URLS[country_code]
    print(f"\n[{country_code}] 開啟 {url}")

    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await _wait_for_content(page)
    await _dismiss_consent(page)
    await page.wait_for_timeout(2000)

    if debug:
        await page.screenshot(path=f"debug_{country_code}_list.png")
        await _save_debug_html(page, country_code)

    # Wait for at least one trend row to appear (either Wiz or Angular)
    for sel in [_ROW_SELECTOR, _KW_SELECTOR, "feed-item"]:
        try:
            await page.wait_for_selector(sel, timeout=15000)
            break
        except Exception:
            pass

    print(f"[{country_code}] 捲動載入所有關鍵字...")
    await _scroll_to_load_keywords(page, target=25)

    keywords = await _extract_keywords(page)

    if not keywords:
        print(f"[{country_code}] ⚠ 未找到關鍵字")
        await _save_debug_html(page, country_code)
        return []

    print(f"[{country_code}] 找到 {len(keywords)} 個關鍵字，開始擷取新聞...")

    list_url = page.url
    results: list[dict] = []

    for idx, keyword in enumerate(keywords[:25]):
        print(f"  [{idx+1:02d}/{min(len(keywords), 25)}] {keyword[:40]}")
        await _ensure_row(page, idx)
        item = await _scrape_one_keyword(page, keyword, idx, list_url, debug)
        results.append(item)
        print(f"       → {len(item.get('news', []))} 則新聞")
        await asyncio.sleep(0.3)

    return results


# ── Browser factory ───────────────────────────────────────────────────────────

async def create_browser(headless: bool = True) -> tuple:
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
