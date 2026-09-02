"""Client for the shared PT-Gen metadata service."""

from __future__ import annotations

import re
from typing import Any

import httpx


PTGEN_API_URL = "https://ptgen.dingg.de/api/getData"


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


async def get_ptgen_meta(meta: dict[str, Any], timeout: float = 30.0) -> dict[str, Any]:
    """Fetch and normalize PT-Gen metadata for a release."""
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
    result["trans_title"] = _trans_titles(payload, bbcode)
    result["douban_url"] = str(payload.get("douban_link") or douban_url).strip()
    result["region"] = payload.get("region") or []
    result["country"] = payload.get("country") or result["region"]
    return result
