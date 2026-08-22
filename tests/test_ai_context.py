"""Pure tests for the distributable AI_CONTEXT.md contract.

Name: tests/test_ai_context.py
Purpose: verify that the stable AI context exists, documents key flows, and avoids common machine-specific path leaks.
Main behavior: reads the root Markdown only; no FreeCAD/Qt dependency.
Modification notes: keep checks generic and portable; do not encode organization/client identifiers in tests.
Version: 2026-08-21-ai-context-v1
Date and time: 2026-08-21 08:24 -06:00
"""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
AI_CONTEXT = ROOT / "AI_CONTEXT.md"


class AIContextTests(unittest.TestCase):
    def test_ai_context_exists_and_describes_core_workflows(self):
        self.assertTrue(AI_CONTEXT.is_file())
        text = AI_CONTEXT.read_text(encoding="utf-8")
        self.assertIn("GameEngineExportWB", text)
        self.assertIn("Quick Example -> Run in Castle", text)
        self.assertIn("AI_CONTEXT.md", text)
        self.assertIn("GEE_ContextJSON", text)
        self.assertIn("independent core -> FreeCAD adapter", text)

    def test_ai_context_has_no_machine_specific_absolute_paths_or_email(self):
        text = AI_CONTEXT.read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"[A-Za-z]:[\\/]Users[\\/][^\\/\s]+", text))
        self.assertIsNone(re.search("/" + "Users/" + r"[^/\s]+", text))
        self.assertIsNone(re.search("/" + "home/" + r"[^/\s]+", text))
        self.assertIsNone(re.search(r"\\\\[^\\\s]+\\[^\\\s]+", text))
        self.assertIsNone(
            re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
        )


if __name__ == "__main__":
    unittest.main()
