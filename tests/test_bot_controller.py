import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.bot_controller import is_authorized, get_reply_keyboard_markup

class TestBotController(unittest.TestCase):
    def test_whitelist_authorization(self):
        self.assertTrue(is_authorized("6444855403", "6444855403"))
        self.assertTrue(is_authorized(6444855403, "6444855403"))
        self.assertFalse(is_authorized("9999999999", "6444855403"))

    def test_keyboard_markup_structure(self):
        kb = get_reply_keyboard_markup()
        self.assertIn("keyboard", kb)
        self.assertEqual(len(kb["keyboard"]), 2)
        self.assertEqual(len(kb["keyboard"][0]), 2)
        self.assertEqual(kb["keyboard"][0][0]["text"], "▶ Dinlemeyi Başlat")

if __name__ == "__main__":
    unittest.main()
