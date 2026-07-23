Classify one user message inside an open Failure Analysis (FA) chat session.
The message is about the Radar ticket's diagnosis steps / timeline / progress.
Decide what the user wants done with those steps.

Kinds:
- list_steps — user wants the original diagnosis steps verbatim, numbered
  (e.g. "列出所有 FA 步骤", "列一下步骤", "原文", "列出全部", "完整步骤")
- summarize_steps — user wants a short recap / summary of what was done
  (e.g. "简要总结", "总结一下", "summary", "概述", "做了哪些", "归纳", "回顾")
- latest_action — user wants only the most recent / latest action or update
  (e.g. "最新一步", "最近做了什么", "刚做的", "上一步", "最新进展")
- other — mentions steps but the intent is unclear or something else

Priority: when both summarize and list cues appear, prefer summarize_steps.
When unsure between list_steps and summarize_steps, prefer summarize_steps.

Output exactly one line and nothing else:
KIND: <list_steps|summarize_steps|latest_action|other>

## Message

{{question}}

## Kind
