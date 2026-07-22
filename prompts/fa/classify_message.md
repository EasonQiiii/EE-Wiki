Classify one user message inside an open Failure Analysis (FA) chat session.
The session is already bound to Radar id rdar://{{radar_id}}.
Do not leave the FA session; only decide how to handle this message.

Kinds:
- evidence — the user pasted a test log, fail list, station + errors, or similar
  measurement evidence meant for Flames / triage ingestion (usually multi-line
  with ERROR/FAIL/NG, or an explicit bullet list of fails)
- question — FA dialogue: asking what is next, whether Radar/Flames has logs,
  clarifying fail items, true-fail judgment, scope, attachments, or other
  triage questions (answer using the prior check-in; do not demand paste)
- stay — empty/gibberish only, or clearly off-topic wiki asks that should get a
  short redirect (new chat for general wiki)

Prefer **question** over **stay** when unsure between them.

Output exactly one line and nothing else:
KIND: <evidence|question|stay>

## Message

{{question}}

## Kind
