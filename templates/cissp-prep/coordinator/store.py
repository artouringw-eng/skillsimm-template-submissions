"""Transactional learner state and one-time migration from the original workspace."""
import hashlib
import json
import os
import re
import shutil
import sqlite3
from datetime import date, timedelta
from pathlib import Path

DOMAINS = {"D1": "Security & Risk Management", "D2": "Asset Security",
           "D3": "Security Architecture & Engineering", "D4": "Communication & Network Security",
           "D5": "Identity & Access Management", "D6": "Security Assessment & Testing",
           "D7": "Security Operations", "D8": "Software Development Security"}


def table_rows(text):
    return [[s.strip() for s in line.strip().strip("|").split("|")]
            for line in text.splitlines() if line.startswith("|")]


def clean(value):
    return str(value).replace("|", "\\|").replace("\n", " ")


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.state = self.root / ".state"
        self.state.mkdir(mode=0o700, exist_ok=True)
        os.chmod(self.state, 0o700)
        self.db = sqlite3.connect(self.state / "learning.sqlite3", timeout=15)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS baseline (domain TEXT PRIMARY KEY, correct INTEGER, attempted INTEGER);
        CREATE TABLE IF NOT EXISTS schedule (
          day INTEGER PRIMARY KEY, date TEXT UNIQUE, domains TEXT, topics TEXT, minutes INTEGER);
        CREATE TABLE IF NOT EXISTS mistakes (
          id TEXT PRIMARY KEY, date TEXT, domain TEXT, gist TEXT, answer TEXT, correct TEXT, rule TEXT);
        CREATE TABLE IF NOT EXISTS facts (domain TEXT, fact TEXT, PRIMARY KEY(domain,fact));
        CREATE TABLE IF NOT EXISTS sessions (
          id TEXT PRIMARY KEY, date TEXT, day INTEGER, phase TEXT, state TEXT);
        CREATE UNIQUE INDEX IF NOT EXISTS one_active_session ON sessions((1)) WHERE phase != 'closed';
        CREATE TABLE IF NOT EXISTS questions (
          id TEXT PRIMARY KEY, session_id TEXT REFERENCES sessions(id), phase TEXT, domain TEXT,
          topic TEXT, body TEXT, review TEXT, provenance TEXT, approved INTEGER);
        CREATE TABLE IF NOT EXISTS attempts (
          id TEXT PRIMARY KEY, question_id TEXT UNIQUE REFERENCES questions(id),
          session_id TEXT REFERENCES sessions(id), date TEXT, answer TEXT, correct INTEGER);
        CREATE TABLE IF NOT EXISTS revisions (
          id INTEGER PRIMARY KEY, domain TEXT, date TEXT, minutes INTEGER, reason TEXT, provenance TEXT,
          UNIQUE(domain,date));
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY, session_id TEXT, kind TEXT, payload TEXT);
        CREATE TABLE IF NOT EXISTS receipts (id TEXT PRIMARY KEY, request TEXT, response TEXT);
        ''')

    def close(self):
        self.db.close()

    def get(self, key, default=None):
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def put(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, json.dumps(value)))

    def event(self, sid, kind, payload):
        self.db.execute("INSERT INTO events(session_id,kind,payload) VALUES (?,?,?)",
                        (sid, kind, json.dumps(payload)))

    def migrate(self):
        if self.get("migrated"):
            return {"already_imported": True, "scores": self.scores()}
        paths = [Path(x) for x in ("PLAN.md", "PROGRESS.md", "MISTAKES.md", "AGENTS.md")]
        paths += [Path("CHEATSHEETS") / f"{d}.md" for d in DOMAINS]
        texts = {str(p): (self.root / p).read_text() for p in paths}
        baseline = []
        for row in table_rows(texts["PROGRESS.md"]):
            domain = row[0].split()[0]
            if domain in DOMAINS and len(row) >= 3:
                correct, attempted = int(row[1]), int(row[2])
                if not 0 <= correct <= attempted:
                    raise ValueError("Invalid baseline score")
                baseline.append((domain, correct, attempted))
        if {r[0] for r in baseline} != set(DOMAINS) or len(baseline) != 8:
            raise ValueError("Expected exactly one baseline row for each of eight domains")
        # Original dates are supplied in PLAN; the header carries the year.
        year = int(re.search(r"\b(20\d\d)\b", texts["PLAN.md"]).group())
        schedule = []
        from datetime import datetime
        for row in table_rows(texts["PLAN.md"]):
            if not row[0].isdigit():
                continue
            when = date.fromisoformat(row[1]) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", row[1]) else datetime.strptime(f"{row[1]} {year}", "%a %b %d %Y").date()
            topics = row[-1]
            domains = re.findall(r"D[1-8]", " ".join(row[2:]))
            minutes = 240 if when.weekday() >= 5 else 120
            if "Practice exam" in topics:
                minutes = 180
            if "Light review" in topics or "Rest." in topics:
                minutes = 30
            if "EXAM DAY" in topics:
                minutes = 0
            schedule.append((int(row[0]), when.isoformat(), json.dumps(list(dict.fromkeys(domains))), topics, minutes))
        if not schedule:
            raise ValueError("No calendar rows found")
        backup = self.state / "originals"
        for p in paths:
            dest = backup / p
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists():
                shutil.copy2(self.root / p, dest)
            elif dest.read_text() != texts[str(p)]:
                raise ValueError("Original backup differs; migration requires manual recovery")
        with self.db:
            self.db.executemany("INSERT INTO baseline VALUES (?,?,?)", baseline)
            self.db.executemany("INSERT INTO schedule VALUES (?,?,?,?,?)", schedule)
            for i, row in enumerate(table_rows(texts["MISTAKES.md"])):
                if len(row) == 6 and row[1] in DOMAINS:
                    self.db.execute("INSERT INTO mistakes VALUES (?,?,?,?,?,?,?)", (f"import-{i}", *row))
            for d in DOMAINS:
                for line in texts[f"CHEATSHEETS/{d}.md"].splitlines():
                    if line.startswith("- "):
                        self.db.execute("INSERT OR IGNORE INTO facts VALUES (?,?)", (d, line[2:]))
            self.put("exam_date", max(r[1] for r in schedule))
            self.put("original_plan", texts["PLAN.md"])
            self.put("original_progress", texts["PROGRESS.md"])
            self.put("schema_version", 1)
            self.put("migrated", True)
            self.put("export_hashes", {p: hashlib.sha256(t.encode()).hexdigest() for p, t in texts.items()
                                       if p != "AGENTS.md"})
        return {"already_imported": False, "scores": self.scores()}

    def require_migration(self):
        if not self.get("migrated"):
            raise ValueError("Run python3 -m coordinator migrate first")

    def scores(self):
        out = {d: {"correct": 0, "attempted": 0} for d in DOMAINS}
        for row in self.db.execute("SELECT * FROM baseline"):
            out[row["domain"]] = {"correct": row["correct"], "attempted": row["attempted"]}
        for row in self.db.execute('''SELECT q.domain, SUM(a.correct) correct, COUNT(*) attempted
                                    FROM attempts a JOIN questions q ON a.question_id=q.id GROUP BY q.domain'''):
            out[row["domain"]]["correct"] += row["correct"]
            out[row["domain"]]["attempted"] += row["attempted"]
        for value in out.values():
            n = value["attempted"]
            value["percent"] = round(100 * value["correct"] / n, 1) if n else None
            value["reliable"] = n >= 5
        return out

    def topics(self):
        return [dict(r) for r in self.db.execute('''SELECT q.domain,q.topic,COUNT(*) attempted,SUM(a.correct) correct
                    FROM attempts a JOIN questions q ON q.id=a.question_id GROUP BY q.domain,q.topic''')]

    def active(self):
        row = self.db.execute("SELECT * FROM sessions WHERE phase != 'closed'").fetchone()
        return self.session(row["id"]) if row else None

    def session(self, sid):
        row = self.db.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
        if not row:
            raise ValueError("Unknown session")
        result = dict(row)
        result["state"] = json.loads(result["state"])
        return result

    def save_session(self, s):
        self.db.execute("UPDATE sessions SET phase=?,state=? WHERE id=?",
                        (s["phase"], json.dumps(s["state"]), s["id"]))

    def summary(self, sid):
        rows = self.db.execute("SELECT COUNT(*) n,COALESCE(SUM(correct),0) c FROM attempts WHERE session_id=?", (sid,)).fetchone()
        return {"session_id": sid, "correct": rows["c"], "attempted": rows["n"],
                "domains": self.scores(), "topic_performance": self.topics()}

    def export(self, force=False):
        self.require_migration()
        scores = self.scores()
        progress = ["# CISSP Progress", "", f"Exam: {self.get('exam_date')}. Generated from .state/learning.sqlite3.",
                    "", "## Domain scores (baseline + assessed attempts)",
                    "| Domain | Correct | Attempted | % | Evidence |", "|---|---|---|---|---|"]
        for d, v in scores.items():
            progress.append(f"| {d} {DOMAINS[d]} | {v['correct']} | {v['attempted']} | {v['percent']} | {'5+ attempts' if v['reliable'] else 'limited'} |")
        total_c, total_n = sum(v['correct'] for v in scores.values()), sum(v['attempted'] for v in scores.values())
        progress += [f"| **Total** | {total_c} | {total_n} | {round(100*total_c/total_n,1) if total_n else 0} | |",
                     "", "## Session log", "| Date | Session | Phase | Score |", "|---|---|---|---|"]
        for s in self.db.execute("SELECT * FROM sessions ORDER BY date,id"):
            summary = self.summary(s["id"])
            progress.append(f"| {s['date']} | {s['id']} | {s['phase']} | {summary['correct']}/{summary['attempted']} |")
        active = self.active()
        progress += ["", f"Current day: {active['day'] if active else self.get('current_day', 1)}",
                     "", "## Imported record (retained verbatim)", self.get("original_progress")]
        mistakes = ["# Mistakes Log", "", "| Date | Domain | Question gist | My answer | Correct | Rule / why |", "|---|---|---|---|---|---|"]
        for row in self.db.execute("SELECT * FROM mistakes ORDER BY date,id"):
            mistakes.append("| " + " | ".join(clean(row[k]) for k in ("date", "domain", "gist", "answer", "correct", "rule")) + " |")
        adjustments = ["", "## Coordinator adjustments"]
        for row in self.db.execute("SELECT * FROM revisions ORDER BY date,id"):
            adjustments.append(f"- {row['date']}: {row['minutes']} minutes (added: weak {row['domain']}) — {row['reason']}")
        progress += adjustments
        views = {"PLAN.md": self.get("original_plan") + "\n" + "\n".join(adjustments) + "\n",
                 "PROGRESS.md": "\n".join(progress) + "\n", "MISTAKES.md": "\n".join(mistakes) + "\n"}
        for d in DOMAINS:
            facts = [r[0] for r in self.db.execute("SELECT fact FROM facts WHERE domain=? ORDER BY rowid", (d,))]
            views[f"CHEATSHEETS/{d}.md"] = f"# {d} — {DOMAINS[d]}\n\n" + "\n".join(f"- {x}" for x in facts) + "\n"
        hashes = self.get("export_hashes", {})
        conflicts = [p for p in views if (self.root/p).exists() and hashes.get(p) != hashlib.sha256((self.root/p).read_bytes()).hexdigest()]
        if conflicts and not force:
            raise ValueError("Manual Markdown edits detected: " + ", ".join(conflicts) + ". Import facts explicitly or back up edits before export --force.")
        if conflicts:
            from time import time_ns
            dest = self.state / "manual-backups" / str(time_ns())
            for p in conflicts:
                (dest / p).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(self.root / p, dest / p)
        for p, content in views.items():
            target = self.root / p
            target.parent.mkdir(exist_ok=True)
            temp = target.with_suffix(target.suffix + ".tmp")
            temp.write_text(content)
            temp.replace(target)
            # Commit per-file receipt so recovery from a partial export is safe.
            hashes[p] = hashlib.sha256(content.encode()).hexdigest()
            with self.db:
                self.put("export_hashes", hashes)
        return {"exported": list(views)}

    def candidates(self, domain, today, settings):
        when = date.fromisoformat(today)
        rows = self.db.execute("SELECT * FROM schedule WHERE date>? AND date<=? ORDER BY date",
                               (today, (when + timedelta(days=3)).isoformat())).fetchall()
        result = []
        for row in rows:
            if row["date"] >= self.get("exam_date") or "Rest." in row["topics"] or "Light review" in row["topics"]:
                continue
            already = self.db.execute("SELECT 1 FROM revisions WHERE domain=? AND date>=?", (domain, today)).fetchone()
            if already:
                return []
            used = self.db.execute("SELECT COALESCE(SUM(minutes),0) FROM revisions WHERE date=?", (row["date"],)).fetchone()[0]
            cap = settings.get("weekend_minutes", 300) if date.fromisoformat(row["date"]).weekday() >= 5 else settings.get("weekday_minutes", 180)
            if row["minutes"] + used + 20 <= cap:
                result.append(row["date"])
        return result
