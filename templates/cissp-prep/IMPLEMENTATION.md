# Running the adaptive learning coordinator

Requires Python 3.11+; all runtime dependencies are in the standard library.
The coordinator runs on macOS/Linux (its single-writer lock uses `fcntl`).
SQLite is the authoritative memory. AI models never own or directly modify it.

## Local setup

From this directory:

```sh
cp config.example.toml config.toml
python3 -m coordinator migrate
python3 -m coordinator status
```

Migration is idempotent. It backs up originals in `.state/originals/`, imports
aggregate diagnostic counts without inventing question-level attempts, preserves
mistakes and facts, and imports the full study calendar. After migration, never
merge legacy SESSION-UPDATE totals into the generated Markdown files.

Configure `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_MODEL`, and `ANTHROPIC_MODEL`
in your local shell environment. Use model IDs supported by your API accounts.
Do not paste credentials into chat or commit them. No live API calls are made by
migrate, status or export. Each reviewed question normally uses two API calls;
lessons also receive an independent review. API charges use your provider accounts.

For a fresh workspace only, use `python3 -m coordinator init --exam-date YYYY-MM-DD`
instead of migrate. It creates a 29-day calendar ending on the supplied future exam
date, with zero scores. Existing study files are never overwritten by init.

```sh
python3 -m coordinator chat
```

Enter `/start`, then `/next`. Answer A–D when prompted. Use `/next` between questions
and to obtain the lesson; `/more` advances through long lessons. Ask concept questions after the lesson; `/continue`
starts the quiz, followed by `/next`. `/end` adapts and closes the session, including
an early exit. `/quit` leaves it open for later resumption. Status shows the current
checkpoint. The default session date is the local calendar date; standalone
`start --day N` selects a calendar lesson explicitly. `--date` is intended for testing.

The loop is a formative tutor: 3 warmups (when mistakes exist), 8 topic questions and
2 weak-domain questions by default. Set the documented ranges in config.toml to
adjust these. Calendar practice-exam days remain guided formative sessions in this
version; it does not implement a 100–150-question adaptive exam or official scoring.

## Memory, routing and tools

- `.state/learning.sqlite3`: baseline, attempts, question/review records, topic
  performance, mistakes, facts, calendar, plan revisions, sessions and replay receipts.
- `skills/`: coordinator, tutor, question author, reviewer and planner contracts.
- `curriculum.json`: all eight domains and their topics.
- `config.toml`: teacher/reviewer/planner routing; model IDs or environment names.
- `PLAN.md`, `PROGRESS.md`, `MISTAKES.md`, `CHEATSHEETS/`: generated human-readable views.

Default routing uses OpenAI Responses for teaching and planning, Anthropic Messages
for review. Reverse the provider assignments to swap their roles; use the correct
key/model environment names for each. The reviewer must use a different provider
from the author. Restart the relay/chat after changing config; pending questions,
answers and lessons remain fixed. New model calls use the new assignments. Successful
uncommitted calls are cached for recovery; use retry-content explicitly to regenerate
rejected/invalid cached content. API errors never silently substitute another model.

References: [OpenAI Responses](https://developers.openai.com/api/reference/resources/responses/methods/create),
[Anthropic Messages](https://platform.claude.com/docs/en/api/messages/create).

Questions are reviewed before delivery. Scores use stored keys, not model grading.
Answers and mistakes commit before adaptation. If planning fails, the answer response
includes adaptation_pending; use `/adapt` to retry. Domains below 70% after five
attempts receive a 20-minute block within the next three calendar days when capacity
allows. Existing coverage is never removed. Default capacity is 180 weekday / 300
weekend minutes, with base reservations imported from the calendar. Rest/light days
and the exam date are protected. An existing pending focus block prevents duplicates.
Unavailable slots are reported as deferred; the coordinator never silently overbooks.

Every accepted answer also updates its underlying-rule cheatsheet entry. Lessons add
3–8 reviewed facts. Markdown export conflicts do not erase committed learning data.
Use `export --force` only after reviewing a conflict; it backs up edited files before
regenerating them. For new facts, save a JSON list of `{domain,fact}` objects and run
`import-facts PATH`. Direct edits to aggregate scores/calendar are not automatically
imported. There is no automatic write-back from external chat SESSION-UPDATE blocks.

## SkillSimm relay contract

The official Session Desk adapter is a separate authenticated component. Follow
[SKILLSIMM_SETUP.md](SKILLSIMM_SETUP.md): attach through our wrapper so the adapter's
/end handler saves learning and submits the correct summary. Install the template,
connect/admit a local agent, trust its hooks, and give it the packaged
`skills/desk-agent.md`. It forwards input/output to:

```sh
python3 -m coordinator relay
```

Each stdin line is a JSON request; each stdout line is a JSON response:

```json
{"id":"message-001","action":"start"}
{"id":"message-002","action":"next"}
{"id":"message-003","action":"answer","question_id":"ID_FROM_RESPONSE","answer":"B"}
```

Use unique IDs for new messages and the same ID/body on retries. Successful responses
are `{id,ok:true,result}`; failures are `{id,ok:false,error}` and can be retried with
the same ID. Additional actions: status, more, continue, ask (text), adapt, end,
retry-content. Optional session_id selects an existing session. Never treat a timeout
as an answer. A pending question is returned unchanged on next/reconnect. Conflicting
replays are rejected. The relay accepts only learning actions, not arbitrary file paths
or shell commands. Only one operation may mutate the workspace at a time.

Relay outputs are learner-safe projections; the private database/model-call cache is
not. This is an API/context separation, not a security boundary against a learner who
owns the local machine. Do not attach `.state/` to learner chat or publish it.

## Verification and submission

```sh
python3 -m unittest discover -s tests -v
python3 scripts/build_submission.py
```

Copy only `templates/cissp-adaptive-learning/` to the submissions repository and run:

```sh
python3 scripts/validate_package.py templates/cissp-adaptive-learning
```

The builder copies an explicit set of reusable code/instructions into the template
and ZIP. It does not copy study records, database, credentials, or private keys.
It refuses unexpected files in the public output directory. Set creator/license and
royalty terms before submission. Building does not publish or open a pull request.

Live acceptance requires configured APIs and a SkillSimm run: verify a reviewed
question, answer feedback, lesson/discussion, plan update, a disconnect/reconnect,
and successful /end with a saved summary. Tests use synthetic provider responses;
they establish coordinator behavior, not live model quality or bridge compatibility.
