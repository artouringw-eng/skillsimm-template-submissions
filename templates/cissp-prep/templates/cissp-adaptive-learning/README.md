# CISSP Adaptive Learning Coordinator

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
