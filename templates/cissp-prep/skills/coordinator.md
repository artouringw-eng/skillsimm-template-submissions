# Coordinator contract

Use the Python coordinator tools, never edit learning records directly. SQLite is
authoritative; the Markdown files are generated views. The learner owns every answer.

Start/resume → up to three mistake-review questions → lesson → learner discussion →
8–12 topic questions and 1–2 weak-domain questions → assessment and adaptation → end.
Present one reviewed question at a time. Never access the SQLite question bodies or
model-call cache from a learner-facing agent. Only forward public coordinator output.
Do not answer a pending quiz question on the learner's behalf. A model change must
preserve session, question and attempt IDs. Preserve the same message ID on redelivery.

The app's /end instruction means call the coordinator's end action, relay its summary,
then complete the Session Desk outcome. Do not end the desk while adaptation is pending.
An interrupted API call is retried from its checkpoint. Use retry-content only when
the coordinator reports invalid/rejected cached model output. No shell tools are
available to the API models. All state mutations are checked Python operations.
