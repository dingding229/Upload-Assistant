import ast
import re
import unittest
from pathlib import Path


def _load_compactor():
    module = ast.parse(Path("src/discparse.py").read_text(encoding="utf-8"))
    function = next(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "compact_bdinfo_report"
    )
    namespace = {"re": re}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "<BDInfo compactor>", "exec"), namespace)
    return namespace["compact_bdinfo_report"]


class BDInfoCompactionTests(unittest.TestCase):
    def test_keeps_files_and_removes_chapters(self):
        compact = _load_compactor()
        report = (
            "DISC INFO:\n\nDisc Label: Test\n\n"
            "PLAYLIST REPORT:\n\nName: 00000.MPLS\n\n"
            "FILES:\n\nName Time In Length\n00000.M2TS 0:00:00 1:30:00\n\n"
            "CHAPTERS:\n\nNumber Time In\n1 0:00:00\n"
        )
        result = compact(report)
        self.assertIn("FILES:", result)
        self.assertIn("00000.M2TS", result)
        self.assertNotIn("CHAPTERS:", result)
        self.assertNotIn("Number Time In", result)
        self.assertTrue(result.endswith("\n"))

    def test_removes_stream_diagnostics_when_chapters_are_absent(self):
        compact = _load_compactor()
        report = "DISC INFO:\nFILES:\n00000.M2TS\nSTREAM DIAGNOSTICS:\nFile PID Codec\n"
        self.assertEqual(compact(report), "DISC INFO:\nFILES:\n00000.M2TS\n")


if __name__ == "__main__":
    unittest.main()
