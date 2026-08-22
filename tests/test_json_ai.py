"""Pure tests for GameEngineExportWB AI JSON prompt helper.

Name: tests/test_json_ai.py
Purpose: verify that the AI copy/paste prompt stays language-aware and keeps JSON payloads intact.
Main behavior: tests prompt-only and prompt+JSON output without FreeCAD, FreeCADGui or Qt.
Modification notes: keep this test pure so it can run before FreeCAD is available.
Version: 2026-08-21-ai-json-prompt-v1
Date and time: 2026-08-21 07:49 -06:00
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


def _load_module():
    path = Path(__file__).resolve().parents[1] / "core" / "json_ai.py"
    spec = importlib.util.spec_from_file_location("gee_json_ai", str(path))
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class JsonAITests(unittest.TestCase):
    def test_spanish_prompt_contains_current_json(self):
        module = _load_module()
        text = module.build_ai_prompt({"units": "mm", "rooms": []}, "es")
        self.assertIn("PROMPT SUGERIDO PARA IA", text)
        self.assertIn("JSON ACTUAL:", text)
        self.assertIn('"units": "mm"', text)

    def test_english_prompt_without_context(self):
        module = _load_module()
        text = module.build_ai_prompt("", "en")
        self.assertTrue(text.startswith("SUGGESTED AI PROMPT"))
        self.assertNotIn("CURRENT JSON:", text)


if __name__ == "__main__":
    unittest.main()
