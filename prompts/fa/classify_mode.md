Classify whether the user's message should enter Failure-Analysis (FA) mode or stay in general Wiki (knowledge) mode for EE-Wiki.

Return MODE: fa when the user wants to:
- 失效分析 / 排查某个现象为什么没输出、报错、异常（debug a failure symptom）
- 客退 / RMA / 根因调查 / 8D / 帮我 FA / 帮我分析这颗料为什么 fail
- 追查失败证据、true-fail、诊断步骤
- 调查某个位号 / net / 接口 / 模块的**异常行为**（必须有失败 / 异常 / 没输出等调查意图）

Return MODE: wiki when the user wants to:
- 查器件核心参数 / datasheet / pinout / 翻译
- **原理图追网 / 完整 trace / 连通性 / netlist 走线**（无失效语义时）
- 询问某个 net / trace 的**参数属性**（阻抗 / 等长布线 / 信号完整性 / stack-up / 叠层）且无失效语义时 → wiki（这是查参数，不是查失效）
- 一般工程知识、概念解释、SOP 写法
- 无调查意图的普通查询

IMPORTANT:
- A message does NOT need a Radar (rdar://) id to be FA mode. FA mode is about the *intent* to investigate a failure, not about whether a ticket id is present.
- Naming a net or asking for its schematic **trace** alone is **wiki**, not FA. Example: `logan p1 原理图 DP_xxx 的完整trace` → MODE: wiki.
- Only route net / 位号 questions to FA when there is clear failure language (fail / 异常 / 没输出 / 客退 / 根因 / 帮我FA …).
- A follow-up about a previously-traced net's *properties* (阻抗 / 等长布线 / 信号完整性) with no failure language is **wiki** — it asks for a spec/parameter, not for a failure investigation.

Output exactly one line and nothing else:
MODE: fa
or
MODE: wiki

## Recent history (may be empty)
{{history}}

## User message
{{question}}

## Mode
