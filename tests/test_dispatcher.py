import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.dispatcher import build_multipart_voice

class TestDispatcher(unittest.TestCase):
    def test_multipart_builder(self):
        body, content_type = build_multipart_voice(
            chat_id="6444855403",
            caption="Test Caption",
            file_bytes=b"FAKE_AUDIO_DATA",
            filename="test.m4a"
        )
        self.assertTrue(content_type.startswith("multipart/form-data; boundary="))
        self.assertIn(b"6444855403", body)
        self.assertIn(b"Test Caption", body)
        self.assertIn(b"FAKE_AUDIO_DATA", body)
        self.assertIn(b'filename="test.m4a"', body)

if __name__ == "__main__":
    unittest.main()
