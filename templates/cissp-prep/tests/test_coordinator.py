import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from coordinator.__main__ import safe_dispatch
from coordinator.engine import Engine
from coordinator.models import ModelError, Router, object_json
from coordinator.store import Store
from coordinator.bootstrap import initialize
from scripts.skillsimm_bridge import patch_adapter, close_learning

ROOT = Path(__file__).resolve().parents[1]


class FakeRouter:
    learning = {"topic_questions": 8, "weak_questions": 2, "warmup_questions": 3}

    def __init__(self):
        self.calls = []
        self.reject = False
        self.fail = False
        self.version = "one"

    def identity(self, role):
        return {"provider": "anthropic" if role == "reviewer" else "openai", "model": self.version}

    def call(self, role, skill, payload):
        self.calls.append((role, skill, payload))
        if self.fail:
            raise ModelError("Simulated outage")
        if skill == "question-author":
            domain = payload["required_domain"]
            value = {"domain": domain, "topic": "test topic", "stem": f"Synthetic question {len(self.calls)}?",
                     "options": {c: f"Synthetic choice {c}" for c in "ABCD"}, "answer": "A",
                     "explanations": {c: f"Synthetic explanation {c}" for c in "ABCD"}, "rule": "Synthetic rule"}
        elif skill == "reviewer":
            value = {"approved": not self.reject, "answer": "A", "reason": "Synthetic review"}
        elif skill == "tutor":
            value = {"lesson": "Synthetic lesson", "reply": "Synthetic explanation",
                     "facts": [{"domain": "D1", "fact": f"Synthetic fact {i}"} for i in range(3)]}
        elif skill == "planner":
            value = {"date": payload["allowed_dates"][0], "reason": "Synthetic focus review"}
        else:
            raise AssertionError(skill)
        return value, self.identity(role)


class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for name in ("PLAN.md", "PROGRESS.md", "MISTAKES.md", "AGENTS.md"):
            source = ROOT / ".state/originals" / name
            shutil.copy(source if source.exists() else ROOT / name, self.root / name)
        src = ROOT / ".state/originals/CHEATSHEETS"
        shutil.copytree(src if src.exists() else ROOT / "CHEATSHEETS", self.root / "CHEATSHEETS")
        for name in ("curriculum.json", "config.example.toml"):
            shutil.copy(ROOT / name, self.root / name)
        shutil.copytree(ROOT / "skills", self.root / "skills")
        self.store = Store(self.root)
        self.router = FakeRouter()
        self.engine = Engine(self.store, self.router)
        self.store.migrate()

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def start(self):
        return self.engine.start("2026-11-23")["session_id"]

    def test_migration_is_exact_and_idempotent(self):
        scores = self.store.scores()
        self.assertEqual(sum(v["correct"] for v in scores.values()), 7)
        self.assertEqual(sum(v["attempted"] for v in scores.values()), 12)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM mistakes").fetchone()[0], 5)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM schedule").fetchone()[0], 29)
        self.assertTrue(self.store.migrate()["already_imported"])
        self.assertEqual(self.store.scores(), scores)
        self.assertTrue((self.root / ".state/originals/PLAN.md").exists())

    def test_provider_replacement_and_reconnect_keep_pending_question(self):
        sid = self.start()
        first = self.engine.next(sid)
        self.router.version = "replacement"
        self.store.close()
        self.store = Store(self.root)
        self.engine = Engine(self.store, self.router)
        self.assertEqual(self.engine.next(sid), first)
        self.assertNotIn("answer", first["question"])
        self.assertNotIn("explanations", first["question"])
        self.assertEqual(len(self.router.calls), 2)

    def test_duplicate_attempts_and_conflicts(self):
        sid = self.start()
        qid = self.engine.next(sid)["question"]["question_id"]
        self.engine.answer(qid, "B", "message-1")
        self.engine.answer(qid, "B", "message-1")
        self.engine.answer(qid, "B", "new-id-same-answer")
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0], 1)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM mistakes").fetchone()[0], 6)
        with self.assertRaises(ValueError):
            self.engine.answer(qid, "A", "message-1")
        qid2 = self.engine.next(sid)["question"]["question_id"]
        with self.assertRaises(ValueError):
            self.engine.answer(qid2, "B", "message-1")

    def test_rejected_question_never_delivered_or_scored(self):
        sid = self.start()
        self.router.reject = True
        with self.assertRaises(ModelError):
            self.engine.next(sid)
        self.assertNotIn("question", self.engine.view(sid))
        rejected = self.store.db.execute("SELECT id FROM questions LIMIT 1").fetchone()[0]
        with self.assertRaises(ValueError):
            self.engine.answer(rejected, "A", "reject-attempt")
        self.assertEqual(sum(v["attempted"] for v in self.store.scores().values()), 12)
        self.router.reject = False
        self.assertIn("question", self.engine.next(sid))

    def test_outage_preserves_phase(self):
        sid = self.start()
        self.router.fail = True
        with self.assertRaises(ModelError):
            self.engine.next(sid)
        self.assertEqual(self.store.session(sid)["phase"], "warmup")
        self.router.fail = False
        self.assertIn("question", self.engine.next(sid))

    def test_full_session_reaches_debrief_and_closes(self):
        sid = self.start()
        for i in range(3):
            q = self.engine.next(sid)["question"]
            self.engine.answer(q["question_id"], "A", f"warm-{i}")
        self.assertEqual(self.engine.view(sid)["phase"], "lesson")
        self.assertEqual(self.engine.next(sid)["phase"], "discussion")
        self.engine.discuss("Explain the principle", sid)
        payload = self.router.calls[-1][2]
        self.assertNotIn("answer", json.dumps(payload))
        self.engine.continue_quiz(sid)
        for i in range(10):
            q = self.engine.next(sid)["question"]
            self.engine.answer(q["question_id"], "A", f"quiz-{i}")
        self.assertEqual(self.engine.view(sid)["phase"], "debrief")
        self.assertEqual(self.engine.end(sid)["phase"], "closed")
        self.assertEqual(self.store.summary(sid)["attempted"], 13)
        self.assertIsNone(self.store.active())

    def test_adaptation_threshold_capacity_and_replay(self):
        sid = self.start()
        self.assertEqual(self.engine.adapt(sid)["scheduled"], [])
        with self.store.db:
            self.store.db.execute("UPDATE baseline SET correct=2,attempted=5 WHERE domain='D1'")
        first = self.engine.adapt(sid)
        self.assertEqual(first["scheduled"][0]["date"], "2026-11-24")
        self.assertEqual(first["scheduled"][0]["minutes"], 20)
        self.assertEqual(self.engine.adapt(sid)["scheduled"], [])
        self.assertEqual(self.store.candidates("D3", "2026-11-23", {"weekday_minutes": 120}), [])
        self.assertEqual(self.store.candidates("D3", "2026-12-19", {}), [])
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM schedule").fetchone()[0], 29)

    def test_seventy_percent_not_weak(self):
        sid = self.start()
        with self.store.db:
            self.store.db.execute("UPDATE baseline SET correct=7,attempted=10")
        self.assertEqual(self.engine.adapt(sid)["scheduled"], [])

    def test_markdown_conflict_backed_up_on_force(self):
        self.store.export()
        (self.root / "PROGRESS.md").write_text("Manual change")
        with self.assertRaises(ValueError):
            self.store.export()
        self.store.export(force=True)
        self.assertTrue(list((self.root / ".state/manual-backups").glob("*/PROGRESS.md")))

    def test_relay_redelivery_returns_same_response(self):
        request = {"id": "start-event", "action": "start", "date": "2026-11-23"}
        response = safe_dispatch(self.store, self.router, request)
        self.assertTrue(response["ok"])
        self.assertEqual(response, safe_dispatch(self.store, self.router, request))
        bad = {**request, "day": 3}
        self.assertFalse(safe_dispatch(self.store, self.router, bad)["ok"])

    def test_all_domains_are_in_curriculum_and_calendar(self):
        self.assertEqual(set(self.engine.curriculum), {f"D{i}" for i in range(1,9)})
        domains = set()
        for row in self.store.db.execute("SELECT domains FROM schedule"):
            domains.update(json.loads(row[0]))
        self.assertEqual(domains, set(self.engine.curriculum))

    def test_provider_payloads_and_incomplete_outputs(self):
        router = Router(self.root)
        class Response:
            def __init__(self, data):
                self.data = json.dumps(data).encode()
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def read(self):
                return self.data
        with patch.dict("os.environ", {"OPENAI_API_KEY":"test", "ANTHROPIC_API_KEY":"test", "OPENAI_MODEL":"test-openai", "ANTHROPIC_MODEL":"test-anthropic"}):
            with patch("urllib.request.urlopen", return_value=Response({"status":"completed", "output":[{"content":[{"type":"output_text", "text":'{"ok":true}'}]}]})) as call:
                result, _ = router.call("teacher", "tutor", {"kind":"discussion"})
                self.assertTrue(result["ok"])
                self.assertFalse(json.loads(call.call_args.args[0].data)["store"])
            with patch("urllib.request.urlopen", return_value=Response({"stop_reason":"end_turn", "content":[{"type":"text", "text":'{"approved":true}'}]})):
                result, _ = router.call("reviewer", "reviewer", {})
                self.assertTrue(result["approved"])
            with patch("urllib.request.urlopen", return_value=Response({"status":"incomplete"})):
                with self.assertRaises(ModelError):
                    router.call("teacher", "tutor", {})

    def test_invalid_model_json_rejected(self):
        for text in ("not json", "[]", "null"):
            with self.assertRaises(ModelError):
                object_json(text)

    def test_lesson_paging_preserves_full_content(self):
        sid = self.start()
        s = self.store.session(sid)
        s["phase"] = "discussion"
        s["state"]["lesson"] = "paragraph\n" * 1200
        with self.store.db:
            self.store.save_session(s)
        view = self.engine.view(sid)
        self.assertLessEqual(len(view["lesson"]), 4200)
        self.assertGreater(view["pages"], 1)
        with self.assertRaises(ValueError):
            self.engine.continue_quiz(sid)
        for _ in range(view["pages"]-1):
            view = self.engine.more(sid)
        self.assertEqual(view["page"], view["pages"])
        self.assertEqual(self.engine.continue_quiz(sid)["phase"], "quiz")

    def test_answer_commits_when_planner_is_unavailable(self):
        sid = self.start()
        q = self.engine.next(sid)["question"]
        with self.store.db:
            self.store.db.execute("UPDATE baseline SET correct=2,attempted=4 WHERE domain=?", (q["domain"],))
        self.router.fail = True
        response = safe_dispatch(self.store, self.router, {"id":"persist-first", "action":"answer",
                                 "question_id":q["question_id"], "answer":"B"})
        self.assertTrue(response["ok"])
        self.assertIn("adaptation_pending", response["result"])
        self.assertEqual(self.store.scores()[q["domain"]]["attempted"], 5)
        self.router.fail = False
        self.assertEqual(len(self.engine.adapt(sid)["scheduled"]), 1)

    def test_bridge_checkpoints_before_official_end(self):
        import types
        order = []
        class Relay:
            def end(self):
                order.append(("official", self.last_summary))
        adapter = types.SimpleNamespace(Relay=Relay, __file__="official.py")
        def checkpoint():
            order.append(("checkpoint", "saved"))
            return "saved summary"
        with patch("scripts.skillsimm_bridge.close_learning", side_effect=checkpoint):
            patch_adapter(adapter).Relay().end()
        self.assertEqual(order, [("checkpoint", "saved"), ("official", "saved summary")])
        self.assertTrue(adapter.__file__.endswith("skillsimm_bridge.py"))

    def test_bridge_does_not_end_if_checkpoint_fails(self):
        import types
        calls = []
        class Relay:
            def end(self):
                calls.append("ended")
        adapter = types.SimpleNamespace(Relay=Relay)
        with patch("scripts.skillsimm_bridge.close_learning", side_effect=RuntimeError("outage")):
            with self.assertRaises(RuntimeError):
                patch_adapter(adapter).Relay().end()
        self.assertEqual(calls, [])

    def test_bridge_closes_actual_learning_state_without_credentials(self):
        sid = self.start()
        summary = close_learning(self.root)
        self.assertIn("Practice score: 0/0", summary)
        self.assertEqual(self.store.session(sid)["phase"], "closed")

    def test_fresh_bootstrap_is_empty_and_preserves_existing_files(self):
        from datetime import date, timedelta
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copy(ROOT / "curriculum.json", root / "curriculum.json")
            initialize(root, (date.today()+timedelta(days=90)).isoformat())
            fresh = Store(root)
            try:
                fresh.migrate()
                self.assertEqual(sum(v["attempted"] for v in fresh.scores().values()), 0)
                self.assertEqual(fresh.db.execute("SELECT COUNT(*) FROM schedule").fetchone()[0], 29)
                with self.assertRaises(ValueError):
                    initialize(root, (date.today()+timedelta(days=90)).isoformat())
            finally:
                fresh.close()


if __name__ == "__main__":
    unittest.main()
