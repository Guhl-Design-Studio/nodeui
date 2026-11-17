import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nodeui_bridge.share_nodes import PromptInput


class PromptInputTests(unittest.TestCase):
    def test_prompt_needs_no_image_and_preserves_text(self):
        self.assertEqual(set(PromptInput.INPUT_TYPES()["required"]), {"prompt"})
        for prompt in ("A snowy forest 🌲", "", "Two lines\nof text"):
            self.assertEqual(PromptInput().read(prompt), (prompt,))


if __name__ == "__main__":
    unittest.main()
