import os
import tempfile
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


class ScoringAndReviewTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        database = patch.object(quiz, "DB_PATH", os.path.join(directory.name, "quiz.db"))
        database.start()
        self.addCleanup(database.stop)
        quiz.init_db()
        self.db = quiz.connect()
        self.addCleanup(self.db.close)
        self.db.execute(
            "INSERT INTO teams (id, name, token, created_at) VALUES (1, 'Team <one>', 'token', 1)")
        self.question = self.db.execute("SELECT * FROM questions ORDER BY position LIMIT 1").fetchone()
        self.client = quiz.app.test_client()
        self.now = int(quiz.time.time())

    def admin_login(self):
        with self.client.session_transaction() as session:
            session["is_admin"] = True

    def set_round(self, status, ended=""):
        for key, value in (("status", status), ("started_at", str(self.now - 10)),
                           ("duration", "300"), ("ended_at", str(ended))):
            self.db.execute("UPDATE settings SET value=? WHERE key=?", (value, key))

    def add_answer(self, time_ms, correct=True, points=100, answered=True):
        choice = self.question["correct_idx"] if correct else (self.question["correct_idx"] + 1) % 4
        self.db.execute(
            "INSERT INTO answers (team_id, question_id, seq, served_at, answered_at, "
            "chosen_idx, is_correct, time_ms, points) VALUES (1, ?, 1, ?, ?, ?, ?, ?, ?)",
            (self.question["id"], self.now, self.now + time_ms / 1000 if answered else None,
             choice if answered else None, int(correct) if answered else None,
             time_ms if answered else None, points if answered else 0))

    def test_scoring_boundaries(self):
        for correct, elapsed, expected in (
            (True, 0, 15), (True, 9999, 15), (True, 10000, 15),
            (True, 10001, 10), (True, 20000, 10),
            (False, 0, -5), (False, 10000, -5), (False, 20000, -5),
        ):
            with self.subTest(correct=correct, elapsed=elapsed):
                self.assertEqual(quiz.answer_points(correct, elapsed), expected)

    def test_answer_endpoint_scores_without_revealing_evaluation(self):
        self.set_round("running")
        with self.client.session_transaction() as session:
            session["team_id"], session["team_token"] = 1, "token"
        for correct, seconds, expected in (
            (True, 9, 15), (True, 10, 15), (True, 11, 10), (False, 1, -5),
        ):
            with self.subTest(correct=correct, seconds=seconds):
                self.db.execute("DELETE FROM answers")
                self.add_answer(0, answered=False)
                choice = self.question["correct_idx"] if correct else (self.question["correct_idx"] + 1) % 4
                with patch.object(quiz.time, "time", return_value=self.now + seconds):
                    response = self.client.post("/api/answer", json={
                        "question_id": self.question["id"], "choice": choice})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json, {"ok": True})
                self.assertEqual(self.db.execute("SELECT points FROM answers").fetchone()[0], expected)
                self.assertEqual(self.client.post("/api/answer", json={
                    "question_id": self.question["id"], "choice": choice}).status_code, 409)

    def test_existing_answers_are_rescored_once_and_preserved(self):
        self.add_answer(10000)
        self.db.execute("DELETE FROM settings WHERE key='scoring_version'")
        original = dict(self.db.execute("SELECT * FROM answers").fetchone())
        quiz.init_db()
        actual = dict(self.db.execute("SELECT * FROM answers").fetchone())
        self.assertEqual(actual, {**original, "points": 15})
        quiz.init_db()
        self.assertEqual(dict(self.db.execute("SELECT * FROM answers").fetchone()), actual)
        self.assertEqual(quiz.team_stats(self.db)[0]["score"], 15)
        self.admin_login()
        self.assertIn(",15,", self.client.get("/admin/export/summary.csv").text)

    def test_migration_handles_slow_wrong_and_unanswered(self):
        for correct, elapsed, answered, expected in (
            (True, 10001, True, 10), (False, 1000, True, -5),
            (True, 0, False, 0),
        ):
            with self.subTest(correct=correct, elapsed=elapsed, answered=answered):
                self.db.execute("DELETE FROM answers")
                self.db.execute("DELETE FROM settings WHERE key='scoring_version'")
                self.add_answer(elapsed, correct=correct, answered=answered)
                quiz.init_db()
                self.assertEqual(self.db.execute("SELECT points FROM answers").fetchone()[0], expected)

    def test_review_requires_admin_and_completed_round(self):
        self.assertEqual(self.client.get("/admin/review").status_code, 302)
        self.assertEqual(self.client.get("/api/admin/team/1").status_code, 401)
        self.admin_login()
        self.assertEqual(self.client.get("/admin/review").status_code, 409)
        self.set_round("running")
        self.assertEqual(self.client.get("/admin/review").status_code, 409)
        self.set_round("finished", ended=self.now - 1)
        with patch.object(quiz.time, "time", return_value=self.now):
            self.assertFalse(self.client.get("/api/admin/overview").json["review_available"])
            self.assertEqual(self.client.get("/admin/review").status_code, 409)
        with patch.object(quiz.time, "time", return_value=self.now + 1):
            self.assertTrue(self.client.get("/api/admin/overview").json["review_available"])
            self.assertEqual(self.client.get("/admin/review").status_code, 200)

    def test_early_review_requires_every_registered_team_to_finish(self):
        self.admin_login()
        self.set_round("running")
        with patch.object(quiz.time, "time", return_value=self.now):
            self.db.execute(
                "INSERT INTO answers (team_id, question_id, seq, served_at, answered_at, "
                "chosen_idx, is_correct, time_ms, points) "
                "SELECT 1, id, position, 990, 999, correct_idx, 1, 9000, 15 FROM questions")
            self.assertTrue(self.client.get("/api/admin/overview").json["review_available"])
            self.assertEqual(self.client.get("/admin/review").status_code, 200)
            self.db.execute(
                "INSERT INTO teams (id, name, token, created_at) VALUES (2, 'Team two', 'two', 2)")
            self.assertFalse(self.client.get("/api/admin/overview").json["review_available"])
            self.assertEqual(self.client.get("/admin/review").status_code, 409)
            self.db.execute("DELETE FROM teams WHERE id=2")
            self.db.execute("DELETE FROM answers")
            self.assertFalse(self.client.get("/api/admin/overview").json["review_available"])
            self.db.execute("DELETE FROM teams")
            self.assertFalse(self.client.get("/api/admin/overview").json["review_available"])

    def test_review_contains_bilingual_answers_and_score_breakdown(self):
        self.admin_login()
        self.add_answer(10000, points=15)
        self.set_round("finished", ended=1)
        response = self.client.get("/admin/review")
        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn("Team &lt;one&gt;", html)
        self.assertIn("Score: 15", html)
        self.assertIn("Base", html)
        self.assertIn("Bonus", html)
        self.assertIn("10.000 s", html)
        answer = self.client.get("/api/admin/team/1").json["answers"][0]
        self.assertEqual((answer["base_points"], answer["bonus"], answer["points"]), (10, 5, 15))
        self.assertEqual(answer["chosen_en"], answer["answer_en"])
        self.assertIn(answer["answer_en"], html)
        self.db.execute(
            "UPDATE answers SET chosen_idx=?, is_correct=0, time_ms=1000, points=-5",
            ((self.question["correct_idx"] + 1) % 4,))
        answer = self.client.get("/api/admin/team/1").json["answers"][0]
        self.assertEqual((answer["base_points"], answer["bonus"], answer["points"]), (-5, 0, -5))
        self.assertNotEqual(answer["chosen_en"], answer["answer_en"])
        self.assertIn("Wrong", self.client.get("/admin/review").text)
        self.client.post("/api/admin/reset", json={})
        self.assertEqual(self.client.get("/admin/review").status_code, 409)


if __name__ == "__main__":
    unittest.main()
