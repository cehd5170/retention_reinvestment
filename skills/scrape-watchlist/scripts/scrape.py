#!/usr/bin/env python3
"""Log into Retention & Reinvestment Table using saved cookies and scrape all stocks' expensive/cheap prices from the Watchlist."""

import json
import os
import sys
import asyncio
import tempfile
from pathlib import Path
from playwright.async_api import async_playwright

STORAGE_STATE_PATH = Path(__file__).resolve().parents[3] / "storage_state.json"


def get_storage_state_path() -> str:
    """Return path to storage_state.json, creating from env var if needed."""
    if STORAGE_STATE_PATH.exists():
        return str(STORAGE_STATE_PATH)
    env_data = os.environ.get("STORAGE_STATE")
    if env_data:
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        tmp.write(env_data)
        tmp.close()
        return tmp.name
    return ""


async def scrape():
    state_path = get_storage_state_path()
    if not state_path:
        print(json.dumps({
            "status": "error",
            "message": "找不到 storage_state.json，請先執行 scripts/login_save_cookies.py 手動登入一次。"
        }, ensure_ascii=False))
        sys.exit(1)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            storage_state=state_path,
            viewport={"width": 1920, "height": 1080},
        )
        page = await context.new_page()

        try:
            await page.goto("https://stocks.ddns.net/App/Watchlist.aspx", wait_until="domcontentloaded", timeout=60000)

            if "login" in page.url.lower():
                print(json.dumps({
                    "status": "error",
                    "message": "Cookies 已過期，請重新執行 scripts/login_save_cookies.py 手動登入。"
                }, ensure_ascii=False))
                sys.exit(1)

            await page.wait_for_selector("#ctl00_ContentPlaceHolder1_GridView2", timeout=15000)

            # Fetch all stock data in one JS call (deduplicated)
            stocks = await page.evaluate("""() => {
                const mainTable = document.getElementById('ctl00_ContentPlaceHolder1_GridView2');
                if (!mainTable) return [];

                const rows = mainTable.querySelectorAll('tr');
                const stocks = [];
                const seen = new Set();

                for (let i = 1; i < rows.length; i++) {
                    const row = rows[i];

                    const exchangeEl = row.querySelector('[id*="lblExchange"]');
                    if (!exchangeEl) continue;
                    const exchange = exchangeEl.textContent.trim();

                    const cardTitle = row.querySelector('.card-title');
                    if (!cardTitle) continue;
                    const stockId = cardTitle.textContent.trim();
                    if (!stockId || seen.has(stockId)) continue;
                    seen.add(stockId);

                    // Company name
                    const nameEl = row.querySelector('[id*="lblStockName"], [id*="lblCompany"], .card-text');
                    let stockName = nameEl ? nameEl.textContent.trim() : '';

                    // ViewtblExp: Expected Return% | Cheap Price | Expensive Price | NAV
                    const expTable = row.querySelector('[id*="ViewtblExpPortrait"]') || row.querySelector('[id*="ViewtblExp"]');
                    let expectedReturn = '', cheapPrice = '', expensivePrice = '', nav = '';
                    if (expTable) {
                        const expRows = expTable.querySelectorAll('tr');
                        if (expRows.length >= 2) {
                            const valueCells = expRows[1].querySelectorAll('td');
                            if (valueCells.length >= 4) {
                                expectedReturn = valueCells[0].textContent.trim();
                                cheapPrice = valueCells[1].textContent.trim();
                                expensivePrice = valueCells[2].textContent.trim();
                                nav = valueCells[3].textContent.trim();
                            }
                        }
                    }

                    stocks.push({
                        stock_id: stockId,
                        name: stockName,
                        exchange: exchange,
                        expected_return: expectedReturn,
                        cheap_price: cheapPrice,
                        expensive_price: expensivePrice,
                        nav: nav,
                    });
                }

                return stocks;
            }""")

        except Exception as e:
            print(json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False))
            sys.exit(1)
        finally:
            await browser.close()

    if not stocks:
        print(json.dumps({
            "status": "info",
            "message": "Watchlist 目前沒有股票。請使用 search-stock 技能搜尋個別股票。",
            "stocks": []
        }, ensure_ascii=False))
    else:
        print(json.dumps(stocks, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(scrape())
