"""Direct stock lookup — bypasses LLM agent for simple queries.

Runs search-stock and get-stock-price in parallel, then compares
prices programmatically. ~20-30 seconds instead of ~180 seconds.
"""

import asyncio
import json
import subprocess
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parents[1] / "skills"


async def _run_script(cmd: list[str], timeout: int = 60) -> dict | list | None:
    """Run a skill script as subprocess and parse JSON output."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return None

    if proc.returncode != 0:
        return None

    try:
        return json.loads(stdout.decode())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


async def quick_analyze(stock_ids: list[str]) -> str:
    """Analyze stocks directly without LLM. Returns formatted text."""
    python = sys.executable
    search_script = str(SKILLS_DIR / "search-stock" / "scripts" / "search.py")
    price_script = str(SKILLS_DIR / "get-stock-price" / "scripts" / "get_price.py")

    # Run all lookups in parallel
    search_tasks = [
        _run_script([python, search_script, "--stock-id", sid])
        for sid in stock_ids
    ]
    price_args = [python, price_script]
    for sid in stock_ids:
        price_args.extend(["--stock-id", sid])
    price_task = _run_script(price_args)

    # Wait for all results concurrently
    results = await asyncio.gather(*search_tasks, price_task)

    search_results = results[:-1]
    price_data = results[-1]

    # Build price lookup
    prices = {}
    if isinstance(price_data, list):
        for p in price_data:
            prices[p["stock_id"]] = p

    # Format output
    lines = []
    for sid, search in zip(stock_ids, search_results):
        if not search or isinstance(search, dict) and search.get("status") == "error":
            err_msg = search.get("message", "查詢失敗") if search else "查詢逾時"
            lines.append(f"❌ {sid}: {err_msg}")
            lines.append("")
            continue

        name = search.get("name", "")
        cheap = _parse_float(search.get("cheap_price", ""))
        expensive = _parse_float(search.get("expensive_price", ""))

        price_info = prices.get(sid, {})
        current = _parse_float(price_info.get("price", ""))
        stock_name = price_info.get("name", name)

        # Determine recommendation
        if current is not None and expensive is not None and current >= expensive:
            rec, emoji = "賣出", "🔴"
            reasoning = f"現價 {current} ≥ 貴價 {expensive}"
        elif current is not None and cheap is not None and current <= cheap:
            rec, emoji = "買入", "🟢"
            reasoning = f"現價 {current} ≤ 淑價 {cheap}"
        elif current is not None:
            rec, emoji = "持有", "⚪"
            reasoning = f"淑價 {cheap} < 現價 {current} < 貴價 {expensive}"
        else:
            rec, emoji = "無法判斷", "❓"
            reasoning = "無法取得即時價格"

        lines.append(f"{emoji} {sid} {stock_name}")
        price_str = f"  現價:{current}" if current else "  現價:N/A"
        cheap_str = f" 淑價:{cheap}" if cheap else ""
        exp_str = f" 貴價:{expensive}" if expensive else ""
        lines.append(f"{price_str}{cheap_str}{exp_str}")
        lines.append(f"  建議：{rec}")
        lines.append(f"  {reasoning}")
        lines.append("")

    return "\n".join(lines).strip() if lines else "查無資料"


def _parse_float(val: str | None) -> float | None:
    """Parse a string to float, return None on failure."""
    if not val:
        return None
    try:
        return float(val.replace(",", ""))
    except (ValueError, AttributeError):
        return None
