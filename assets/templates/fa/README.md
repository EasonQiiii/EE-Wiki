# FA Keynote templates

Place an optional company **one-page FA summary** Keynote here:

```text
assets/templates/fa/one_page.key
```

If present, EE-Wiki copies it and replaces placeholders via AppleScript.
If absent (typical lab default), EE-Wiki **creates a one-slide Keynote from
scratch** with Radar-only content:

1. **Summary** — radar id, title, state, product / project / build, fail items
2. **FA Steps** — brief Radar diagnosis lines (human notes; no history rows)
3. **Conclusion** — ticket state + latest diagnosis (no invented root cause)

Chat triggers: **keynote / one page / 一页纸 / 导出报告** on a bound (`rdar://`)
session → `generate_fa_summary` → `data/exports/fa/{radar_id}/FA_summary.key`
plus `FA_summary.md` mirror. Reply includes the download link and a Markdown
preview of the same sections.

## Optional company-template placeholders

| Token | Source |
|-------|--------|
| `{{RADAR_ID}}` | Radar id digits |
| `{{TITLE}}` | `RadarProblem.title` |
| `{{PRODUCT}}` / `{{PROJECT}}` / `{{BUILD}}` | EE-Wiki scope |
| `{{STATE}}` | `state / substate` |
| `{{STEPS}}` | Numbered diagnosis |
| `{{CONCLUSION}}` | Latest status string |
| `{{BODY}}` | Full plain-text one-pager body |

Do **not** put customer FA data in this folder — only blank or branded
templates. Without Keynote.app (CI / Linux), EE-Wiki still writes a text
one-pager at `FA_summary.key` so the download URL works for integration tests.
