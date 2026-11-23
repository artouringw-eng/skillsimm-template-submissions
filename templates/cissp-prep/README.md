# CISSP Adaptive Learning Workspace

This workspace now has a persistent Python coordinator with interchangeable OpenAI
and Anthropic models, independent question review, deterministic scoring, and an
adaptive study plan across all eight domains. The original 7/12 baseline and five
mistakes are preserved in SQLite; original files are backed up in `.state/originals/`.

- [Local setup, architecture and commands](IMPLEMENTATION.md)
- [Connect to SkillSimm Session Desk](SKILLSIMM_SETUP.md)
- [Reusable submission package](templates/cissp-adaptive-learning/README.md)
- [Configuration example](config.example.toml)

Start locally with `python3 -m coordinator chat` after setting the API credentials and
model IDs described in the setup guide. View progress without API calls using
`python3 -m coordinator status`. Run tests with `python3 -m unittest discover -s tests -v`.

The database is authoritative. Markdown study files are generated views; do not use
legacy SESSION-UPDATE write-back to modify their totals. The earlier workflow below
is retained for background, not as the active persistence protocol.

---

# CISSP Prep Workspace

This folder holds a study workflow that any AI assistant can run. The files are the
shared record. Each assistant reads them at the start of a session and updates them at
the end, so you can switch between Claude, ChatGPT, Gemini and others without losing
progress.

```
cissp-prep/
├── AGENTS.md        tutor instructions (the "brain"); works with any LLM
├── CLAUDE.md        → loads AGENTS.md in Claude Code
├── GEMINI.md        → loads AGENTS.md in Gemini CLI
├── PLAN.md          day-by-day schedule, Nov 23 → Dec 21
├── PROGRESS.md      current day, domain scores, session log
├── MISTAKES.md      every missed question and its rule
└── CHEATSHEETS/     D1.md … D8.md: notes per domain, built as you go
```

## Starting a session

### A) Assistants that can read and edit files (best)
They read the instructions and update your progress automatically.

| Tool | How to start |
|---|---|
| Claude Code | `cd ~/cissp-prep && claude`, then say **"Day 3"** |
| Codex CLI | `cd ~/cissp-prep && codex`, then say **"Day 3"** (reads `AGENTS.md`) |
| Gemini CLI | `cd ~/cissp-prep && gemini`, then say **"Day 3"** (reads `GEMINI.md`) |
| Cursor / Windsurf / VS Code agents | Open the folder and say "Follow AGENTS.md. Day 3" |

Resume your last Claude Code chat with `claude --continue`.

### B) Chat apps (ChatGPT, Gemini, Claude.ai, etc.)
1. **One-time setup:** create a Project (ChatGPT / Claude.ai) or a Gem (Gemini) called
   "CISSP Tutor". Paste the contents of `AGENTS.md` into its instructions.
2. **Each session:** upload or paste the latest `PLAN.md`, `PROGRESS.md` and `MISTAKES.md`,
   then send the kickoff prompt below.
3. **At the end:** the assistant outputs a `=== SESSION-UPDATE ===` block. Either
   - paste its rows into `PROGRESS.md`, `MISTAKES.md` and `CHEATSHEETS/` yourself, or
   - open Claude Code in this folder and say: *"Merge this SESSION-UPDATE:"* + paste.

### Kickoff prompt (copy and paste)
```
You are my CISSP tutor. Follow the protocol in AGENTS.md exactly.
Here are my current PLAN.md, PROGRESS.md and MISTAKES.md. Today is Day __ (2026-__-__).
Start with the warm-up review, then teach today's topics, then quiz me.
At the end, output the SESSION-UPDATE block.
```

## Useful commands to say
- `Day N`: run that day's full session
- `Checkpoint`: a 12-question mixed diagnostic across all domains
- `Quiz me on D4` / `Quiz me on Kerberos`: extra practice
- `Review my mistakes`: questions built from `MISTAKES.md` only
- `Practice exam batch 1 of 6`: 25 timed questions toward a full mock exam
- `Explain <topic> like I'm a manager`: a quick concept refresher

## Tips
- Keep the folder in iCloud Drive, Google Drive or a private GitHub repo to use it on other devices.
- Recommended resources: ISC2 Official Study Guide + Official Practice Tests (Sybex),
  Destination Certification MindMaps (YouTube), Pete Zerger's CISSP Exam Cram (YouTube).
