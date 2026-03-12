#!/usr/bin/env python3
"""Search for stock expensive/cheap prices on the Retention & Reinvestment Table.

Supports single and batch mode:
  Single: python search.py --stock-id 2330
  Batch:  python search.py --stock-id 2330 --stock-id 2317

In batch mode, ONE browser is reused for all stocks (much faster).
Single mode outputs a dict, batch mode outputs a JSON array.
"""

import json
import sys
import asyncio
import os
from pathlib import Path
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError, async_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from utils.storage import get_storage_state_path

def _env_int(name: str, default: int, minimum: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, value)


SCRIPT_TIMEOUT_SECONDS = _env_int("SEARCH_SCRIPT_TIMEOUT_SECONDS", 60, 20)
BATCH_TIMEOUT_SECONDS = _env_int("SEARCH_BATCH_TIMEOUT_SECONDS", 120, 30)
NAVIGATION_TIMEOUT_MS = _env_int("SEARCH_NAVIGATION_TIMEOUT_MS", 18000, 5000)
SELECTOR_TIMEOUT_MS = _env_int("SEARCH_SELECTOR_TIMEOUT_MS", 8000, 2000)
SEARCH_BASE_URLS = [
    url.strip().rstrip("/")
    for url in os.getenv("SEARCH_BASE_URLS", "https://stocks.ddns.net,http://stocks.ddns.net").split(",")
    if url.strip()
]


async def _route_handler(route):
    if route.request.resource_type in {"image", "font", "media"}:
        await route.abort()
        return
    await route.continue_()


async def _search_one_stock(page, stock_id: str, base_url: str) -> dict:
    """Search a single stock using an existing page. Returns result dict."""
    try:
        await page.goto(
            f"{base_url}/Screener.aspx",
            wait_until="domcontentloaded",
            timeout=NAVIGATION_TIMEOUT_MS,
        )

        if "login" in page.url.lower():
            return {"status": "error", "message": "Cookies 已過期，請重新執行 scripts/login_save_cookies.py 手動登入。"}

        await page.wait_for_selector("#ctl00_txtGlobalSearch")

        await page.click("#ctl00_txtGlobalSearch")
        await page.fill("#ctl00_txtGlobalSearch", "")
        await page.type("#ctl00_txtGlobalSearch", stock_id, delay=20)

        tw_item = page.locator(f'div.AutoExtenderList:has-text("[TW]"):has-text("{stock_id}")')
        try:
            await tw_item.first.wait_for(state="visible", timeout=5000)
        except PlaywrightTimeoutError:
            pass
        count = await tw_item.count()

        if count == 0:
            return {"status": "error", "message": f"在盈再表搜尋中找不到台灣股票 {stock_id}。"}

        async with page.expect_navigation(wait_until="domcontentloaded", timeout=15000):
            await tw_item.first.click()

        await page.wait_for_selector("#ctl00_ContentPlaceHolder1_GridView2")

        result = await page.evaluate("""(targetId) => {
            const rows = document.querySelectorAll('#ctl00_ContentPlaceHolder1_GridView2 tr');

            for (const row of rows) {
                const cardTitle = row.querySelector('.card-title');
                if (!cardTitle) continue;
                const stockId = cardTitle.textContent.trim();
                if (stockId !== targetId) continue;

                const get = (sel) => {
                    const el = row.querySelector(sel);
                    return el ? el.textContent.trim() : '';
                };

                return {
                    stock_id: stockId,
                    name: get('[id*="ViewlblIndustry"]'),
                    exchange: get('[id*="lblExchange"]'),
                    expected_return: get('[id*="lblIRRPortrait"]'),
                    cheap_price: get('[id*="lblNPVLOWPortrait"]'),
                    expensive_price: get('[id*="lblNPVHIGHPortrait"]'),
                    nav: get('[id*="lblNAVPortrait"]'),
                    found: true,
                };
            }

            return {found: false};
        }""", stock_id)

        if not result.get("found"):
            return {"status": "error", "message": f"在盈再表 Watchlist 中找不到 {stock_id} 的資料。"}

        del result["found"]
        return result
    except PlaywrightTimeoutError:
        return {"status": "error", "message": f"{base_url} 載入逾時"}
    except PlaywrightError as e:
        return {"status": "error", "message": f"{base_url} 連線失敗：{str(e).splitlines()[0]}"}
    except Exception as e:
        return {"status": "error", "message": f"{type(e).__name__}: {e}"}


async def _find_working_base_url(page) -> str | None:
    """Try each base URL and return the first one that loads successfully."""
    for base_url in SEARCH_BASE_URLS:
        try:
            await page.goto(
                f"{base_url}/Screener.aspx",
                wait_until="domcontentloaded",
                timeout=NAVIGATION_TIMEOUT_MS,
            )
            if "login" not in page.url.lower():
                return base_url
        except (PlaywrightTimeoutError, PlaywrightError):
            continue
    return None


async def _search_batch_impl(stock_ids: list[str], state_path: str) -> list[dict]:
    """Search multiple stocks in ONE browser session."""
    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--no-zygote",
                ],
            )
        except Exception as e:
            error = {"status": "error", "message": f"瀏覽器啟動失敗：{type(e).__name__}: {e}"}
            return [error] * len(stock_ids)

        try:
            context = await browser.new_context(
                storage_state=state_path,
                viewport={"width": 1280, "height": 720},
            )
            page = await context.new_page()
            await page.route("**/*", _route_handler)
            page.set_default_timeout(SELECTOR_TIMEOUT_MS)

            # Find a working base URL first
            base_url = await _find_working_base_url(page)
            if base_url is None:
                if "login" in page.url.lower():
                    error = {"status": "error", "message": "Cookies 已過期，請重新執行 scripts/login_save_cookies.py 手動登入。"}
                else:
                    error = {"status": "error", "message": "盈再表查詢失敗：所有網址均無法連線"}
                return [error] * len(stock_ids)

            # Search each stock reusing the same browser/page
            results = []
            for stock_id in stock_ids:
                result = await _search_one_stock(page, stock_id, base_url)
                results.append(result)

            return results
        finally:
            await browser.close()


async def _search_impl(stock_id: str, state_path: str) -> dict:
    """Search a single stock. Kept for backward compatibility."""
    results = await _search_batch_impl([stock_id], state_path)
    return results[0]


async def search(stock_id: str) -> dict:
    """Search a stock and return result dict."""
    state_path = get_storage_state_path()
    if not state_path:
        return {"status": "error", "message": "找不到 storage_state.json，請先執行 scripts/login_save_cookies.py 手動登入。"}
    try:
        return await asyncio.wait_for(_search_impl(stock_id, state_path), timeout=SCRIPT_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        return {
            "status": "error",
            "message": f"盈再表查詢逾時（{SCRIPT_TIMEOUT_SECONDS} 秒），請稍後再試。",
        }


async def search_batch(stock_ids: list[str]) -> list[dict]:
    """Search multiple stocks in one browser session. Returns list of result dicts."""
    state_path = get_storage_state_path()
    if not state_path:
        error = {"status": "error", "message": "找不到 storage_state.json，請先執行 scripts/login_save_cookies.py 手動登入。"}
        return [error] * len(stock_ids)
    timeout = BATCH_TIMEOUT_SECONDS
    try:
        return await asyncio.wait_for(_search_batch_impl(stock_ids, state_path), timeout=timeout)
    except asyncio.TimeoutError:
        return [{"status": "error", "message": f"盈再表批次查詢逾時（{timeout} 秒），請稍後再試。"}] * len(stock_ids)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--stock-id", action="append", required=True, help="股票代號（可多次指定）")
    args = parser.parse_args()

    stock_ids = args.stock_id
    if len(stock_ids) == 1:
        result = asyncio.run(search(stock_ids[0]))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if isinstance(result, dict) and result.get("status") == "error":
            sys.exit(1)
    else:
        results = asyncio.run(search_batch(stock_ids))
        print(json.dumps(results, ensure_ascii=False, indent=2))
        if all(isinstance(r, dict) and r.get("status") == "error" for r in results):
            sys.exit(1)


if __name__ == "__main__":
    main()
