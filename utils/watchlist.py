"""Watchlist persistence via Supabase."""

import logging

from supabase import create_client

import config

logger = logging.getLogger(__name__)

_client = None


def get_client():
    global _client
    if _client is None:
        _client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
    return _client


def add_stock(user_id: str, stock_id: str) -> bool:
    """Add a stock to user's watchlist. Returns False if already exists."""
    client = get_client()
    try:
        existing = (
            client.table("watchlist")
            .select("id")
            .eq("user_id", user_id)
            .eq("stock_id", stock_id)
            .execute()
        )
        if existing.data:
            return False
        client.table("watchlist").insert(
            {"user_id": user_id, "stock_id": stock_id}
        ).execute()
        return True
    except Exception as e:
        logger.error("add_stock failed for user=%s stock=%s: %s", user_id, stock_id, e)
        raise


def remove_stock(user_id: str, stock_id: str) -> bool:
    """Remove a stock from user's watchlist. Returns False if not found."""
    client = get_client()
    try:
        result = (
            client.table("watchlist")
            .delete()
            .eq("user_id", user_id)
            .eq("stock_id", stock_id)
            .execute()
        )
        return len(result.data) > 0
    except Exception as e:
        logger.error("remove_stock failed for user=%s stock=%s: %s", user_id, stock_id, e)
        raise


def list_stocks(user_id: str) -> list[str]:
    """Get all stock IDs for a user."""
    client = get_client()
    try:
        result = (
            client.table("watchlist")
            .select("stock_id")
            .eq("user_id", user_id)
            .order("created_at")
            .execute()
        )
        return [row["stock_id"] for row in result.data]
    except Exception as e:
        logger.error("list_stocks failed for user=%s: %s", user_id, e)
        raise


def get_all_users_with_stocks() -> dict[str, list[str]]:
    """Get all users and their tracked stocks. Returns {user_id: [stock_ids]}."""
    client = get_client()
    try:
        result = (
            client.table("watchlist")
            .select("user_id, stock_id")
            .order("user_id")
            .execute()
        )
        users: dict[str, list[str]] = {}
        for row in result.data:
            users.setdefault(row["user_id"], []).append(row["stock_id"])
        return users
    except Exception as e:
        logger.error("get_all_users_with_stocks failed: %s", e)
        raise
