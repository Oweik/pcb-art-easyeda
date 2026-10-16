import json
import random
import tempfile
import unittest
from pathlib import Path

from PIL import Image
from pcb_art import load_masks, make_demo, rectangles, validate_plan


class ConversionTests(unittest.TestCase):
    def test_pixel_union_is_exact_including_holes(self):
        rng = random.Random(17)
        for _ in range(100):
            rows = [[rng.choice([True, False]) for _ in range(13)] for _ in range(17)]
            restored = [[0] * 13 for _ in range(17)]
            for x, y, w, h in rectangles(rows):
                for py in range(y, y + h):
                    for px in range(x, x + w):
                        restored[py][px] += 1
            self.assertEqual(restored, [[int(v) for v in row] for row in rows])

    def test_demo_and_opening_validation(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            make_demo(folder)
            plan = load_masks(folder / "manifest.json")
            validate_plan(plan)
            self.assertEqual(len(plan["shapes"]), 14)
            copper = Image.new("L", (120, 160), 255)
            copper.save(folder / "front_copper.png")
            with self.assertRaisesRegex(ValueError, "without copper"):
                load_masks(folder / "manifest.json")

    def test_canvas_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            make_demo(folder)
            Image.new("L", (10, 10), 255).save(folder / "back_silk.png")
            with self.assertRaisesRegex(ValueError, "same canvas"):
                load_masks(folder / "manifest.json")

    def test_plan_rejects_unknown_layers_and_invalid_geometry(self):
        for shape in [{"layer": "front_paste", "rect_mm": [1, 1, 1, 1]},
                      {"layer": "front_copper", "rect_mm": [29, 1, 2, 1]},
                      {"layer": "back_silk", "rect_mm": [float("nan"), 1, 2, 1]}]:
            with self.assertRaises(ValueError):
                validate_plan({"schema": 1, "back_view": "normal", "width_mm": 30, "height_mm": 40, "shapes": [shape]})


if __name__ == "__main__":
    unittest.main()
