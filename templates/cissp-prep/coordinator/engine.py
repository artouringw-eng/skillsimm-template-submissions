"""Learning state machine. Only validated operations may change learner evidence."""
import hashlib
import json
import uuid
from datetime import date

from .models import ModelError
from .store import DOMAINS


def nonempty(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ModelError(f"Invalid {name}")


def pages(text, size=4200):
    result = []
    while text:
        cut = len(text) if len(text) <= size else text.rfind("\n", 0, size)
        if cut <= 0:
            cut = min(size, len(text))
        result.append(text[:cut])
        text = text[cut:].lstrip("\n")
    return result or [""]


def question_valid(q):
    if not isinstance(q, dict) or not isinstance(q.get("domain"), str) or q["domain"] not in DOMAINS:
        raise ModelError("Invalid question domain")
    for field in ("topic", "stem", "rule"):
        nonempty(q.get(field), field)
        if len(q[field]) > 1800:
            raise ModelError("Question content exceeds chat limits")
    options = q.get("options")
    if not isinstance(options, dict) or set(options) != set("ABCD"):
        raise ModelError("Question needs four options A–D")
    for v in options.values():
        nonempty(v, "option")
        if len(v) > 400:
            raise ModelError("Option exceeds chat limits")
    if len(set(options.values())) != 4 or not isinstance(q.get("answer"), str) or q["answer"] not in options:
        raise ModelError("Invalid or duplicate choices")
    explanations = q.get("explanations")
    if not isinstance(explanations, dict) or set(explanations) != set("ABCD"):
        raise ModelError("Explain all four choices")
    for v in explanations.values():
        nonempty(v, "explanation")
        if len(v) > 500:
            raise ModelError("Explanation exceeds chat limits")


class Engine:
    def __init__(self, store, router):
        self.store, self.router = store, router
        self.settings = router.learning
        self.curriculum = json.loads((store.root / "curriculum.json").read_text())
        for key, low, high, default in (("topic_questions", 8, 12, 8), ("weak_questions", 1, 2, 2), ("warmup_questions", 0, 3, 3)):
            n = self.settings.get(key, default)
            if type(n) is not int or not low <= n <= high:
                raise ValueError(f"{key} must be {low}–{high}")

    def call(self, sid, operation, role, skill, payload):
        # Successfully received outputs survive crashes and avoid repeat API charges.
        key = "call:" + hashlib.sha256(json.dumps([sid, operation, payload], sort_keys=True).encode()).hexdigest()
        cached = self.store.get(key)
        if cached:
            return cached["value"], cached["identity"]
        value, identity = self.router.call(role, skill, payload)
        with self.store.db:
            self.store.put(key, {"value": value, "identity": identity})
            self.store.event(sid, operation, {"identity": identity, "cache_key": key})
        return value, identity

    def session(self, sid=None):
        s = self.store.session(sid) if sid else self.store.active()
        if not s:
            raise ValueError("No active session; use start")
        return s

    def context(self, s):
        return {"day": s["day"], "date": s["date"], "topics": s["state"]["topics"],
                "domains": s["state"]["domains"], "scores": self.store.scores(),
                "topic_performance": self.store.topics(), "curriculum": self.curriculum}

    def start(self, today=None, day=None):
        self.store.require_migration()
        current = self.store.active()
        if current:
            if day and day != current["day"]:
                raise ValueError("An active session exists; end it before changing day")
            return self.view(current["id"])
        today = today or date.today().isoformat()
        row = self.store.db.execute("SELECT * FROM schedule WHERE day=?" if day else "SELECT * FROM schedule WHERE date=?",
                                    (day if day else today,)).fetchone()
        if not row:
            raise ValueError("No calendar entry for this date; select a planned --day explicitly")
        if today >= self.store.get("exam_date"):
            raise ValueError("Exam deadline reached; explicitly revise the schedule before starting new study")
        if "EXAM DAY" in row["topics"] or "Rest." in row["topics"]:
            return {"phase": "rest", "message": row["topics"]}
        domains = json.loads(row["domains"]) or list(DOMAINS)
        focus = [r[0] for r in self.store.db.execute("SELECT domain FROM revisions WHERE date=?", (row["date"],))]
        domains = list(dict.fromkeys(domains + focus))
        sid = uuid.uuid4().hex
        warmup = self.settings.get("warmup_questions", 3) if self.store.db.execute("SELECT 1 FROM mistakes LIMIT 1").fetchone() else 0
        state = {"topics": row["topics"], "domains": domains, "warmup_target": warmup,
                 "quiz_target": self.settings.get("topic_questions", 8) + self.settings.get("weak_questions", 2)}
        with self.store.db:
            self.store.db.execute("INSERT INTO sessions VALUES (?,?,?,?,?)",
                                  (sid, today, row["day"], "warmup" if warmup else "lesson", json.dumps(state)))
            self.store.put("current_day", row["day"])
        return self.view(sid)

    def pending(self, s):
        return self.store.db.execute('''SELECT q.* FROM questions q LEFT JOIN attempts a ON a.question_id=q.id
            WHERE q.session_id=? AND q.approved=1 AND a.id IS NULL ORDER BY q.rowid LIMIT 1''', (s["id"],)).fetchone()

    def public_question(self, row):
        q = json.loads(row["body"])
        return {"question_id": row["id"], "domain": q["domain"], "topic": q["topic"],
                "stem": q["stem"], "options": q["options"]}

    def view(self, sid=None):
        s = self.session(sid)
        result = {"session_id": s["id"], "day": s["day"], "phase": s["phase"], "topics": s["state"]["topics"]}
        row = self.pending(s)
        if row and s["phase"] != "closed":
            result["question"] = self.public_question(row)
        if s["phase"] == "discussion":
            lesson_pages = pages(s["state"].get("lesson", ""))
            index = s["state"].get("lesson_page", 0)
            result["lesson"] = lesson_pages[index]
            result["page"] = index + 1
            result["pages"] = len(lesson_pages)
            result["message"] = "Use /more for the next page." if index < len(lesson_pages)-1 else "Ask a question, or continue when ready for the quiz."
        if s["phase"] in ("debrief", "closed"):
            result["summary"] = self.store.summary(s["id"])
        return result

    def next(self, sid=None):
        s = self.session(sid)
        if self.pending(s):
            return self.view(s["id"])
        if s["phase"] in ("warmup", "quiz"):
            self.make_question(s)
        elif s["phase"] == "lesson":
            self.teach(s)
        return self.view(s["id"])

    def make_question(self, s):
        db = self.store.db
        count = db.execute("SELECT COUNT(*) FROM attempts a JOIN questions q ON q.id=a.question_id WHERE q.session_id=? AND q.phase=?",
                           (s["id"], s["phase"])).fetchone()[0]
        scores = self.store.scores()
        weakest = sorted(DOMAINS, key=lambda d: scores[d]["percent"] if scores[d]["percent"] is not None else -1)
        context = self.context(s)
        if s["phase"] == "warmup":
            misses = [dict(r) for r in db.execute("SELECT * FROM mistakes ORDER BY date DESC,rowid DESC LIMIT 15")]
            miss = misses[count % len(misses)]
            domain = miss["domain"]
            context["review_mistake"] = miss
        elif count >= self.settings.get("topic_questions", 8):
            domain = weakest[(count - self.settings.get("topic_questions", 8)) % len(weakest)]
        else:
            domain = s["state"]["domains"][count % len(s["state"]["domains"]) ]
        context.update({"required_domain": domain, "phase": s["phase"], "question_number": count + 1})
        context["avoid_stems"] = [json.loads(r[0])["stem"] for r in db.execute("SELECT body FROM questions WHERE session_id=?", (s["id"],))]
        # At most three candidates per invocation. Rejected candidates remain auditable.
        for _ in range(3):
            serial = db.execute("SELECT COUNT(*) FROM questions WHERE session_id=?", (s["id"],)).fetchone()[0]
            q, author = self.call(s["id"], f"author-{serial}", "teacher", "question-author", context)
            try:
                question_valid(q)
                if q["domain"] != domain:
                    raise ModelError("Question did not use requested domain")
            except ModelError:
                with db:
                    db.execute("INSERT INTO questions VALUES (?,?,?,?,?,?,?,?,?)",
                               (uuid.uuid4().hex, s["id"], s["phase"], domain, "invalid", json.dumps(q),
                                json.dumps({"approved": False, "reason": "Invalid question structure"}), json.dumps({"author": author}), 0))
                continue
            reviewer = self.router.identity("reviewer")
            if reviewer["provider"] == author["provider"]:
                raise ModelError("Reviewer must use the other provider for independent question review")
            review, reviewer = self.call(s["id"], f"review-{serial}", "reviewer", "reviewer", {"kind": "question", "question": q})
            approved = review.get("approved") is True and review.get("answer") == q["answer"] and isinstance(review.get("reason"), str) and bool(review["reason"].strip())
            with db:
                db.execute("INSERT INTO questions VALUES (?,?,?,?,?,?,?,?,?)",
                           (uuid.uuid4().hex, s["id"], s["phase"], domain, q["topic"], json.dumps(q), json.dumps(review),
                            json.dumps({"author": author, "reviewer": reviewer}), int(approved)))
            if approved:
                return
        raise ModelError("Three candidate questions failed review; retry next to request new candidates")

    def teach(self, s):
        value, identity = self.call(s["id"], "lesson", "teacher", "tutor", {"kind": "lesson", **self.context(s)})
        nonempty(value.get("lesson"), "lesson")
        facts = value.get("facts")
        if not isinstance(facts, list) or not 3 <= len(facts) <= 8:
            raise ModelError("Lesson requires 3–8 key facts")
        for fact in facts:
            if not isinstance(fact, dict) or not isinstance(fact.get("domain"), str) or fact["domain"] not in DOMAINS:
                raise ModelError("Invalid lesson fact domain")
            nonempty(fact.get("fact"), "fact")
        review, reviewer = self.call(s["id"], "lesson-review", "reviewer", "reviewer", {"kind": "lesson", "lesson": value})
        if reviewer["provider"] == identity["provider"] or review.get("approved") is not True:
            raise ModelError("Lesson not approved by an independent reviewer; use retry-content to regenerate")
        with self.store.db:
            for fact in facts:
                self.store.db.execute("INSERT OR IGNORE INTO facts VALUES (?,?)", (fact["domain"], fact["fact"]))
            s["state"]["lesson"] = value["lesson"]
            s["phase"] = "discussion"
            self.store.save_session(s)

    def discuss(self, text, sid=None):
        s = self.session(sid)
        if s["phase"] != "discussion":
            raise ValueError("Discussion is available after the lesson, before the quiz")
        nonempty(text, "learner question")
        # No saved question keys, unpublished candidate questions or future answers are sent.
        value, _ = self.call(s["id"], "discussion", "teacher", "tutor",
                             {"kind": "discussion", **self.context(s), "lesson": s["state"]["lesson"], "learner_question": text})
        nonempty(value.get("reply"), "reply")
        return {"session_id": s["id"], "reply": value["reply"]}

    def continue_quiz(self, sid=None):
        s = self.session(sid)
        if s["phase"] not in ("discussion", "quiz"):
            raise ValueError("Continue is available after the lesson")
        if s["state"].get("lesson_page", 0) < len(pages(s["state"].get("lesson", "")))-1:
            raise ValueError("Read the remaining lesson pages with more before starting the quiz")
        with self.store.db:
            s["phase"] = "quiz"
            self.store.save_session(s)
        return self.view(s["id"])

    def more(self, sid=None):
        s = self.session(sid)
        if s["phase"] != "discussion":
            raise ValueError("More is available during a paged lesson")
        with self.store.db:
            s["state"]["lesson_page"] = min(s["state"].get("lesson_page", 0)+1, len(pages(s["state"]["lesson"]))-1)
            self.store.save_session(s)
        return self.view(s["id"])

    def answer(self, qid, answer, attempt_id):
        answer = answer.strip().upper()
        if answer not in "ABCD" or len(answer) != 1:
            raise ValueError("Answer must be A, B, C, or D")
        nonempty(attempt_id, "attempt id")
        db = self.store.db
        row = db.execute("SELECT * FROM questions WHERE id=?", (qid,)).fetchone()
        if not row or not row["approved"]:
            raise ValueError("Only a reviewed, delivered question can be answered")
        q = json.loads(row["body"])
        s = self.store.session(row["session_id"])
        with db:
            prior = db.execute("SELECT * FROM attempts WHERE id=? OR question_id=?", (attempt_id, qid)).fetchall()
            if prior:
                if len(prior) != 1 or prior[0]["question_id"] != qid or prior[0]["answer"] != answer:
                    raise ValueError("Conflicting replay: this attempt/question already has a different answer")
            else:
                pending = self.pending(s)
                if s["phase"] not in ("warmup", "quiz") or not pending or pending["id"] != qid:
                    raise ValueError("This is not the pending question")
                correct = int(answer == q["answer"])
                db.execute("INSERT INTO attempts VALUES (?,?,?,?,?,?)", (attempt_id, qid, s["id"], s["date"], answer, correct))
                if not correct:
                    db.execute("INSERT INTO mistakes VALUES (?,?,?,?,?,?,?)",
                               (attempt_id, s["date"], q["domain"], q["stem"], answer + ": " + q["options"][answer],
                                q["answer"] + ": " + q["options"][q["answer"]], q["rule"]))
                db.execute("INSERT OR IGNORE INTO facts VALUES (?,?)", (q["domain"], q["rule"]))
                count = db.execute("SELECT COUNT(*) FROM attempts a JOIN questions q ON q.id=a.question_id WHERE q.session_id=? AND q.phase=?",
                                   (s["id"], s["phase"])).fetchone()[0]
                target = s["state"]["warmup_target"] if s["phase"] == "warmup" else s["state"]["quiz_target"]
                if count >= target:
                    s["phase"] = "lesson" if s["phase"] == "warmup" else "debrief"
                self.store.save_session(s)
        return {"question_id": qid, "correct": answer == q["answer"], "answer": q["answer"],
                "explanations": q["explanations"], "rule": q["rule"], "phase": s["phase"]}

    def adapt(self, sid=None):
        s = self.session(sid)
        updates, deferred = [], []
        for domain, score in self.store.scores().items():
            if score["attempted"] < 5 or score["correct"] / score["attempted"] >= .7:
                continue
            candidates = self.store.candidates(domain, s["date"], self.settings)
            if not candidates:
                deferred.append({"domain": domain, "reason": "Already scheduled, or no capacity before the deadline within three days"})
                continue
            proposal, identity = self.call(s["id"], f"plan-{domain}", "planner", "planner",
                                           {"domain": domain, "score": score, "allowed_dates": candidates,
                                            "minutes": 20, "existing_topics": s["state"]["topics"]})
            if proposal.get("date") not in candidates:
                raise ModelError("Planner selected an unavailable date; use retry-content to regenerate")
            nonempty(proposal.get("reason"), "plan reason")
            # Revalidate capacity immediately before commit.
            if proposal["date"] not in self.store.candidates(domain, s["date"], self.settings):
                raise ValueError("Schedule changed; retry adaptation")
            reason = f"{score['correct']}/{score['attempted']} ({score['percent']}%) below 70%. {proposal['reason']}"
            with self.store.db:
                self.store.db.execute("INSERT INTO revisions(domain,date,minutes,reason,provenance) VALUES (?,?,?,?,?)",
                                      (domain, proposal["date"], 20, reason, json.dumps(identity)))
            updates.append({"domain": domain, "date": proposal["date"], "minutes": 20, "reason": reason})
        return {"scheduled": updates, "deferred": deferred}

    def end(self, sid=None):
        s = self.session(sid)
        if s["phase"] == "closed":
            return self.view(s["id"])
        adaptation = self.adapt(s["id"])
        with self.store.db:
            s["state"]["ended_from"] = s["phase"]
            s["phase"] = "closed"
            self.store.save_session(s)
        return {**self.view(s["id"]), "adaptation": adaptation}

    def retry_content(self, sid=None):
        s = self.session(sid)
        # Discard only unsuccessful/uncommitted model output caches for this session.
        # Published questions and committed lessons/attempts remain immutable.
        with self.store.db:
            for row in self.store.db.execute("SELECT payload FROM events WHERE session_id=?", (s["id"],)).fetchall():
                key = json.loads(row[0]).get("cache_key")
                if key:
                    self.store.db.execute("DELETE FROM meta WHERE key=?", (key,))
            self.store.event(s["id"], "retry-content", {"reason": "Explicit model-output retry"})
        return self.view(s["id"])
