import os
import unittest
from unittest.mock import patch

from bin.get_bdinfo import build_bdinfo_command, get_bdinfo_jobs


class BDInfoCommandTests(unittest.TestCase):
    def test_builds_requested_report_command(self) -> None:
        self.assertEqual(
            build_bdinfo_command("/usr/local/bin/bdinfo", "/media/disc/BDMV", jobs=16),
            [
                "/usr/local/bin/bdinfo",
                "--report",
                "--no-mmap",
                "--jobs",
                "16",
                "/media/disc/BDMV",
            ],
        )

    def test_jobs_uses_cpu_affinity_when_available(self) -> None:
        with patch.object(os, "sched_getaffinity", return_value={0, 1, 2, 3}, create=True):
            self.assertEqual(get_bdinfo_jobs(), 4)

    def test_jobs_falls_back_to_cpu_count(self) -> None:
        with patch.object(os, "sched_getaffinity", side_effect=OSError, create=True), patch.object(os, "cpu_count", return_value=8):
            self.assertEqual(get_bdinfo_jobs(), 8)


if __name__ == "__main__":
    unittest.main()
