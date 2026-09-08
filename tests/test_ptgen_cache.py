import asyncio
import unittest
from copy import deepcopy
from unittest.mock import patch

import httpx

from src.ptgen_api import build_ptgen_subtitle, get_ptgen_meta


class PtgenCacheTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.calls = 0
        self.fail = False
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()
        self.meta = {"base_dir": "/test", "uuid": "release", "imdb_id": 1234567}
        original_client = httpx.AsyncClient

        async def respond(request):
            self.calls += 1
            self.entered.set()
            await self.release.wait()
            if self.fail:
                return httpx.Response(503)
            return httpx.Response(200, json={"format": "PTGEN", "aka": ["Title"]})

        self.patcher = patch(
            "src.ptgen_api.httpx.AsyncClient",
            side_effect=lambda **kw: original_client(transport=httpx.MockTransport(respond), **kw),
        )
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    async def test_parallel_and_sequential_share_one_request(self):
        results = await asyncio.gather(*(get_ptgen_meta(deepcopy(self.meta)) for _ in range(6)))
        results[0]["trans_title"].append("modified")
        result = await get_ptgen_meta(deepcopy(self.meta))
        self.assertEqual(self.calls, 1)
        self.assertEqual(result["trans_title"], ["Title"])
        self.assertEqual(results[1]["trans_title"], ["Title"])

    async def test_distinct_release_and_changed_lookup(self):
        await get_ptgen_meta(self.meta)
        await get_ptgen_meta({**self.meta, "uuid": "other"})
        await get_ptgen_meta({**self.meta, "imdb_id": 2345678})
        self.assertEqual(self.calls, 3)

    async def test_failure_is_shared_for_run(self):
        self.fail = True
        results = await asyncio.gather(*(get_ptgen_meta(deepcopy(self.meta)) for _ in range(6)))
        await get_ptgen_meta(self.meta)
        self.assertEqual(self.calls, 1)
        self.assertTrue(all(result["bbcode"] == "" for result in results))

    async def test_cancelled_waiter_does_not_cancel_fetch(self):
        self.release.clear()
        first = asyncio.create_task(get_ptgen_meta(self.meta))
        await self.entered.wait()
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        self.release.set()
        result = await get_ptgen_meta(deepcopy(self.meta))
        self.assertEqual(self.calls, 1)
        self.assertEqual(result["bbcode"], "PTGEN")

    async def test_douban_lookup_shared(self):
        meta = {"uuid": "douban", "douban_url": "https://movie.douban.com/subject/123/"}
        await asyncio.gather(get_ptgen_meta(meta), get_ptgen_meta(deepcopy(meta)))
        self.assertEqual(self.calls, 1)

    async def test_subtitle_uses_only_ptgen_title(self):
        subtitle = build_ptgen_subtitle(
            {"title": "世界将颤抖", "trans_title": ["撼世逃奔", "世界将颤抖", "撼世逃奔"]},
            "Fallback",
        )
        self.assertEqual(subtitle, "世界将颤抖")

    async def test_subtitle_falls_back_when_ptgen_has_no_titles(self):
        self.assertEqual(build_ptgen_subtitle({"trans_title": []}, "Fallback"), "Fallback")


if __name__ == "__main__":
    unittest.main()
