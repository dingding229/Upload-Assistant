"""Client for the shared PT-Gen metadata service."""

from __future__ import annotations

import asyncio
import os
import re
import weakref
from copy import deepcopy
from typing import Any

import httpx


PTGEN_API_URL = "https://ptgen.dingg.de/api/getData"

# Tracker workers may receive deep copies of meta. Share requests by release
# identity, not by the identity of that dict. Each event loop owns its cache.
_caches: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def _imdb_sid(value: Any) -> str:
    """Return an IMDb ``tt`` identifier suitable for PT-Gen, or empty text."""
    raw = str(value or "").strip()
    if raw.lower().startswith("tt"):
        raw = raw[2:]
    return f"tt{raw.zfill(7)}" if raw.isdigit() and int(raw) != 0 else ""


def _get_imdb_sid(meta: dict[str, Any]) -> str:
    """Resolve an IMDb id from the metadata formats used by the upload flow."""
    candidates: list[Any] = [meta.get("imdb_id"), meta.get("imdb")]
    imdb_info = meta.get("imdb_info")
    if isinstance(imdb_info, dict):
        candidates.extend(imdb_info.get(key) for key in ("imdb_id", "id", "imdb"))
        imdb_url = str(imdb_info.get("imdb_url") or "")
        url_match = re.search(r"/title/(tt\d+)", imdb_url, flags=re.IGNORECASE)
        if url_match:
            candidates.append(url_match.group(1))
    for candidate in candidates:
        sid = _imdb_sid(candidate)
        if sid:
            return sid
    return ""


def _trans_titles(payload: dict[str, Any], bbcode: str) -> list[str]:
    aka = payload.get("aka")
    if isinstance(aka, list):
        titles = [str(item).strip() for item in aka if str(item).strip()]
        if titles:
            return titles
    match = re.search(r"^[ \\t]*◎译[　 \\t]*名[：:　 \\t]+(.+)$", bbcode, flags=re.MULTILINE)
    if not match:
        return []
    return [part.strip() for part in re.split(r"\\s*/\\s*", match.group(1)) if part.strip()]


def _main_title(payload: dict[str, Any], bbcode: str) -> str:
    """Return PT-Gen's ``片名`` field, with a formatted-text fallback."""
    title = str(payload.get("chinese_title") or payload.get("title") or "").strip()
    if title:
        return title
    match = re.search(r"^[ \t]*◎[ \t]*片[　 \t]*名[：:　 \t]+(.+)$", bbcode, flags=re.MULTILINE)
    return match.group(1).strip() if match else ""


def build_ptgen_subtitle(ptgen: dict[str, Any], fallback: str = "") -> str:
    """Return only PT-Gen's ``片名``; fall back when it is unavailable."""
    return str(ptgen.get("title") or fallback or "").strip()


async def get_ptgen_meta(meta: dict[str, Any], timeout: float = 30.0) -> dict[str, Any]:
    """Share one request per release/lookup across sequential or parallel trackers.

    Results (including failures) are retained for this run, not written to disk.
    Restarting the run retries failures. Return copies so tracker edits cannot
    affect another tracker. Cancelling a waiter does not cancel the shared fetch.
    """
    loop = asyncio.get_running_loop()
    results, pending = _caches.setdefault(loop, ({}, {}))
    imdb_sid = _get_imdb_sid(meta)
    douban_url = str(meta.get("douban_url") or "").strip()
    lookup = ("imdb", imdb_sid) if imdb_sid else ("douban", douban_url)
    release = str(meta.get("uuid") or meta.get("path") or "")
    if not release:
        # Without release identity, do not accidentally share across torrents.
        return await _fetch_ptgen_meta(meta, timeout)
    key = (os.path.abspath(str(meta.get("base_dir") or ".")), release, lookup)
    if key in results:
        return deepcopy(results[key])

    async def fetch_once() -> dict[str, Any]:
        try:
            result = await _fetch_ptgen_meta(meta, timeout)
            results[key] = result
            return result
        finally:
            pending.pop(key, None)

    if key not in pending:
        pending[key] = loop.create_task(fetch_once())
    return deepcopy(await asyncio.shield(pending[key]))


async def _fetch_ptgen_meta(meta: dict[str, Any], timeout: float) -> dict[str, Any]:
    """Fetch and normalize PT-Gen metadata (uncached transport)."""
    imdb_sid = _get_imdb_sid(meta)
    douban_url = str(meta.get("douban_url") or "").strip()
    if imdb_sid:
        params: dict[str, str] = {"source": "imdb", "sid": imdb_sid}
    elif douban_url:
        params = {"url": douban_url}
    else:
        return {"bbcode": "", "trans_title": [], "douban_url": ""}

    try:
        async with httpx.AsyncClient(
            timeout=float(timeout),
            follow_redirects=True,
            headers={"User-Agent": "Upload-Assistant PT-Gen client"},
        ) as client:
            response = await client.get(PTGEN_API_URL, params=params)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError, TypeError):
        return {"bbcode": "", "trans_title": [], "douban_url": ""}

    if not isinstance(payload, dict) or payload.get("success") is False:
        return {"bbcode": "", "trans_title": [], "douban_url": ""}

    bbcode = str(payload.get("format") or "").strip()
    # Use the full-resolution TMDB poster in tracker descriptions.
    bbcode = re.sub(
        r"(https?://image\.tmdb\.org/t/p/)(?:w\d+|original)/",
        r"\1original/",
        bbcode,
        flags=re.IGNORECASE,
    )
    result = dict(payload)
    result["bbcode"] = bbcode
    result["title"] = _main_title(payload, bbcode)
    result["trans_title"] = _trans_titles(payload, bbcode)
    result["douban_url"] = str(payload.get("douban_link") or douban_url).strip()
    result["region"] = payload.get("region") or []
    result["country"] = payload.get("country") or result["region"]
    return result
