# Connect this coordinator to SkillSimm Session Desk

Use a dedicated desk name such as `cissp`. Do not reuse an existing desk belonging
to another project. Start a Codex or Claude session with this workspace as its
project folder. For Codex, the hook checks the thread's cwd as well as its ID;
changing directory inside a tool in a thread rooted elsewhere is not sufficient.

The official adapter was inspected from:
`https://app.skillsimm.com/api/agent/desk.py`.
Its attach command supports --kind and --session-id. It relays only final responses
and user prompts, waits up to five minutes, and intercepts /end itself. Its end
operation searches for a task named exactly **Session log**. This template uses that
name. `scripts/skillsimm_bridge.py` wraps the official adapter to save the coordinator
session and set the final score summary before the adapter submits the log.

## Install

In the coordinator workspace (or `runtime/` inside the reusable package):

```sh
mkdir -p .skillsimm
printf '*\n' > .skillsimm/.gitignore
curl -fsSL https://app.skillsimm.com/api/agent/desk.py -o .skillsimm/skillsimm_desk.py
uv run scripts/skillsimm_bridge.py attach --help
```

The wrapper uses the official adapter's pinned `httpx` and `mcp` dependencies.
It does not modify the downloaded adapter. Recheck compatibility after updating it.
The local source workspace already includes this download; reinstall only to update.

Configure model API keys and model IDs as described in IMPLEMENTATION.md. API keys
remain in the local process environment. Hooks inherit that environment, so launch
the agent with the model settings available to its command tools and hooks.

## Attach and join

Run these from the intended Codex thread in this project:

```sh
uv run scripts/skillsimm_bridge.py --desk cissp attach --kind codex --session-id "$CODEX_THREAD_ID" --approvals
uv run scripts/skillsimm_bridge.py --desk cissp join RUN_JOIN_CODE --kind codex
```

In a separate terminal, supply the actual thread ID instead of assuming
CODEX_THREAD_ID is available. Start the SkillSimm run first. Admit the waiting desk
on the run page. Initial hook trust must be completed locally in Codex /hooks or
Settings > Hooks; reopen the project thread if hooks do not appear.

For Claude, use:

```sh
uv run scripts/skillsimm_bridge.py --desk cissp attach --approvals
uv run scripts/skillsimm_bridge.py --desk cissp join RUN_JOIN_CODE
```

Review the hooks in Claude /hooks. Omit --approvals if permission prompts should
stay local. Keep the wrapper path for all commands, especially attach. If you have
already attached the unwrapped official script for this desk, detach that desk and
attach using the wrapper; its saved seat token is preserved.

```sh
uv run scripts/skillsimm_bridge.py --desk cissp check
```

Seat tokens stay in `~/.skillsimm/desks/cissp/`. A join interrupted before admission
can resume with `join --resume`. Never copy or publish these tokens.

## Agent kickoff

Give the connected local agent this instruction:

> Follow templates/cissp-adaptive-learning/skills/desk-agent.md. Use this folder's
> Python coordinator for all learning operations. Present its questions and feedback
> in final responses, never tool dialogs. Do not read private answer keys. Start or
> resume the existing learning checkpoint.

When operating from the package's runtime directory, use the sibling
`../skills/desk-agent.md` instead. The agent can use the JSON-lines relay or individual
coordinator CLI commands. For answers always use a stable ID derived from question_id.
The official hook exposes message text, not a stable inbox ID, so the coordinator's
question-level replay protection is essential.

Use /more to page a long lesson; final responses must remain below 5500 characters
because the desk truncates at 6000. /pause leaves the learning checkpoint open.
/end is handled by the wrapper: it closes/adapts learning, supplies a score summary,
then lets the official adapter submit Session log and detach. If adaptation fails,
the wrapper refuses to end the desk: retry adaptation locally, then /end again.
After a five-minute hook timeout, prompt the same local agent again to resume.

## Live acceptance

1. Confirm check identifies the intended admitted seat.
2. Send /start and /next; receive a reviewed question in the team desktop.
3. Submit an answer; verify feedback and an increment of exactly one attempt.
4. Reopen the same local agent/workspace; verify the pending question is unchanged.
5. Complete a lesson, /more if needed, discussion and quiz; inspect the revised plan.
6. Send /end; verify the coordinator is closed and Session log contains its summary.

No desk has been attached or joined by this implementation. These steps need a run
join code, local hook trust, run-owner admission, and configured OpenAI/Anthropic APIs.
