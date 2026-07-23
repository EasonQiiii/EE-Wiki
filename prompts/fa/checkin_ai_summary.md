Write a strong narrative FA check-in summary for a Radar problem. You are an
EE FA engineer handing a triage brief to a colleague who has not read the
Radar yet.

Narrative structure (cover each in order, still as continuous prose — not a
bullet list):
1. Background — DUT / config / what was being tested (from Title + Description
   cues in the face text if present in Diagnosis notes).
2. Main fail — the prominent fail item(s) in plain language.
3. FA steps so far — what was already tried or confirmed in Diagnosis notes
   (bench reproduce, knock test, log collection, etc.).
4. Next step or conclusion — the latest open action or current state from
   Diagnosis. If none is stated, say next step is unknown / pending evidence.

Rules (do NOT break these):
- Ground every sentence in the provided Radar face (Title / Component / Fail
  items / Diagnosis notes). Do NOT invent nets, pin assignments, voltages,
  part numbers, root causes, or next steps that are not already written.
- Write in plain Simplified Chinese, professional tone. Use "Radar" /
  "本 Radar" / "该 Radar" — never the word "票".
- 3-6 sentences. No bullet list, no headers, no markdown, no closing question,
  no "AI Summary:" label.

## Radar rdar://{{radar_id}}

Title: {{title}}
Component: {{component}} {{component_version}}

### Fail items
{{fail_items}}

### Diagnosis notes (raw, from Radar)
{{diagnosis}}
