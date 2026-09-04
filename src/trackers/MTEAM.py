# Upload Assistant © 2025 Audionut & wastaken7 — Licensed under UAPL v1.0
import os
import re
from typing import Any, Optional, cast

import aiofiles
import httpx

from cogs.redaction import Redaction
from src.console import console
from src.exceptions import UploadException
from src.ptgen_api import get_ptgen_meta
from src.trackers.COMMON import COMMON

Meta = dict[str, Any]
Config = dict[str, Any]


class MTEAM:
    """
    https://test2.m-team.cc/api/swagger-ui/index.html
    https://wiki.m-team.cc/zh-tw/api
    """

    def __init__(self, config: Config):
        self.config = config
        self.common = COMMON(config)
        self.tracker = "MTEAM"
        self.base_url = "https://kp.m-team.cc"
        self.api_base_url = str(self.config["TRACKERS"][self.tracker].get("api_base_url", "")).strip().rstrip("/")
        self.torrent_url = f"{self.base_url}/detail/"
        self.banned_groups = [""]
        self.api_key = str(self.config["TRACKERS"][self.tracker].get("api_key") or "").strip()
        self.session = httpx.AsyncClient(
            headers={
                "x-api-key": self.api_key,
                "Accept": "*/*",
            },
            timeout=30.0,
        )

    async def mediainfo(self, meta: Meta) -> str:
        mi_path: str = ""
        mediainfo: str = ""

        if meta.get("is_disc") == "BDMV":
            mi_path = os.path.join(meta["base_dir"], "tmp", meta["uuid"], "BDINFO.txt")
        else:
            mi_path = f"{meta['base_dir']}/tmp/{meta['uuid']}/MEDIAINFO_CLEANPATH.txt"

        if mi_path:
            async with aiofiles.open(mi_path, encoding="utf-8") as f:
                mediainfo = await f.read()

        return mediainfo

    def bbcode_to_markdown(self, text):
        specific_img_pattern = r"\[url=[^\]]*\]\[img(?:=[^\]]*)?\](.*?)\[/img\]\[/url\]"
        text = re.sub(specific_img_pattern, r"![](\1)", text, flags=re.IGNORECASE)

        patterns = [
            (r"\[b\](.*?)\[/b\]", r"**\1**"),
            (r"\[i\](.*?)\[/i\]", r"*\1*"),
            (r"\[u\](.*?)\[/u\]", r"<u>\1</u>"),
            (r"\[s\](.*?)\[/s\]", r"~~\1~~"),
            (r"\[img(?:=[^\]]*)?\](.*?)\[/img\]", r"![](\1)"),
            (r"\[url=(.*?)\](.*?)\[/url\]", r"[\2](\1)"),
            (r"\[url\](.*?)\[/url\]", r"<\1>"),
        ]

        for pattern, replacement in patterns:
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE | re.DOTALL)

        return text

    def mteam_standard_desc(self, meta: Meta):
        imdb = meta.get("imdb_info", {})

        tmdb_poster = f"https://image.tmdb.org/t/p/w200{meta.get('tmdb_poster')}"
        poster_url = tmdb_poster if tmdb_poster else imdb.get("cover", "")
        title = meta.get("title", "N/A")
        year = meta.get("year", "N/A")
        rating = imdb.get("rating", "N/A")

        writers = imdb.get("writers", [])
        creators_str = " / ".join(writers)

        cast = meta.get("tmdb_cast", [])
        actors_str = " / ".join(cast)

        plot = imdb.get("plot", meta.get("overview", ""))

        desc = [
            f"![]({poster_url})",
            "",
            f"**Title**: {title}",
            f"**Year**: {year}",
            f"**IMDb Rating**: {rating}/10",
            f"**Creators**: {creators_str}",
            f"**Actors**: {actors_str}",
            "",
            "### Introduction",
            "",
            f"  {plot}",
        ]

        return "\n".join(desc)

    async def generate_description(self, meta: Meta) -> str:
        ext_meta = meta.get("ptgen")
        if not isinstance(ext_meta, dict):
            ext_meta = await get_ptgen_meta(meta)
            meta["ptgen"] = ext_meta
        desc_parts: list[str] = []
        if ext_meta.get("bbcode"):
            desc_parts.append(str(ext_meta["bbcode"]).strip())
        # M-Team receives MediaInfo/BDInfo through the dedicated API field;
        # it must not be duplicated in the public description.
        images = meta.get("image_list", [])
        if isinstance(images, list):
            desc_parts.extend(
                f"[img]{image['raw_url']}[/img]"
                for image in images
                if isinstance(image, dict) and image.get("raw_url")
            )
        description = "\n\n".join(part for part in desc_parts if part.strip()).strip()

        async with aiofiles.open(f"{meta['base_dir']}/tmp/{meta['uuid']}/[{self.tracker}]DESCRIPTION.txt", "w", encoding="utf-8") as description_file:
            await description_file.write(description)

        return description

    def get_category_id(self, meta: Meta) -> Optional[int]:
        movie_sd = 401  # Movie/SD
        movie_hd = 419  # Movie/HD
        movie_dvdiso = 420  # Movie/DVDiSo
        movie_blu_ray = 421  # Movie/Blu-Ray
        movie_remux = 439  # Movie/Remux
        tv_series_sd = 403  # TV Series/SD
        tv_series_hd = 402  # TV Series/HD
        tv_series_bd = 438  # TV Series/BD
        tv_series_dvdiso = 435  # TV Series/DVDiSo
        anime = 405  # Anime

        is_sd = meta.get("sd", False)
        is_dvd = meta.get("is_disc") == "DVD"
        is_bd = meta.get("is_disc") == "BDMV"
        is_remux = meta.get("type", "") == "REMUX"
        is_anime = meta.get("anime", False)

        if is_anime:
            return anime

        if is_bd:
            return tv_series_bd if meta["category"] == "TV" else movie_blu_ray

        if is_remux and meta["category"] == "MOVIE":
            return movie_remux

        if is_dvd:
            return tv_series_dvdiso if meta["category"] == "TV" else movie_dvdiso

        if is_sd:
            return tv_series_sd if meta["category"] == "TV" else movie_sd

        # Default to HD
        return tv_series_hd if meta["category"] == "TV" else movie_hd

    def get_small_description(self, meta: Meta) -> str:
        resolution = meta.get("resolution", "")
        audio = meta.get("audio", "")
        video_bitrate, audio_bitrate = self.get_bitrates(meta)

        return f"{resolution} @ {video_bitrate} kbps - {audio} @ {audio_bitrate} kbps"

    def get_bitrates(self, meta) -> tuple[int, int]:
        v_raw = None
        a_raw = None
        is_bdmv = meta.get("is_disc") == "BDMV"
        is_dvd = meta.get("is_disc") == "DVD"

        if is_bdmv:
            discs = meta.get("discs", [])
            if discs:
                bdinfo = discs[0].get("bdinfo", {})
                v_tracks = bdinfo.get("video", [])
                a_tracks = bdinfo.get("audio", [])
                if v_tracks:
                    v_raw = v_tracks[0].get("bitrate")
                if a_tracks:
                    a_raw = a_tracks[0].get("bitrate")
        elif is_dvd:
            pass
        else:
            tracks = meta.get("mediainfo", {}).get("media", {}).get("track", [])
            for track in tracks:
                t_type = track.get("@type")
                if t_type == "Video" and v_raw is None:
                    v_raw = track.get("BitRate")
                elif t_type == "Audio" and a_raw is None:
                    a_raw = track.get("BitRate")

        def clean_to_int(val, bdmv_mode):
            if not val or isinstance(val, dict):
                return 0

            try:
                if bdmv_mode:
                    numeric_match = re.search(r"\d+", str(val).replace(".", "").replace(",", ""))
                    return int(numeric_match.group()) if numeric_match else 0
                else:
                    return int(val) // 1000
            except (ValueError, TypeError, AttributeError):
                return 0

        return (clean_to_int(v_raw, is_bdmv), clean_to_int(a_raw, is_bdmv))

    async def search_existing(self, meta: dict[str, Any], _) -> list[dict[str, Any]]:
        if not self.api_base_url:
            return []
        imdb_info = meta.get("imdb_info") if isinstance(meta.get("imdb_info"), dict) else {}
        imdb_id = str(
            imdb_info.get("imdbID")
            or imdb_info.get("imdb_id")
            or imdb_info.get("id")
            or meta.get("imdb_id")
            or meta.get("imdb")
            or ""
        ).strip()
        if imdb_id.lower().startswith("tt"):
            imdb_id = imdb_id[2:]
        if imdb_id.isdigit() and int(imdb_id) > 0:
            imdb_id = f"tt{imdb_id.zfill(7)}"
        else:
            imdb_id = ""

        if not imdb_id:
            print(f"[bold yellow]Cannot perform search on {self.tracker}: IMDb ID not found in metadata.[/bold yellow]")
            return []

        api_url = f"{self.api_base_url}/torrent/search"

        payload = {
            "mode": "normal",
            "imdb": imdb_id,
        }
        dupes: list[dict[str, Any]] = []

        try:
            response = await self.session.post(api_url, json=payload, timeout=15)
            res_json = response.json()

            if res_json.get("code") != "0":
                print(f"[bold red]API Error: {res_json.get('message')}[/bold red]")
                return []

            torrents = res_json.get("data", {}).get("data", [])

            for torrent in torrents:
                t_id = torrent.get("id")
                if not t_id:
                    continue

                dupes.append({"name": torrent.get("name"), "size": int(torrent.get("size", 0)), "link": f"https://kp.m-team.cc/detail/{t_id}"})

            return dupes

        except Exception as e:
            print(f"[bold red]Error searching for IMDb ID {imdb_id} on {self.tracker}: {e}[/bold red]")

        return []

    def get_standard(self, meta: Meta) -> int:
        _1080p = 1
        _1080i = 2
        _720p = 3
        sd = 5
        _4k = 6
        _8k = 7

        resolution = meta.get("resolution", "").lower()
        if resolution == "1080p":
            return _1080p
        elif resolution == "1080i":
            return _1080i
        elif resolution == "720p":
            return _720p
        elif resolution == "2160p":
            return _4k
        elif resolution == "4320p":
            return _8k
        elif meta.get("sd", False):
            return sd
        else:
            console.print(f"{self.tracker}: Unknown or unsupported resolution '{resolution}', defaulting to 1080p.")
            return _1080p

    def get_videocodec(self, meta: Meta) -> int:
        x264 = 1  # H.264(x264/AVC)
        x265 = 16  # H.265(x265/HEVC)
        vc1 = 2  # VC-1
        mpeg2 = 4  # MPEG-2
        xvid = 3  # Xvid
        av1 = 19  # AV1
        vp8_9 = 21  # VP8/9

        codec = meta.get("video_codec", "").lower()
        if codec in ("h264", "x264", "avc", "h.264"):
            return x264
        elif codec in ("h265", "hevc", "x265"):
            return x265
        elif codec in ("vc1", "vc-1"):
            return vc1
        elif codec in ("mpeg2", "mpeg-2"):
            return mpeg2
        elif codec == "xvid":
            return xvid
        elif codec == "av1":
            return av1
        elif codec in ("vp8", "vp9"):
            return vp8_9
        else:
            console.print(f"{self.tracker}: Unknown or unsupported video codec '{codec}', defaulting to x264.")
            return x264

    def get_audiocodec(self, meta: Meta) -> int:
        aac = 6  # AAC
        ac3 = 8  # AC3(DD)
        dts = 3  # DTS
        dts_hd_ma = 11  # DTS-HD MA
        eac3 = 12  # E-AC3(DDP)
        atmos_eac3 = 13  # E-AC3 Atoms(DDP Atoms)
        true_hd = 9  # TrueHD

        codec = meta.get("audio", "").lower()

        if "aac" in codec:
            return aac
        elif "dd+" in codec:
            return eac3
        elif "dd " in codec:
            return ac3

        elif "atmos" in codec and ("dd+" in codec or "e-ac-3" in codec or "eac3" in codec):
            return atmos_eac3
        elif "dts-hd" in codec:
            return dts_hd_ma
        elif "dts" in codec:
            return dts
        elif "truehd" in codec:
            return true_hd
        else:
            console.print(f"{self.tracker}: Unknown or unsupported audio codec '{codec}', defaulting to AC3.")
            return ac3

    def _imdb_url(self, meta: Meta) -> str:
        info = meta.get("imdb_info") if isinstance(meta.get("imdb_info"), dict) else {}
        candidate = str(info.get("imdb_url") or "").strip()
        if candidate:
            return candidate
        raw = str(meta.get("imdb_id") or info.get("imdbID") or info.get("imdb_id") or "").strip()
        if raw.lower().startswith("tt"):
            raw = raw[2:]
        return f"https://www.imdb.com/title/tt{raw.zfill(7)}/" if raw.isdigit() and int(raw) else ""

    async def fetch_data(self, meta: Meta) -> dict[str, Any]:
        """
        https://test2.m-team.cc/api/swagger-ui/index.html#/種子/createOredit
        """
        if not isinstance(meta.get("ptgen"), dict):
            meta["ptgen"] = await get_ptgen_meta(meta)
        ptgen = cast(dict[str, Any], meta.get("ptgen", {}))
        data = {
            # "torrent": 0,
            # "offer": 0,
            "name": meta["name"],
            "smallDescr": " / ".join(str(x) for x in ptgen.get("trans_title", []) if str(x).strip()) or str(meta.get("title", "")),
            "descr": await self.generate_description(meta),
            "category": self.get_category_id(meta),
            # "source": 0,
            # "medium": 0,
            "standard": self.get_standard(meta),
            "videoCodec": self.get_videocodec(meta),
            "audioCodec": self.get_audiocodec(meta),
            # "team": 0,
            # "processing": 0,
            # "countries": "",
            "imdb": self._imdb_url(meta),
            "douban": str(ptgen.get("douban_url") or meta.get("douban_url") or ""),
            # "dmmCode": "",
            # "cids": "",
            # "aids": "",
            "anonymous": bool(meta.get("anon", 0) or self.config["TRACKERS"][self.tracker].get("anon", False)),
            # "labels": 0,
            # "tags": "",
            # "file": "",
            # "nfo": "",
            "mediainfo": await self.mediainfo(meta),
            "mediaInfoAnalysisResult": True,
            # "labelsNew": ""
        }

        return data

    async def upload(self, meta: Meta, _) -> bool:
        if not self.api_base_url:
            raise UploadException("M-Team API address is not configured; set TRACKERS.MTEAM.api_base_url", "red")
        if not self.api_key:
            raise UploadException("M-Team API key is not configured; set TRACKERS.MTEAM.api_key", "red")
        data = await self.fetch_data(meta)
        response = None

        if not meta.get("debug", False):
            try:
                upload_url = f"{self.api_base_url}/torrent/createOredit"
                await self.common.create_torrent_for_upload(
                    meta,
                    self.tracker,
                    "M-Team",
                    announce_url=self.config["TRACKERS"][self.tracker].get("announce_url", "https://fake.tracker"),
                )
                torrent_path = f"{meta['base_dir']}/tmp/{meta['uuid']}/[{self.tracker}].torrent"

                async with aiofiles.open(torrent_path, "rb") as torrent_file:
                    torrent_bytes = await torrent_file.read()
                files = {"file": ("upload.torrent", torrent_bytes, "application/x-bittorrent")}

                response = await self.session.post(upload_url, data=data, files=files, headers=dict(self.session.headers), timeout=90)
                response.raise_for_status()
                response_json = response.json()
                response_data: dict[str, Any] = cast(dict[str, Any], response_json) if isinstance(response_json, dict) else {}

                if response_data.get("message") == "SUCCESS":
                    torrent_id = str(response_data["data"]["id"])
                    meta["tracker_status"][self.tracker]["torrent_id"] = torrent_id
                    meta["tracker_status"][self.tracker]["status_message"] = response_data.get("message")

                    download_api_url = f"{self.api_base_url}/torrent/genDlToken?id={torrent_id}"
                    response = await self.session.post(download_api_url)
                    data = response.json()
                    final_download_url = data.get("data")
                    if final_download_url:
                        await self.common.download_tracker_torrent(meta, self.tracker, headers=dict(self.session.headers), downurl=final_download_url)
                        return True
                    console.print(f"{self.tracker}: Failed to get download URL from API response.")
                    meta["tracker_status"][self.tracker]["status_message"] = "Failed to get download URL from API response"
                    return False
                else:
                    meta["tracker_status"][self.tracker]["status_message"] = f"data error: {response_data.get('message', 'Unknown API error.')}"
                    return False

            except httpx.HTTPStatusError as e:
                meta["tracker_status"][self.tracker]["status_message"] = f"data error: HTTP {e.response.status_code} - {e.response.text}"
                return False
            except httpx.TimeoutException:
                meta["tracker_status"][self.tracker]["status_message"] = f"data error: Request timed out after {self.session.timeout.write} seconds"
                return False
            except httpx.RequestError as e:
                resp_text = getattr(getattr(e, "response", None), "text", "No response received")
                meta["tracker_status"][self.tracker]["status_message"] = f"data error: Unable to upload. Error: {e}.\nResponse: {resp_text}"
                return False
            except Exception as e:
                resp_text = response.text if response is not None else "No response received"
                meta["tracker_status"][self.tracker]["status_message"] = f"data error: It may have uploaded, go check. Error: {e}.\nResponse: {resp_text}"
                return False

        else:
            console.print("[cyan]MTEAM Request Data:")
            console.print(Redaction.redact_private_info(data))
            meta["tracker_status"][self.tracker]["status_message"] = "Debug mode enabled, not uploading"
            await self.common.create_torrent_for_upload(meta, f"{self.tracker}" + "_DEBUG", f"{self.tracker}" + "_DEBUG", announce_url="https://fake.tracker")
            return True  # Debug mode - simulated success
