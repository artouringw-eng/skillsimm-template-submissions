"""CLI and JSON-lines relay. No assumed/private SkillSimm HTTP endpoints."""
import argparse
import fcntl
import json
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path

from .engine import Engine
from .bootstrap import initialize
from .models import ModelError, Router
from .store import DOMAINS, Store


@contextmanager
def locked(store):
    with (store.state / "coordinator.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("Another coordinator operation is running; retry after it completes") from exc
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def dispatch(store, router, request):
    """Stable tools surface for terminal use or a local Session Desk agent.

    Every relay message needs a stable id; reuse it verbatim on redelivery.
    The response contains only learner-safe fields (except local status metadata).
    """
    if not isinstance(request, dict) or not isinstance(request.get("id"), str) or not request["id"]:
        raise ValueError("Each request needs a nonempty string id")
    encoded = json.dumps(request, sort_keys=True)
    receipt = store.db.execute("SELECT * FROM receipts WHERE id=?", (request["id"],)).fetchone()
    if receipt:
        if receipt["request"] != encoded:
            raise ValueError("Message id was reused with different content")
        return json.loads(receipt["response"])
    action = request.get("action")
    sid = request.get("session_id")
    if action == "init":
        initialize(store.root, request["exam_date"])
        result = store.migrate()
    elif action == "migrate":
        result = store.migrate()
    elif action == "status":
        result = {"migrated": store.get("migrated", False), "exam_date": store.get("exam_date"),
                  "scores": store.scores(), "topic_performance": store.topics()}
        active = store.active()
        if active:
            result["session"] = Engine(store, router).view(active["id"])
    elif action == "export":
        result = store.export(force=request.get("force") is True)
    elif action == "import-facts":
        # Explicit additive import; aggregate Markdown scores are never reimported.
        facts = json.loads(Path(request["file"]).read_text())
        if not isinstance(facts, list):
            raise ValueError("Expected a JSON list of {domain,fact}")
        for f in facts:
            if not isinstance(f, dict) or f.get("domain") not in DOMAINS or not isinstance(f.get("fact"), str) or not f["fact"].strip():
                raise ValueError("Invalid fact")
        with store.db:
            store.db.executemany("INSERT OR IGNORE INTO facts VALUES (?,?)", [(f["domain"], f["fact"]) for f in facts])
        result = {"imported": len(facts)}
    else:
        store.require_migration()
        engine = Engine(store, router)
        if action == "start":
            result = engine.start(request.get("date"), request.get("day"))
        elif action == "next":
            result = engine.next(sid)
        elif action == "continue":
            result = engine.continue_quiz(sid)
        elif action == "more":
            result = engine.more(sid)
        elif action == "ask":
            result = engine.discuss(request["text"], sid)
        elif action == "answer":
            result = engine.answer(request["question_id"], request["answer"], request["id"])
            # Evidence is committed first. A planner outage cannot erase an answer.
            try:
                qrow = store.db.execute("SELECT session_id FROM questions WHERE id=?", (request["question_id"],)).fetchone()
                result["adaptation"] = engine.adapt(qrow[0])
            except (ModelError, ValueError) as exc:
                result["adaptation_pending"] = str(exc)
        elif action == "adapt":
            result = engine.adapt(sid)
        elif action == "end":
            result = engine.end(sid)
        elif action == "retry-content":
            result = engine.retry_content(sid)
        else:
            raise ValueError("Unknown action")
    if action not in ("export", "status") and store.get("migrated"):
        try:
            store.export()
        except (ValueError, OSError) as exc:
            result["export_pending"] = str(exc)
    response = {"id": request["id"], "ok": True, "result": result}
    with store.db:
        store.db.execute("INSERT INTO receipts VALUES (?,?,?)", (request["id"], encoded, json.dumps(response)))
    return response


def safe_dispatch(store, router, request):
    try:
        with locked(store):
            return dispatch(store, router, request)
    except (ValueError, KeyError, ModelError, OSError) as exc:
        return {"id": request.get("id") if isinstance(request, dict) else None, "ok": False, "error": str(exc)}


def show(response):
    print(json.dumps(response, indent=2, ensure_ascii=False))


def chat(store, router):
    print("CISSP coordinator. Commands: /start, /next, /more, /continue, /status, /adapt, /end, /retry, /quit.")
    print("After a question, enter A–D. After a lesson, type a question or /continue. /quit preserves the checkpoint.")
    pending = None
    current = store.active()
    if current:
        view = Engine(store, router).view(current["id"])
        pending = view.get("question", {}).get("question_id")
        show(view)
    while True:
        try:
            text = input("\nYou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nCheckpoint saved.")
            break
        if text == "/quit":
            break
        if not text:
            continue
        request = {"id": uuid.uuid4().hex}
        if text.upper() in ("A", "B", "C", "D"):
            if not pending:
                print("No pending question; use /next.")
                continue
            request.update(action="answer", question_id=pending, answer=text.upper())
        elif text.startswith("/"):
            request["action"] = {"retry": "retry-content"}.get(text[1:], text[1:])
        else:
            request.update(action="ask", text=text)
        result = safe_dispatch(store, router, request)
        show(result)
        if result["ok"]:
            active = store.active()
            row = Engine(store, router).pending(active) if active else None
            pending = row["id"] if row else None


def main():
    parser = argparse.ArgumentParser(description="Persistent CISSP coordinator")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--config", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("migrate", "status", "next", "more", "continue", "adapt", "end", "retry-content", "chat", "relay"):
        p = sub.add_parser(name)
        p.add_argument("--session-id")
    p = sub.add_parser("start")
    p.add_argument("--date")
    p.add_argument("--day", type=int)
    p = sub.add_parser("init")
    p.add_argument("--exam-date", required=True)
    p = sub.add_parser("answer")
    p.add_argument("question_id")
    p.add_argument("answer", choices=list("ABCD"))
    p.add_argument("--id", required=True, help="Stable attempt id; reuse on retries")
    p = sub.add_parser("ask")
    p.add_argument("text")
    p = sub.add_parser("export")
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("import-facts")
    p.add_argument("file")
    args = parser.parse_args()
    store = Store(args.root)
    try:
        router = Router(args.root, args.config)
        if args.command == "chat":
            chat(store, router)
            return 0
        if args.command == "relay":
            # A local agent/bridge forwards the JSON-lines protocol. No network server or arbitrary shell execution.
            for line in sys.stdin:
                try:
                    request = json.loads(line)
                    # Relay clients cannot migrate/export/import arbitrary local files.
                    if not isinstance(request, dict) or request.get("action") not in {"start", "status", "next", "more", "continue", "ask", "answer", "adapt", "end", "retry-content"}:
                        raise ValueError("Unsupported relay action")
                    response = safe_dispatch(store, router, request)
                except ValueError as exc:
                    response = {"ok": False, "error": str(exc)}
                print(json.dumps(response, ensure_ascii=False), flush=True)
            return 0
        request = {k: v for k, v in vars(args).items() if k not in ("root", "config", "command") and v is not None}
        request.update(action=args.command)
        request.setdefault("id", uuid.uuid4().hex)
        response = safe_dispatch(store, router, request)
        show(response)
        return 0 if response["ok"] else 1
    except (ValueError, OSError, ModelError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
