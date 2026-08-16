import importlib.util
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PLUGIN_DIR = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("vision_under_test", PLUGIN_DIR / "scripts" / "vision.py")
vision = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(vision)


class SmartResizeTests(unittest.TestCase):
    def test_within_budget_and_grid_snapped(self):
        h, w = vision.smart_resize(1000, 2000, vision.MIN_PIXELS, 1024 * 1024, factor=28)
        self.assertLessEqual(h * w, int(1024 * 1024 * 1.1))
        self.assertEqual(h % 28, 0)
        self.assertEqual(w % 28, 0)

    def test_upscales_tiny_images(self):
        h, w = vision.smart_resize(10, 10, vision.MIN_PIXELS, 1024 * 1024, factor=28)
        self.assertGreaterEqual(h * w, vision.MIN_PIXELS)


class GroundingParserTests(unittest.TestCase):
    def test_json_bbox_format(self):
        text = '[{"label":"button","bbox_2d":[100,200,300,400]}]'
        matches = vision.parse_grounding(text, 1000, 2000)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["label"], "button")
        self.assertEqual(matches[0]["bbox_pixel"], [100, 400, 300, 800])
        self.assertEqual(matches[0]["bbox_normalized"], [100, 200, 300, 400])

    def test_ref_box_format(self):
        text = '<ref>search box</ref><box>(50,60),(70,80)</box>'
        matches = vision.parse_grounding(text, 1000, 1000)
        self.assertEqual(matches[0]["label"], "search box")
        self.assertEqual(matches[0]["bbox_pixel"], [50, 60, 70, 80])

    def test_empty_array_is_legitimate(self):
        self.assertEqual(vision.parse_grounding("[]", 100, 100), [])

    def test_pixel_coordinate_heuristic(self):
        text = '[{"label":"x","bbox_2d":[10,20,110,120]}]'
        matches = vision.parse_grounding(text, 100, 100)
        self.assertEqual(matches[0]["bbox_pixel"], [10, 20, 100, 100])


class ChunkPlanTests(unittest.TestCase):
    def test_plan_covers_tail(self):
        tops = vision.plan_chunk_tops(5000, 2000, 100)
        self.assertEqual(tops[-1], 3800)
        self.assertTrue(all(b - a >= 1 for a, b in zip(tops, tops[1:])))

    def test_rejects_bad_overlap(self):
        with self.assertRaises(ValueError):
            vision.plan_chunk_tops(1000, 1000, 600)


class EvidenceNormalizeTests(unittest.TestCase):
    def test_normalizes_full_json(self):
        payload = {
            "summary": "a login form",
            "ocr": {"full_text": "username\npassword"},
            "layout": [{"region": "header", "reading_order": 1, "text": "Login"}],
            "visual": {"dominant_colors": ["#fff"], "style": "flat"},
            "semantics": {
                "scene": "login page",
                "entities": [{"name": "submit button", "type": "button", "evidence": "blue rounded rectangle at bottom"}],
                "relations": [{"subject": "password field", "predicate": "below", "object": "username field"}],
            },
            "uncertainty": ["badge text illegible"],
        }
        evidence = vision.normalize_evidence(json_text(payload))
        self.assertFalse(evidence["parse_error"])
        self.assertEqual(evidence["summary"], "a login form")
        self.assertEqual(evidence["ocr_full_text"], "username\npassword")
        self.assertEqual(evidence["layout"][0]["region"], "header")
        self.assertEqual(evidence["semantics"]["scene"], "login page")
        self.assertEqual(evidence["semantics"]["entities"][0]["name"], "submit button")
        self.assertEqual(evidence["semantics"]["relations"][0]["predicate"], "below")

    def test_unwraps_summary_nested_json(self):
        outer = {
            "summary": json_text({
                "summary": "nested summary",
                "ocr": {"full_text": "nested text"},
                "layout": [{"region": "header", "reading_order": 1, "text": "Login"}],
                "semantics": {"scene": "login", "entities": [{"name": "x", "type": "button", "evidence": "e"}], "relations": []},
                "visual": {"style": "flat"},
                "uncertainty": [],
            }),
        }
        evidence = vision.normalize_evidence(json_text(outer))
        self.assertFalse(evidence["parse_error"])
        self.assertEqual(evidence["summary"], "nested summary")
        self.assertEqual(evidence["ocr_full_text"], "nested text")
        self.assertEqual(evidence["semantics"]["scene"], "login")

    def test_falls_back_to_raw_text(self):
        evidence = vision.normalize_evidence("not json at all")
        self.assertTrue(evidence["parse_error"])
        self.assertEqual(evidence["summary"], "not json at all")
        self.assertEqual(evidence["layout"], [])
        self.assertEqual(evidence["semantics"], {"scene": "", "entities": [], "relations": []})


class ProviderChainTests(unittest.TestCase):
    def test_provider_chain_uses_json_fallback(self):
        with mock.patch.dict(os.environ, {
            "VISION_PROVIDERS_JSON": '[{"apiUrl":"https://a/v1","model":"fallback","apiKey":"k"}]',
            "VISION_API_URL": "",
            "VISION_MODEL": "",
        }, clear=False):
            chain = vision.provider_chain()
            self.assertEqual(chain[0]["model"], "fallback")

    def test_provider_chain_prefers_json_over_env(self):
        with mock.patch.dict(os.environ, {
            "VISION_PROVIDERS_JSON": '[{"apiUrl":"https://a/v1","model":"json","apiKey":"k"}]',
            "VISION_API_URL": "https://b/v1",
            "VISION_MODEL": "env-model",
        }, clear=False):
            chain = vision.provider_chain()
            self.assertEqual([p["model"] for p in chain], ["json"])


class PilDataUrlTests(unittest.TestCase):
    def test_resizes_large_chunk_without_name_error(self):
        from PIL import Image
        image = Image.new("RGB", (2000, 1500), (10, 20, 30))
        url, _ = vision._pil_to_data_url(image, budget="normal")
        self.assertTrue(url.startswith("data:image/jpeg;base64,"))


class LongOcrFallbackTests(unittest.TestCase):
    def test_tesseract_failure_falls_back_to_vlm(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tall.png"
            Image.new("RGB", (60, 2200), (255, 255, 255)).save(path)
            with mock.patch.object(vision, "tesseract_ocr", side_effect=vision.TesseractUnavailable("no binary")):
                with mock.patch.object(vision, "call_api", return_value="TEXT"):
                    result = vision.long_screenshot_ocr(
                        str(path), target_height=1000, overlap=100,
                        tesseract_first=True, tesseract_langs="eng",
                    )
            self.assertEqual(result["chunk_count"], 3)
            self.assertEqual(result["engines"], {"tesseract": 0, "vision": 3})
            self.assertIn("TEXT", result["text"])


class DominantColorsTests(unittest.TestCase):
    def test_returns_requested_count(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "colors.png"
            Image.new("RGB", (80, 80), (12, 34, 56)).save(path)
            result = vision.dominant_colors(str(path), top=3)
            self.assertGreaterEqual(len(result["colors"]), 1)
            self.assertLessEqual(len(result["colors"]), 3)


def json_text(payload):
    import json
    return json.dumps(payload, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
