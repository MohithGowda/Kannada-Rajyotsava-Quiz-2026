import os
import unittest
from unittest.mock import patch

import app as quiz


class JoinUrlTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        os.environ.pop("PUBLIC_URL", None)
        os.environ.pop("RENDER_EXTERNAL_URL", None)

    def test_public_origin_preserves_scheme_and_port(self):
        for origin in (
            "https://quiz.onrender.com",
            "http://quiz.example.com",
            "https://quiz.example.com:8443",
            "http://192.168.1.10:5000",
        ):
            with self.subTest(origin=origin):
                with quiz.app.test_request_context("/", base_url=origin):
                    self.assertEqual(quiz.join_url(), origin + "/join")

    def test_localhost_uses_lan_address(self):
        with patch.object(quiz, "lan_ip", return_value="192.168.1.10"):
            for origin in ("http://localhost:5000", "http://127.0.0.1:5000",
                           "http://[::1]:5000"):
                with self.subTest(origin=origin):
                    with quiz.app.test_request_context("/", base_url=origin):
                        self.assertEqual(quiz.join_url(), "http://192.168.1.10:5000/join")

    def test_render_uses_public_https_url_behind_proxy(self):
        os.environ["RENDER_EXTERNAL_URL"] = "https://quiz.onrender.com"
        with quiz.app.test_request_context("/", base_url="http://quiz.onrender.com:10000"):
            self.assertEqual(quiz.join_url(), "https://quiz.onrender.com/join")

    def test_public_url_takes_precedence_over_render_url(self):
        os.environ["PUBLIC_URL"] = "https://quiz.example.com/"
        os.environ["RENDER_EXTERNAL_URL"] = "https://quiz.onrender.com"
        with quiz.app.test_request_context("/"):
            self.assertEqual(quiz.join_url(), "https://quiz.example.com/join")

    def test_qr_encodes_public_registration_url(self):
        os.environ["RENDER_EXTERNAL_URL"] = "https://quiz.onrender.com"
        qr = quiz.qrcode.QRCode()
        with patch.object(quiz.qrcode, "QRCode", return_value=qr):
            with patch.object(qr, "add_data", wraps=qr.add_data) as add_data:
                with quiz.app.test_client() as client:
                    response = client.get("/qr.png", base_url="http://quiz.onrender.com")
                add_data.assert_called_once_with("https://quiz.onrender.com/join")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "image/png")
        self.assertTrue(response.data.startswith(b"\x89PNG\r\n\x1a\n"))


if __name__ == "__main__":
    unittest.main()
