# -*- coding: utf-8 -*-
"""M-Team API uploader (kp.m-team.cc)."""
import os
import time
import uuid
import hashlib
import hmac
from urllib.parse import urlparse
from typing import Any, Optional

import aiofiles
import httpx

from src.console import console
from src.exceptions import UploadException
from src.trackers.COMMON import COMMON


class MTEAM:
    # Values used by the official web client.  The API gateway validates these
    # even though they are not represented in the generated OpenAPI schema.
    _CLIENT_SECRET = "HLkPcWmycL57mfJt"
    _CLIENT_VERSION = "1.1.7"
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.tracker = "MTEAM"
        self.source_flag = "M-Team"
        c = config.get("TRACKERS", {}).get("MTEAM", {})
        self.base_url = str(c.get("api_base", "https://kp.m-team.cc/api")).rstrip("/")
        self.api_key = str(c.get("api_key", c.get("authorization", ""))).strip()
        self.visitor_id = str(c.get("visitor_id", "")).strip() or str(uuid.uuid4())
        self.did = str(c.get("did", "")).strip()
        self.version = str(c.get("version", self._CLIENT_VERSION)).strip()
        self.web_version = str(c.get("web_version", "1170")).strip()
        self.announce_url = str(c.get("announce_url", "https://kp.m-team.cc/announce")).strip()
        self.source = str(c.get("source", 1)).strip()
        self.banned_groups: list[str] = []

    async def validate_credentials(self, _meta: dict[str, Any]) -> bool:
        return bool(self.api_key)

    async def search_existing(self, _meta: dict[str, Any], _disctype: str) -> list[dict[str, Any]]:
        """M-Team's search schema is account/version dependent; skip safely when unavailable."""
        return []

    async def _get_mediainfo_file(self, meta: dict[str, Any]) -> str:
        """Read the shared complete BDInfo/MediaInfo report prepared by DiscParse."""
        tmp = os.path.join(meta["base_dir"], "tmp", meta["uuid"])
        if meta.get("is_disc") == "BDMV":
            candidates = [os.path.join(tmp, "BDINFO.txt")]
        else:
            candidates = [os.path.join(tmp, "MEDIAINFO_CLEANPATH.txt")]
        for path in candidates:
            if os.path.isfile(path):
                async with aiofiles.open(path, encoding="utf-8", errors="replace") as f:
                    return await f.read()
        return str(meta.get("mediainfo", ""))

    def _ids(self, meta: dict[str, Any]) -> dict[str, int]:
        c = self.config.get("TRACKERS", {}).get("MTEAM", {})
        maps = c.get("ids", {}) if isinstance(c.get("ids", {}), dict) else {}
        def val(key: str, default: int) -> int:
            x = maps.get(key, default)
            try: return int(x)
            except (TypeError, ValueError): return default
        typ = str(meta.get("type", ""))
        medium_default = {"REMUX": 3, "WEBDL": 4, "WEBRIP": 5, "HDTV": 6, "ENCODE": 5}.get(typ, 1)
        return {
            "category": val("movie_category" if meta.get("category") == "MOVIE" else "tv_category", 1 if meta.get("category") == "MOVIE" else 2),
            "source": val("source", int(self.source) if self.source.isdigit() else 1),
            "medium": val("medium", medium_default),
            "standard": val("standard", 1),
            "videoCodec": val("videoCodec", 1), "audioCodec": val("audioCodec", 1),
            "team": val("team", 0), "processing": val("processing", 0),
        }

    def _headers(self, timestamp_ms: int) -> dict[str, str]:
        headers = {"Accept": "application/json", "User-Agent": "Upload-Assistant/MTEAM"}
        if self.api_key:
            # Enter the exact value from the site's API configuration (including
            # ``Bearer `` when the site supplies that prefix).
            headers["authorization"] = self.api_key
        headers["visitorId"] = self.visitor_id
        headers["version"] = self.version
        headers["webVersion"] = self.web_version
        headers["ts"] = str(timestamp_ms // 1000)
        if self.did:
            headers["did"] = self.did
        return headers

    async def upload(self, meta: dict[str, Any], _disctype: str) -> Optional[bool]:
        common = COMMON(self.config)
        await common.create_torrent_for_upload(meta, self.tracker, self.source_flag)
        desc_path = f"{meta['base_dir']}/tmp/{meta['uuid']}/[{self.tracker}]DESCRIPTION.txt"
        if not os.path.isfile(desc_path):
            # M-Team does not need a tracker-specific description transform;
            # use the common prepared description when one is not present.
            desc_path = f"{meta['base_dir']}/tmp/{meta['uuid']}/DESCRIPTION.txt"
        torrent_path = f"{meta['base_dir']}/tmp/{meta['uuid']}/[{self.tracker}].torrent"
        async with aiofiles.open(desc_path, encoding="utf-8") as f: descr = await f.read()
        async with aiofiles.open(torrent_path, "rb") as f: torrent = await f.read()
        ids = self._ids(meta)
        name = str(meta.get("name", ""))[:255]
        small = str(meta.get("imdb_info", {}).get("title") or meta.get("title", ""))[:255]
        imdb = str(meta.get("imdb_info", {}).get("imdb_url") or "")
        douban = str(meta.get("douban_url") or meta.get("douban", "") or "")
        mediainfo = await self._get_mediainfo_file(meta)
        data: dict[str, Any] = {"name": name, "smallDescr": small, "descr": descr,
            **ids, "countries": str(meta.get("region", "")), "imdb": imdb, "douban": douban,
            "anonymous": bool(meta.get("anon", 0)), "tags": str(meta.get("tag", "")),
            "mediainfo": mediainfo, "mediaInfoAnalysisResult": False}
        files = {"file": (os.path.basename(torrent_path), torrent, "application/x-bittorrent")}
        if meta.get("debug"):
            console.print(f"[cyan]MTEAM API: {self.base_url}/torrent/createOredit[/cyan]")
            console.print(data)
            meta["tracker_status"][self.tracker]["status_message"] = "Debug mode enabled, not uploading."
            return True
        path = "/torrent/createOredit"
        timestamp_ms = int(time.time() * 1000)
        sign_path = urlparse(self.base_url + path).path
        sign_text = f"POST&{sign_path}&{timestamp_ms}"
        data["_timestamp"] = str(timestamp_ms)
        data["_sign"] = hmac.new(self._CLIENT_SECRET.encode(), sign_text.encode(), hashlib.sha1).hexdigest()
        try:
            async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
                r = await client.post(self.base_url + path, data=data, files=files, headers=self._headers(timestamp_ms))
            payload = r.json() if "json" in r.headers.get("content-type", "") else {}
            if r.status_code >= 400 or (isinstance(payload, dict) and payload.get("code") not in (None, 0, 200)):
                raise UploadException(f"M-Team upload failed: {payload.get('message', r.text[:300])}", "red")
            result = payload.get("data") if isinstance(payload, dict) else None
            tid = result.get("id") if isinstance(result, dict) else result
            url = str(result.get("url")) if isinstance(result, dict) and result.get("url") else (f"https://kp.m-team.cc/detail/{tid}" if tid else "https://kp.m-team.cc")
            meta["tracker_status"][self.tracker]["status_message"] = url
            if tid: meta["tracker_status"][self.tracker]["torrent_id"] = str(tid)
            await common.create_torrent_ready_to_seed(meta, self.tracker, self.source_flag, self.announce_url, comment=url)
            return True
        except UploadException: raise
        except Exception as e:
            raise UploadException(f"M-Team upload request failed: {e}", "red")
