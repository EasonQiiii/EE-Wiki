# FaAgent 实现计划（Workbuddy 施工单）

**Owner (implement):** Workbuddy  
**Owner (accept):** Cursor agent / human lab — 按文末验收清单打勾  
**Contract:** [fa-session.md](fa-session.md)（已更新：无票也可进 FaMode）

不要改本计划未列范围（勿顺手重构 Wiki Supervisor 全文）。做完每项在 PR 描述勾选。

---

## 0. 目标一句话

Chat Runtime **先判 Mode**：FaMode（结构票号 **或** FA 调查意图 **或** 已绑定会话）走 **FaAgent + ToolBus**；否则 WikiMode 保持现有 Supervisor + hybrid RAG。

金句必须过：

> 帮我FA一下为什么U8600（logan p1）的IIC接口没有输出  
> → FaMode unbound，不是 hw+纯 RAG 长文

---

## 1. Mode 门控（优先，独立可测）

### 1.1 新增 mode 判定模块

建议路径：`src/ee_wiki/agents/fa_mode.py`（或 `integrations/fa_mode.py`）

```text
def resolve_chat_mode(question, history, *, llm, config) -> Literal["fa", "wiki"]
```

规则顺序：

1. History 已是 FA 会话 → `"fa"`  
   - 匹配 `## FA check-in — rdar://` **或** `## FA session — unbound`（及等价头）
2. `parse_fa_checkin_radar_id(question)` 有票 → `"fa"`
3. LLM classify `MODE: fa|wiki`（新 prompt）  
4. 失败 / 无 LLM → `"wiki"`（保守）

### 1.2 Prompt

新增 `prompts/fa/classify_mode.md`：

- 输入：`{{question}}`（可选短 history 摘要）
- 输出一行：`MODE: fa` 或 `MODE: wiki`
- 说明：`fa` = 失效分析/排查现象/客退/帮我 FA/位号异常调查；`wiki` = 查参数/SOP/翻译/一般知识
- **禁止**要求必须有 radar 号才算 fa

### 1.3 单测

`tests/agents/test_fa_mode.py`（或 integrations）：

| 输入 | 期望 |
|------|------|
| `radar://101493937` | fa（可无 LLM） |
| history 含 unbound / check-in 头 | fa |
| `帮我FA一下为什么U8600（logan p1）的IIC接口没有输出` + mock `MODE: fa` | fa |
| `STM32F407 核心参数` + mock `MODE: wiki` | wiki |
| 无 LLM + 无票 + 无 history | wiki |

---

## 2. FaSession 状态（无票 / 有票）

### 2.1 数据结构

建议：`src/ee_wiki/agents/fa_session.py` 或 `integrations/fa_session_state.py`

```text
FaSession:
  case_id: str          # 无票时 ephemeral；有票时 == radar_id
  radar_id: str | None
  product/project/build: str | None
  symptom: str | None   # 开场调查句
  … 现有 fail_items / snapshot 可后续迭代
```

### 2.2 从 history 恢复

- 有 `rdar://` 头 → 绑定会话  
- 有 `## FA session — unbound` → unbound，解析可选 scope/symptom 行（若你写入）  
- 用户新消息含 radar id → **bind**：设置 `radar_id`，再跑现有 `start_fa_checkin`

### 2.3 助手首包头约定（便于 B 入口）

无票进入时回复须含稳定头，例如：

```markdown
## FA session — unbound
**Symptom:** …
**EE-Wiki scope:** product=… project=logan build=p1
```

有票保持：

```markdown
## FA check-in — rdar://{id}
```

---

## 3. Chat 管线分叉

文件：`src/ee_wiki/api/routes/chat.py`（及必要的 `chat_pipeline.py`）

```text
_fetch_stream_result / 等价入口:
  mode = resolve_chat_mode(...)
  if mode == "fa":
      → FaAgent.handle(...)  → AnswerStreamResult(respond, citations 按 skill)
  else:
      → 现有 Supervisor → hybrid/passthrough/clarify
```

- FaMode **禁止**静默掉进「无 FA 意图的纯 wiki RAG」  
- Wiki 检索仅当 FaAgent **显式**调了 `engineering_search` / `search_debug_case` 等，citations 来自这些工具结果

RequestTrace 增加：`mode=fa|wiki`，Fa 时 `branch=fa_agent`（或 `respond`）

---

## 4. FaAgent 最小实现（可先「受控选技」，再上满 tool_calls）

### 4.1 配置

新增例如 `config/agents/fa_agent.yaml`（或扩展 role，但语义是 **单 FaAgent**，不是再调度多 specialist 话剧）：

```yaml
id: fa_agent
tools:
  - radar_get_problem   # 或现有等价
  - fa_start_checkin / fa_session_turn  # 迁移期可保留
  - list_diagnosis 等价（format_radar_diagnosis_steps / 新 tool）
  - trace_net
  - connector_pins
  - query_schematic
  - search_component
  - search_debug_case
  - engineering_search
  # flames_* 有则加；写 Radar 保留 confirm
```

### 4.2 回合逻辑（Phase 1 可简化）

**Phase 1（本计划必须交付）：**

1. Mode=fa  
2. Ensure session（unbound 或有票）  
3. **选技**：LLM 结构化输出 `SKILLS: a,b`（prompt + allowlist 校验）**或** native tool_calls（若现有 LLM 后端已支持则优先）  
4. Exec ToolBus  
5. 拼 EvidenceBundle markdown  
6. Say：短 system「只根据证据回答；无票说明可绑 radar；不编 true-fail」  
7. 返回 `respond`（流式可先整段）

**Phase 1 无票开场默认技能建议（可写进 prompt 示例）：**  
推断 scope → `query_schematic` / `search_component` / `search_debug_case`；若像连通性再 `trace_net`；并文案提示绑票。

**本计划可不做：** 完整多轮 ReAct、Flames live 新 API、Keynote、自由写 graph。

### 4.3 有票路径

复用 `start_fa_checkin` / diagnosis 原文列表（已有 `format_radar_diagnosis_steps`）；「列步骤」类 → **强制** diagnosis 工具，禁止纯 LLM 编 true-fail。

### 4.4 废弃/降级

- Supervisor `_force_radar` 仅作过渡：Chat 已分 FaMode 后，Wiki Supervisor **不应**再抢 FA 意图句  
- `_ABOUT_DIAGNOSIS_STEPS` 正则：仅作无 LLM 兜底，主路径选技/classify  
- 不要把「帮我FA」做成唯一关键词门（与 mode classify 重复且脆弱）

---

## 5. Scope

- Unbound FA：从问句 / API body 解析 `logan` `p1`（复用现有 scope infer 或 `merge_inferred_scope`）  
- Trace 工具需要 product/project：缺则 **clarify 要 scope**，仍留在 FaMode（头仍 unbound），不要掉回 WikiMode

---

## 6. 文档（实现者同步改）

- 若行为与 [fa-session.md](fa-session.md) 有出入，改文档而非默默改合同  
- [agents.md](../usage/agents.md) smoke 表增加无票 FA 金句  
- ADR 0010：短注「会话可先 unbound，`radar_id` 可后 bind；有票后外部主键仍是 radar」——可用 ADR 正文补丁或 fa-session 互链，不必新开大 ADR，除非改写禁令

---

## 7. 测试清单（PR 必须绿）

```bash
pytest tests/agents/test_fa_mode.py \
       tests/integrations/test_fa_chat.py \
       tests/integrations/test_radar_stub.py \
       tests/api/test_chat.py \
       tests/agents/test_supervisor_routing.py -q
```

新增/更新用例：

1. Mode：无票 FA 意图 → fa  
2. Mode：wiki 参数问 → wiki  
3. Chat/FaAgent：无票 FA 金句 → 响应含 `FA session — unbound`（或约定头），**不含**「仅检索上下文没有…」类 wiki 搪塞为主答案  
4. 有票 `101493937` check-in 仍过  
5. 列 diagnosis → 含 stub 原文要点，无「模块归因确认 true-fail」幻觉  
6. Wiki 回归：电源树 / 普通问仍 hybrid|passthrough  

---

## 8. 非目标（本 PR 禁止膨胀）

- 独立 Flames conversational agent / HW conversational agent  
- Open WebUI 侧改 tool loop（loop 留在 EE-Wiki）  
- 自动下载 Radar 附件正文（除非已有接口且小改）  
- 多 agent 辩论  

---

## 9. 验收清单（Cursor / 人工）

**验收日期：** 2026-07-21 · **结论：通过（All follow-ups resolved）**

实现已落地并与 [fa-session.md](fa-session.md) A/B/C 对齐；相关 pytest 57 passed；全量 757 passed；ruff 清洁。

| 项 | 状态 | 说明 |
|----|------|------|
| `fa-session.md` 入口 A/B/C 与代码一致 | PASS | `fa_mode.resolve_chat_mode` + chat 分叉 |
| 金句 → FaMode unbound | PASS | mode 单测 + chat 金句测真跑 FaAgent.handle（仅 mock ToolBus） |
| `STM32F407 核心参数` → WikiMode | PASS | `test_wiki_mode_parameter_query_uses_rag` |
| `radar://101493937` → 有票 check-in | PASS | structural mode + bound FaAgent → `try_fa_chat_reply` |
| unbound 再发 radar → bind | PASS | `test_fa_session_state.py` 不经 mock 验 ensure/bind；chat 测验路由 |
| diagnosis 无编造 true-fail | PASS | 有票路径仍走 `format_radar_diagnosis_steps` / fa_chat；既有 stub 测 |
| ToolBus 无按 agent 复制 | PASS | `config/agents/fa_agent.yaml` allowlist + `bus.call` |
| pytest / ruff | PASS | 施工单套件 57 passed；全量 757 passed；ruff 0 violations |

**Follow-ups（已全部处理）：**

1. ~~ADR 0010 补一句~~ → 已补：`docs/adr/0010-fa-session-external-integrations.md` §1 Amendment
2. ~~补 `tests/agents/test_fa_session.py`~~ → 已创建 `tests/agents/test_fa_session_state.py`（9 tests，不经 mock）
3. ~~Phase 1.5：unbound Say LLM 摘要~~ → 已实现：`prompts/fa/unbound_summary.md` + `_try_llm_summary` in `fa_agent.py`
4. ~~chat 金句测减 mock~~ → 已改：`test_fa_mode_unbound_golden_sentence` 只 mock ToolBus，真跑 FaAgent.handle

**验收人：** Cursor（对照本清单）

### 9.1 金样测试准则（语义分类改动）

任何语义分类（意图 / FA-vs-wiki / 模糊 / PASS-FAIL / 库存类别 / 选技）的改动，验收时必须满足（详见 [ADR 0013](../../adr/0013-regex-llm-boundary-and-scope-lock.md) Testing 节）：

1. **金样用真实中英问句**，不得用玩具字符串。完整 trace 金样必须覆盖 bus 下标 `NAME<1>`，例如：
   - 中：`logan p1 上 U8600 的 I2C_SCL<1> 完整 trace 到哪些 pin？`
   - 英：`logan p1 U8600 I2C_SCL<1> full net trace to which pins?`
2. **不得只靠 mock 关键词验收**：语义改动每个分类至少含一条真实语料金样；mock 只用来隔离路由，不得作为分类正确的唯一证据。
3. **TurnScope 单点锁定**：`ensure_fa_session` 不得二次推断（见 ADR 0013 §1）。
