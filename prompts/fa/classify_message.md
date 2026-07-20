Classify one user message inside an open Failure Analysis (FA) chat session.
The session is already bound to Radar id rdar://{{radar_id}}.
Do not leave the FA session; only decide how to handle this message.

Kinds:
- evidence — the user pasted a test log, fail list, station + errors, or similar
  measurement evidence meant for Flames / triage ingestion
- stay — questions, wiki asks, parameters, chit-chat, unclear text, or anything
  that is not test evidence (remain in FA and ask again if needed)

Output exactly one line and nothing else:
KIND: <evidence|stay>

## Message

{{question}}

## Kind
