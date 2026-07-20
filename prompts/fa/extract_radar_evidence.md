Extract structured fail / symptom evidence from a Radar problem corpus.
The corpus may include Title, Description, Diagnosis (FA notes and pasted
log snippets), and Attachment file names.

Ignore Radar system noise (assignee changes, "New information added",
attachment-count history). Prefer concrete failure symptoms, ERROR/FAIL
lines, and clear NG observations. Do not invent part numbers or fails
that are not supported by the text.

If the ticket only describes monitoring / pass after a fix with no
remaining failure, you may return none.

Output exactly in this form (nothing else):
FAIL_ITEMS:
- <short fail or symptom 1>
- <short fail or symptom 2>

Or when nothing usable:
FAIL_ITEMS: none

## Radar corpus

{{corpus}}

## Fail items
