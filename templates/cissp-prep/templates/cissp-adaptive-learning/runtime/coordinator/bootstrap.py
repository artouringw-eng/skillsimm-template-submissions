"""Create an empty learner workspace for users of the public template."""
import json
from datetime import date, timedelta

from .store import DOMAINS


def initialize(root, exam_date):
    exam = date.fromisoformat(exam_date)
    if exam <= date.today():
        raise ValueError("Choose a future exam date")
    names = ["PLAN.md", "PROGRESS.md", "MISTAKES.md"]
    if any((root / name).exists() for name in names) or (root / "CHEATSHEETS").exists():
        raise ValueError("Study files already exist; use migrate to preserve them")
    curriculum = json.loads((root / "curriculum.json").read_text())
    days = ["D1", "D1", "D1", "D3", "D3", "D3", "review", "D4", "D4", "D4", "D4", "D5", "D5", "review",
            "D7", "D7", "D7", "D7", "D2", "D6", "D8", "review", "review", "review", "review", "review", "light", "rest", "exam"]
    lines = [f"# CISSP study plan {exam.year}", "", "| Day | Date | Domain | Topics |", "|---|---|---|---|"]
    for i, domain in enumerate(days):
        when = exam - timedelta(days=28-i)
        if domain in DOMAINS:
            # Split repeated domain days across its full curriculum.
            indexes = [j for j, d in enumerate(days) if d == domain]
            part = indexes.index(i)
            topics = "; ".join(curriculum[domain]["topics"][part::len(indexes)])
        else:
            topics = {"review":"Mixed retrieval practice D1 D2 D3 D4 D5 D6 D7 D8",
                      "light":"Light review: cheatsheets", "rest":"Rest. 30-minute skim only", "exam":"EXAM DAY"}[domain]
        lines.append(f"| {i+1} | {when.isoformat()} | {domain} | {topics} |")
    (root / "PLAN.md").write_text("\n".join(lines) + "\n")
    progress = ["# CISSP Progress", "", "| Domain | Correct | Attempted | % |", "|---|---|---|---|"]
    progress += [f"| {d} {name} | 0 | 0 | — |" for d, name in DOMAINS.items()]
    (root / "PROGRESS.md").write_text("\n".join(progress) + "\n")
    (root / "MISTAKES.md").write_text("# Mistakes Log\n\n| Date | Domain | Question gist | My answer | Correct | Rule / why |\n|---|---|---|---|---|---|\n")
    (root / "CHEATSHEETS").mkdir()
    for d in DOMAINS:
        (root / "CHEATSHEETS" / f"{d}.md").write_text(f"# {d} — {DOMAINS[d]}\n")
    if not (root / "AGENTS.md").exists():
        (root / "AGENTS.md").write_text("# Coordinator workspace\nUse the Python coordinator. Read skills/coordinator.md. SQLite is authoritative.\n")
