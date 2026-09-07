import ast
import asyncio
import unittest
from pathlib import Path


def _load_match_tracker_url():
    """Load the standalone matcher without requiring qBittorrent dependencies."""
    module = ast.parse(Path("src/torrent_clients/qbittorrent.py").read_text(encoding="utf-8"))
    matcher = next(
        node
        for node in module.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "match_tracker_url"
    )
    namespace = {
        "asyncio": asyncio,
        "cast": lambda _type, value: value,
        "Redaction": type("Redaction", (), {"redact_private_info": staticmethod(str)}),
    }
    exec(compile(ast.Module(body=[matcher], type_ignores=[]), "<tracker matcher>", "exec"), namespace)
    return namespace["match_tracker_url"]


class TrackerUrlMatchingTests(unittest.IsolatedAsyncioTestCase):
    async def test_added_tracker_urls_are_removed_from_upload_targets(self):
        match_tracker_url = _load_match_tracker_url()
        meta = {}
        await match_tracker_url(
            [
                "https://chdbits.xyz/announce.php?passkey=secret",
                "https://tracker.hdsky.me/announce.php?passkey=secret",
                "https://tracker.m-team.cc/announce?passkey=secret",
                "https://ourbits.club/announce.php?passkey=secret",
                "https://tracker.totheglory.im/announce.php?passkey=secret",
                "https://on.springsunday.net/announce.php?passkey=secret",
            ],
            meta,
        )
        self.assertEqual(
            set(meta["remove_trackers"]),
            {"CHDBITS", "HDSKY", "MTEAM", "OURBITS", "TTG", "SSD"},
        )

    async def test_mteam_kp_announce_variant_is_matched(self):
        match_tracker_url = _load_match_tracker_url()
        meta = {"remove_trackers": ["MTEAM"]}
        await match_tracker_url(["https://kp.m-team.cc/announce/token"], meta)
        self.assertEqual(meta["remove_trackers"], ["MTEAM"])

    async def test_chdbits_legacy_announce_domain_is_also_matched(self):
        match_tracker_url = _load_match_tracker_url()
        meta = {}
        await match_tracker_url(["https://ptchdbits.co/announce.php?passkey=secret"], meta)
        self.assertEqual(meta["remove_trackers"], ["CHDBITS"])


if __name__ == "__main__":
    unittest.main()
