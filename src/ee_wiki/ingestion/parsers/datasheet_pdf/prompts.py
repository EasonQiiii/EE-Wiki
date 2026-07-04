"""VLM prompt templates for datasheet page extraction."""

from __future__ import annotations

SYSTEM_PROMPT = (
    "You are an electronic component datasheet expert. "
    "You extract information from datasheet pages with perfect fidelity. "
    "Never invent or approximate values — reproduce exactly what is printed."
)

TABLE_PROMPT = """\
This is a page from an electronic component datasheet containing a table.

Extract the table into a well-formatted Markdown table. Follow these rules strictly:

1. Preserve the exact column headers as printed \
(e.g. Parameter, Device, Conditions, Min, Typ, Max, Units).
2. Keep ALL numeric values exactly as printed — never round, interpolate, or convert units.
3. For parameters spanning multiple rows (different devices or conditions), \
repeat the parameter name in each row.
4. Mark genuinely empty cells with `-`.
5. If the table has a title or section heading, output it as `### {title}` above the table.
6. Include any notes below the table verbatim (e.g. "Note 1: ...", "Note 2: ...").
7. If there is non-table text on the page (above or below the table), \
include it as normal paragraphs.

Output ONLY the Markdown content. Do not wrap in code fences or add commentary."""

GRAPH_PROMPT = """\
This is a page from an electronic component datasheet containing one or more \
performance graphs/charts.

For each graph on this page, provide a structured description:

1. State the graph title exactly as printed.
2. State the X-axis label and units, and the Y-axis label and units.
3. Describe the overall trend of each curve (linear, flat, exponential, inflected, etc.).
4. Report key data points: minimum value, maximum value, value at typical operating point.
5. Note test conditions shown (temperature, load current, input voltage, etc.).
6. If multiple curves exist, describe each with its legend label.

Format each graph as:

### {Graph Title}

**X-axis:** {label} ({units})
**Y-axis:** {label} ({units})
**Conditions:** {conditions}

{Trend description with key values}

Output ONLY the Markdown content. Do not wrap in code fences."""

MIXED_PROMPT = """\
This is a page from an electronic component datasheet containing a mix of text, \
tables, and/or figures.

Extract ALL content faithfully:

1. For tables: output as Markdown tables with exact headers and numeric values.
2. For graphs/charts: provide a structured description (title, axes, trend, key values).
3. For text paragraphs: reproduce the text as-is.
4. Preserve the reading order of the page (top to bottom, left to right).
5. Use `###` headings for section titles and table titles.
6. Never invent values — reproduce exactly what is printed.

Output ONLY the Markdown content. Do not wrap in code fences."""


def build_table_prompt(ocr_text: str | None = None) -> str:
    """Build the user prompt for a table page, optionally including OCR context."""
    if ocr_text:
        return (
            f"{TABLE_PROMPT}\n\n"
            f"--- OCR text from this page (for reference, may have errors) ---\n"
            f"{ocr_text[:3000]}"
        )
    return TABLE_PROMPT


def build_graph_prompt(ocr_text: str | None = None) -> str:
    """Build the user prompt for a graph page, optionally including OCR context."""
    if ocr_text:
        return (
            f"{GRAPH_PROMPT}\n\n"
            f"--- OCR text from this page (axis labels, legend, etc.) ---\n"
            f"{ocr_text[:2000]}"
        )
    return GRAPH_PROMPT


def build_mixed_prompt(ocr_text: str | None = None) -> str:
    """Build the user prompt for a mixed page, optionally including OCR context."""
    if ocr_text:
        return (
            f"{MIXED_PROMPT}\n\n"
            f"--- OCR text from this page (for reference) ---\n"
            f"{ocr_text[:3000]}"
        )
    return MIXED_PROMPT
