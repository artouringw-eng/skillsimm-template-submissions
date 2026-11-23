#!/usr/bin/env python3
"""Build only allowlisted reusable files; never package the learner workspace."""
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SLUG = "cissp-adaptive-learning"


def task(task_id, slot, name, fields):
    return {"task_id": task_id, "participant_slot": slot, "name": name, "type": "human",
            "role": "learner" if slot == 1 else "local_session", "hitl_prompt": name,
            "field_schema": {f: {"type": "textarea", "label": label, "required": True} for f, label in fields.items()},
            "required_fields": list(fields), "review_type": "none", "requires_review": False,
            "evaluation_point": False, "evaluation_weight": 0,
            "ui_options": {"require_rationale": False, "show_confidence": False}}


def build():
    files = {}
    template = {
        "template_id": "cissp_adaptive_learning", "name": "CISSP · Adaptive Learning Coordinator",
        "version": "1.0.0", "team_size": 2, "study_format": "short",
        "ai_chat_enabled": False, "group_communication_allowed": True, "timing": {"enabled": False},
        "privacy": {"encrypt_participant_contacts": True},
        "staffing": {"allowed_sizes": [2, 1], "human_seat_order": [1, 2], "vacant_seat": "pool",
                     "start": {"min_humans": 1}, "desk_teams": {"operator_seat": 1, "session_seat": 2}},
        "lens_assignments": [{"member_slot": 1, "lens": "Learner", "goal": "Practice CISSP reasoning and answer independently"},
                             {"member_slot": 2, "lens": "Local coordinator", "goal": "Teach, assess and adapt using durable local memory"}],
        "stages_dir": "stages/", "materials_dir": "materials/", "skills_dir": "skills/",
        "materials": [{"name": "Learning workflow", "path": "materials/workflow.md", "mime": "text/markdown",
                       "visibility": "all_stages", "description": "Learning loop, learner decisions, and session controls"}],
        "metadata": {"domain": "cybersecurity", "difficulty": "intermediate", "duration_minutes": 120,
                     "scoring_type": "none", "research_ready": False, "verified_by_skillsimm": False,
                     "tags": ["cissp", "adaptive-learning", "session-desk", "local-coordinator"],
                     "team_size": {"min": 1, "max": 2},
                     "learning_goals": ["Apply all eight CISSP domains", "Improve weak topics through evidence-based review",
                                        "Preserve learning progress across AI model changes"]}}
    opening = {"stage_index": 0, "stage_id": "open", "name": "Open learning session",
               "description": "Select the local learning workspace and session goal.", "dependencies": [],
               "tasks": [task("session_goal", 1, "Learning goal and workspace", {
                   "goal": "Today's learning goal", "folder": "Local coordinator workspace (no credentials)",
                   "approvals": "Session preferences and constraints"})], "estimated_duration_minutes": 5}
    working = {"stage_index": 1, "stage_id": "work", "name": "Learn, assess and adapt",
               "description": "Use team chat. Send /end before completing the outcome.", "dependencies": ["open"],
               "tasks": [task("session_log", 2, "Session log", {"summary": "Learning progress and next review"}),
                         task("session_end", 1, "Close learning session", {"outcome": "What you learned", "remaining": "What needs more practice"})],
               "estimated_duration_minutes": 115}
    for path, obj in (("template.json", template), ("stages/01_open.json", opening), ("stages/02_work.json", working)):
        files[path] = json.dumps(obj, indent=2) + "\n"
    files["materials/workflow.md"] = """# Adaptive CISSP learning

One learner works with a local coordinator through the Session Desk. The coordinator
selects today's work from persistent performance evidence and the study calendar.
The learner answers every question; the AI teaches, reviews content and plans practice.

Review earlier mistakes → lesson → questions about the lesson → quiz → feedback →
adapted plan. One question appears at a time. Submit A, B, C or D; the coordinator
then explains all choices. Ask concept questions during the discussion phase.
The next practice block is selected using performance across all eight domains.

Use /start to resume, /next to advance, /more for lesson pages, /continue to start the quiz, /status to see
progress, and /end to save a summary and finish. A dropped connection preserves the
checkpoint. Rejoin the same local workspace rather than creating new learner memory.

Scores in the coordinator's summary are learning evidence. They are not SkillSimm's
native task scores, official exam scores, or a certification readiness guarantee.
"""
    files["README.md"] = """# CISSP Adaptive Learning Coordinator

An app-format Session Desk template: one learner and one local coordinator agent.
OpenAI teaches/authors; Anthropic independently reviews content. A deterministic
coordinator grades reviewed multiple-choice questions and constrains AI plan updates.
SQLite preserves learner state; Markdown exports support inspection and portability.
All eight CISSP domains are covered. Runtime requires Python 3.11+ and API credentials.

## Install and run

1. Install this template through SkillSimm's review/setup process. The repository is
   a submission pipeline, not the simulation runtime.
2. Keep `runtime/` on the coordinator computer. Copy `config.example.toml` to
   `config.toml`; configure model IDs and API-key environment variables there as
   described in `runtime/IMPLEMENTATION.md`. Do not place keys in the template.
3. From `runtime/`, run `python3 -m coordinator init --exam-date YYYY-MM-DD`
   for a fresh learner. To preserve existing study records, copy them into this
   workspace and run `python3 -m coordinator migrate` instead.
4. Create a SkillSimm run, follow `runtime/SKILLSIMM_SETUP.md` to attach through
   the wrapper, and admit the desk. Give the agent `skills/desk-agent.md`.
5. The agent forwards chat commands to the local JSON-lines relay and forwards the
   coordinator responses back to chat. The adaptive loop remains in the work stage.
6. Send /end, copy the coordinator summary to Session log, then complete End session.

## Integration status and review

The official adapter is installed separately from the run-page URL. Attach through
`runtime/scripts/skillsimm_bridge.py`, which wraps it to checkpoint learning before
/end submits Session log. See runtime/SKILLSIMM_SETUP.md. Hooks relay final replies,
not tool output, and wait at most five minutes. Live connection testing still
requires an admitted desk, trusted hooks and configured model APIs.

No learner history, credentials or real answer keys are included. Questions and keys
are generated and reviewed privately at runtime. Native SkillSimm grading is disabled;
the coordinator reports its scores in chat and the session summary. Creator identity
and licensing/royalty terms must be supplied before public submission.

Validation: `python scripts/validate_package.py templates/cissp-adaptive-learning`
from the submissions repository. Runtime tests were run separately in the source
workspace; live SkillSimm/API testing requires configured access.
"""
    files["skills/desk-agent.md"] = """# Local Session Desk relay agent

Follow the installed SkillSimm bridge's own connection instructions. Do not invent
endpoints, tokens or commands. The run owner must admit this local session.

Run `python3 -m coordinator relay` in the chosen local coordinator workspace. Write
one JSON object per line to stdin; read one response per line from stdout. Keep this
process or restart it against the SAME workspace. Do not inspect `.state/` or read
private answer keys. Read runtime/IMPLEMENTATION.md for the protocol.

Map /start, /next, /more, /continue, /status and /adapt to matching actions.
The installed wrapper handles the desk-intercepted /end and saves the summary first. Map a
learner A–D answer to action=answer with the last delivered question_id. Map concept
questions to action=ask only during discussion. If the bridge exposes a learner message ID, use it as id. The current hook
returns text only: for an answer, use answer-QUESTION_ID as id; for other
operations create one UUID per received turn and preserve it on tool retries. Never fabricate a learner answer. Forward
the coordinator's question and choices exactly; withhold keys until the coordinator
returns post-submission feedback. Do not request the next question until the learner
has answered. After /continue or /start, call next with a distinct derived message ID
to obtain the first item. After feedback, invite the learner to continue with /next.

Present coordinator output in your FINAL response; tool output is not bridged.
Keep each final reply below 5500 characters and use /more for lesson pages.
Do not call tool-based question dialogs; ask questions in the final response.
Relay failures honestly. If the local process is not available, do not simulate its
results. The wrapper handles /end before the official adapter submits Session log.
If operating without the wrapper, ask the learner to send "finish learning" first,
call the coordinator end action, and present its saved summary in your final reply;
only then may the learner send /end. Never expose API keys.
"""
    for path in sorted((ROOT / "coordinator").glob("*.py")):
        files["runtime/coordinator/" + path.name] = path.read_text()
    for path in sorted((ROOT / "skills").glob("*.md")):
        files["runtime/skills/" + path.name] = path.read_text()
    files["runtime/scripts/skillsimm_bridge.py"] = (ROOT / "scripts/skillsimm_bridge.py").read_text()
    for name in ("curriculum.json", "config.example.toml", "IMPLEMENTATION.md", "SKILLSIMM_SETUP.md"):
        files["runtime/" + name] = (ROOT / name).read_text()
    files["runtime/.gitignore"] = ".skillsimm/\n.state/\nconfig.toml\n.env\n__pycache__/\nPLAN.md\nPROGRESS.md\nMISTAKES.md\nCHEATSHEETS/\n"
    destination = ROOT / "templates" / SLUG
    existing = {str(p.relative_to(destination)) for p in destination.rglob("*") if p.is_file()} if destination.exists() else set()
    unexpected = existing - set(files)
    if unexpected:
        raise RuntimeError(f"Unexpected files in public package; inspect before packaging: {sorted(unexpected)}")
    for relative, text in files.items():
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    archive = dist / f"{SLUG}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as out:
        for relative in sorted(files):
            out.write(destination / relative, SLUG + "/" + relative)
    print(f"Built {destination}\nArchive: {archive}\n{len(files)} allowlisted files; no learner state included.")


if __name__ == "__main__":
    build()
