# Lab 交接：快速了解 EE-Wiki

给刚进 lab、需要在短时间内摸清项目并能跑通 smoke 的同事。  
默认分支：`v3`。前端用 **Open WebUI**；EE-Wiki 是离线知识后端。

---

## 30 分钟必读（按顺序）

| # | 文档 | 你要带走什么 |
|---|------|----------------|
| 1 | [README.md](../../README.md) — Raw Data Layout + Retrieval Scope | 数据怎么摆、`product/project/build`、`common`/`global` 怎么搜 |
| 2 | [AGENTS.md](../../AGENTS.md) §1–§4、§7–§8 | 模块边界、知识优先/离线优先、V3/V4 范围 |
| 3 | [docs/usage/local-setup.md](local-setup.md) | `.env`、模型路径、如何起 API |
| 4 | [docs/usage/knowledge-authoring.md](knowledge-authoring.md) | 人怎么写文档、放哪一层才被正确检索 |
| 5 | [docs/usage/agents.md](agents.md) | 当前 chat 路由、lab checklist、手工 smoke 表 |
| 6 | [docs/usage/open-webui.md](open-webui.md) | Open WebUI 怎么连本机 EE-Wiki |

读完应能回答：知识放哪、问句怎么进系统、怎样判断是 gate / agent / RAG。

---

## 按职责加读（再 30–60 分钟）

### 数据 / ingest

| 文档 | 用途 |
|------|------|
| [ingest.md](ingest.md) | `ingest` / sync、ADR 0011 布局迁移 |
| [index.md](index.md) | processed → indexes |
| [ADR 0011](../adr/0011-product-project-build-hierarchy.md) | 三层 scope 规则（strict cutover） |

### Chat / Agent / FA

| 文档 | 用途 |
|------|------|
| [ADR 0012](../adr/0012-chat-pipeline-grounding.md) | gates → rules-first route → hybrid RAG + 引用 |
| [ADR 0008](../adr/0008-multi-agent-runtime.md) | Supervisor + ToolBus、写禁令 |
| [fa-session.md](../architecture/fa-session.md) | Radar 会话、Flames 手工粘贴 |
| [ADR 0010](../adr/0010-fa-session-external-integrations.md) | FA 外部集成契约（默认 stub） |

### 原理图 / 追网

| 文档 | 用途 |
|------|------|
| [ADR 0009](../adr/0009-multi-source-schematic-map.md) | PDF + `.net` + `.brd` 合并；权威证据 |
| [ADR 0007](../adr/0007-schematic-connectivity-extraction.md) | CAD 优先、PDF geometry 回退 |

**要点：** 没有同 stem 的 netlist/BoardView 时，pin–net **会权威拒绝**，不会拿 OCR 瞎猜。

### 架构地图（需要改代码时）

| 文档 | 用途 |
|------|------|
| [repository-structure.md](../architecture/repository-structure.md) | 目录与包边界 |
| [data-flow.md](../architecture/data-flow.md) | ingest / retrieve / generate 流水线 |
| [api-overview.md](../architecture/api-overview.md) | REST 面 |
| [mcp.md](mcp.md) | MCP / 工具 |
| [tool-contracts.md](../architecture/tool-contracts.md) | ToolBus 合约 |

不必先通读全部 ADR；需要决策时再查 [docs/adr/README.md](../adr/README.md)。

---

## 一句话架构

```text
data/raw/{product}/{project}/{build}/{type}/…
        ↓ ingest
data/processed/  (+ *.connectivity.json 等 sidecar)
        ↓ index
data/indexes/  (+ data/graph/)
        ↓
Open WebUI → POST /v1/chat/completions
        ↓
pre_rag_gates (FA / connectivity)
        ↓
Supervisor (rules-first → optional semantic → specialists)
        ↓
hybrid RAG (证据 + 检索 + 一次生成 + citations)
```

配置总入口：`config/default.yaml`（`data_layout`、`agents`、`fa`、`schematic_pdf.connectivity`、`models`）。

---

## Lab 当天最小动作

1. **环境** — 从 `.env.example` 导出 `EE_WIKI_DATA_DIR`、`EE_WIKI_MODELS_DIR`（仓库不自动 load `.env`）。
2. **布局** — raw 若仍是两层 `{project}/{build}/…`，先按 [ingest.md](ingest.md#adr-0011-layout-migration) migrate，再清 processed/indexes/graph 后重 ingest。
3. **最小知识包**（至少一个真实 scope）  
   - `sch/*.pdf` + **同 stem** `.net` 和/或 `.brd`  
   - 若干 `note/` / `sop/`（给 power/hw 检索用）  
   - 可选：`fa/`、公司 Keynote 模板见 `assets/templates/fa/`
4. **ingest + index**（或 sync）。
5. **起 API + Open WebUI**，跑 [agents.md 手工 smoke](agents.md#manual-smoke-lab)。

日志里搜 `RequestTrace`：`gate=` / `route_mode=` / `branch=` / `phase_ms=`，用来判断走了哪条路径。

---

## 常用开关（出问题先看这里）

| 开关 | 位置 | 作用 |
|------|------|------|
| `agents.enabled: false` | `config/default.yaml` | 关掉 Supervisor，退回 gate → RAG |
| `fa.*.backend: stub` / Flames `manual` | 同上 | 无内网也能练 FA check-in |
| `schematic_pdf.connectivity.enabled` | 同上 | 关则不做权威追网门 |

**不要**在 lab 把 agent 配成可写 graph/ingest；写禁令见 ADR 0008。Radar 真写回需要确认门控（ADR 0010），默认不要开 live。

---

## 当前分支上已落地（便于对齐预期）

| 能力 | 状态 |
|------|------|
| V3 图 / cases / power tree / rules / MCP | 已有 |
| V4 Supervisor + 六角色 ToolBus | 已有（`agents.enabled` 默认 true） |
| ADR 0012：gates 一次、规则优先路由、hybrid 引用 | 已 accepted |
| ADR 0011：三层 scope + migrate | 已 accepted |
| ADR 0009：netlist/BoardView 合并 sidecar | 已落地；lab 需放 companion 文件 |
| FA Radar/Flames/Keynote | 协议 + stub/manual；live 视现场内网 |

---

## 建议分工（可按人裁）

| 角色 | 优先读 | 现场任务 |
|------|--------|----------|
| 环境 / 模型 | local-setup | 模型路径、API、Open WebUI 连通 |
| 知识库 | README 布局 + knowledge-authoring + ingest | 迁布局、放文档、ingest/index |
| FA | agents + fa-session + ADR 0010 | check-in smoke、手工粘贴 Flames |
| 原理图追网 | ADR 0009 + agents smoke | 确认 `.net`/`.brd` 与权威拒绝行为 |
| 联调 / 排错 | ADR 0012 + RequestTrace | 对照 smoke 表看 branch/route |

---

## 明确先别深挖

- 全量 ADR 0001–0006（栈已定；除非改存储/模型）
- live Radarclient / 内网 Flames API 细节（无凭证时用 stub）
- eval golden 全量（[eval.md](eval.md) 有空再跑）
- 在 lab 现场做大 refactor / 新 ADR

---

## 交接联系点（填空）

| 项 | 填写 |
|----|------|
| 分支 / commit | `v3` @ ________ |
| 数据盘路径 (`EE_WIKI_DATA_DIR`) | ________ |
| 模型盘路径 (`EE_WIKI_MODELS_DIR`) | ________ |
| 已 ingest 的 product/project/build | ________ |
| Open WebUI / API 地址 | ________ |
| 现场对接人 | ________ |

*文档入口也可从 [README 文档表](../../README.md) 进入；本页是 lab 专用阅读顺序与当天清单。*
