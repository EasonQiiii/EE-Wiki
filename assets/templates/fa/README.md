# FA Keynote templates

Place the company **one-page FA summary** Keynote here:

```text
assets/templates/fa/one_page.key
```

EE-Wiki copies this file to `data/exports/fa/{radar_id}/FA_summary.key` when generating a report ([ADR 0010](../../../docs/adr/0010-fa-session-external-integrations.md)). Field merge into Keynote text boxes is a follow-up (macOS / AppleScript); until then a sidecar `FA_summary.fields.txt` is written next to the copy.

Do not put customer FA data in this folder — only blank or branded templates.
