# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp==1.30.0", "httpx==0.28.1"]
# ///
"""Wrap the official desk adapter so /end checkpoints learning before ending the desk.

Install the official adapter at .skillsimm/skillsimm_desk.py first. This file has
the same CLI as that adapter. Attach using THIS file so its hooks invoke this wrapper.
No messages are sent except through the explicitly invoked official desk operations.
"""
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from coordinator.__main__ import safe_dispatch
from coordinator.models import Router
from coordinator.store import Store


def close_learning(root=ROOT):
    store = Store(root)
    try:
        if not store.get("migrated"):
            raise RuntimeError("Initialize/migrate the learning workspace before ending this desk")
        session = store.active()
        if session:
            response = safe_dispatch(store, Router(root), {
                "id": "desk-end-" + session["id"], "action": "end", "session_id": session["id"]})
            if not response["ok"]:
                raise RuntimeError("Learning checkpoint could not close; retry locally before /end")
            sid = session["id"]
        else:
            row = store.db.execute("SELECT id FROM sessions ORDER BY rowid DESC LIMIT 1").fetchone()
            sid = row[0] if row else None
        if not sid:
            return "CISSP learning session ended. No practice attempts were recorded."
        result = store.summary(sid)
        lines = ["CISSP learning session saved.", f"Session: {sid}", f"Practice score: {result['correct']}/{result['attempted']}"]
        for domain, score in result["domains"].items():
            lines.append(f"{domain}: {score['correct']}/{score['attempted']} ({score['percent']}%)")
        revisions = store.db.execute("SELECT domain,date FROM revisions WHERE date>=? ORDER BY date LIMIT 8",
                                     (store.session(sid)["date"],)).fetchall()
        lines += [f"Next focus: {r['date']} — {r['domain']}, 20 minutes" for r in revisions]
        lines.append("Memory and Markdown exports remain in the local workspace. Complete End the session in SkillSimm.")
        return "\n".join(lines)
    finally:
        store.close()


def patch_adapter(adapter):
    original_end = adapter.Relay.end

    def checkpoint_then_end(relay):
        relay.last_summary = close_learning()
        return original_end(relay)

    adapter.Relay.end = checkpoint_then_end
    # Official attach builds hook commands using its __file__. Point them at this
    # wrapper so /end interception also applies inside future hooks/channels.
    adapter.__file__ = str(Path(__file__).resolve())
    return adapter


def main():
    path = ROOT / ".skillsimm" / "skillsimm_desk.py"
    if not path.exists():
        print("Install the official adapter at .skillsimm/skillsimm_desk.py first.", file=sys.stderr)
        return 1
    spec = importlib.util.spec_from_file_location("skillsimm_official_desk", path)
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    patch_adapter(adapter).main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
