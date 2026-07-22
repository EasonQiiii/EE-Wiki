# EE-Wiki RAG 评测集（Golden QA）

> **用途**：基于当前 `data/` 知识库的人工/半自动评分标准，用于验证 RAG 系统的**检索准确性、答案忠实度、范围标注、稳定性**与**拒答能力**。
>
> **版本**：v1.0  
> **机器可读源**：[`qa.yaml`](qa.yaml)（`config/schema/qa_eval.schema.json` 校验；`ee_wiki.common.eval_qa.load_qa_dataset()` 加载）  
> **语料快照**：`data/indexes/manifest.json` — **4,676** chunks，built_at `2026-07-11T08:37:00Z`（Phase A force sync 后；此前 12,554 chunks）  
> **覆盖范围**：global + `kingboo/common`（product common）+ `ipad/logan/p1`（Explorer schematic；ADR 0011）

---

## 1. 为什么需要这份文件

建立固定 Golden QA 集是 RAG 工程化的标准做法，价值在于：

| 收益 | 说明 |
|------|------|
| **回归基线** | 改 chunking、embedding、reranker、scope cascade 后，用同一套题复测，量化是否退化 |
| **分层诊断** | 区分「检索没找对」vs「检索对了但 LLM 胡说」vs「范围标注错误」 |
| **稳定性观测** | 同一事实用中/英、口语/书面问法，检验系统是否一致 |
| **拒答守门** | 知识库没有的内容必须明确 insufficient，防止幻觉 |

**建议放置**：`docs/eval/qa.md`（版本管理、与代码同演进），不要放在 `data/raw/`（那是企业文档区）。

**后续演进**：

- 每次大规模 ingest / reindex 后，更新文首「语料快照」日期与 chunk 数。
- 新增项目文档时，按同样模板追加条目（每类 2–3 题即可）。
- 机器可读数据见 [`qa.yaml`](qa.yaml)；自动跑分见 [docs/usage/eval.md](../usage/eval.md)。
- **V3 graph / cases / power / rules**（P5）：默认 CI 用 `tests/graph/`、`tests/rules/`、`tests/api/test_graph.py`、`tests/retrieval/test_graph_enrichment.py` 做无回归，不依赖 live LLM。Golden QA（`qa.yaml`）仍以文档 RAG 为主；图查询 / 规则评估的人工抽检可在构建 `data/graph/` 后用 `GET /v1/graph/*`、`GET /v1/power/tree`、`GET /v1/rules/evaluate` 或 MCP 对应工具核对。

---

## 2. 评分维度与及格线

每题按以下维度打分（0 = 失败，1 = 部分，2 = 满分）：

| 维度 | 权重 | 判定要点 |
|------|------|----------|
| **R** Retrieval | 30% | 返回的 top chunks 是否包含 `required_sources` 中至少一条；scope 正确 |
| **A** Answer accuracy | 35% | 关键事实与 `expected_answer` 一致，无编造器件/网络/数值 |
| **C** Citation & scope label | 20% | 引用来源正确；答案标明 build / common / global 层级 |
| **S** Stability（仅标注题） | 15% | 列出的 paraphrase 变体得分一致 |

**单次评测及格线**（推荐）：

- 必答题（`mandatory: true`）准确率 ≥ **90%**
- 全量加权均分 ≥ **1.6 / 2.0**
- 负向题（`category: negative`）拒答率 = **100%**（不得编造）

---

## 3. 使用方式

### 3.1 自动评测

完整 CLI 用法、参数说明与排障见 **[docs/usage/eval.md](../usage/eval.md)**。

```bash
# 检索评测（source hit@k + fact recall）
python3 scripts/eval_rag.py

# 完整 RAG 评测（检索 + LLM 答案）
python3 scripts/eval_rag.py --mode both

# 仅必答题，未达标时 exit 1
python3 scripts/eval_rag.py --mandatory-only --fail-on-threshold
```

### 3.2 手动评测

```bash
# 检索-only（验证 R）
python scripts/query.py "问题文本" --project logan --build p1

# 完整 RAG（验证 R+A+C）
python scripts/ask.py "问题文本" --project kingboo --build common
```

对照每题的 `expected_answer` 与 `required_sources` 打分，记录到评测表格（见 §6）。

### 3.3 推荐 filter 约定

| filter | 含义 |
|--------|------|
| `project=global` | 仅企业通用库 |
| `project=kingboo, build=common` | Kingboo 项目级共享 |
| `project=logan, build=p1` | Logan P1 版本专属（应触发 scope inheritance） |
| `（无 filter）` | 全库；用于平台说明类问题 |

---

## 4. 评测条目

格式说明：

- `id`：唯一编号
- `category`：`datasheet` | `schematic` | `sop` | `fa` | `scope` | `platform` | `negative` | `stability`
- `mandatory`：是否纳入及格线硬约束
- `filters`：建议传给检索的 metadata filter
- `questions`：主问题；`stability` 类含 `paraphrases`
- `expected_answer`：人工标注的黄金答案（允许措辞差异，事实必须一致）
- `required_sources`：至少命中其一（路径相对于 repo 根）
- `must_not_contain`：出现即判失败（防幻觉）
- `scope_label`：答案应明确标注的知识层级

---

### Q-001 · Datasheet · STM32F407 核心参数

| 字段 | 内容 |
|------|------|
| id | Q-001 |
| category | datasheet |
| mandatory | true |
| filters | `project=global` |
| scope_label | global |

**问题**：STM32F407ZGT6 的最高 CPU 主频、Flash 和 SRAM 容量分别是多少？

**期望答案**：
- 最高 CPU 频率：**168 MHz**
- 嵌入式 Flash：最高 **1 Mbyte**
- 嵌入式 SRAM：最高 **192 Kbytes**（含 64 Kbytes CCM）

**required_sources**：
- `data/processed/global/datasheet/STM32F407ZGT6.md`

**must_not_contain**：`200 MHz`、`2 Mbyte`（库中无此规格）

---

### Q-003 · Schematic · Logan P1 以太网 PHY

| 字段 | 内容 |
|------|------|
| id | Q-003 |
| category | schematic |
| mandatory | true |
| filters | `project=logan, build=p1` |
| scope_label | build（logan / p1） |

**问题**：Explorer STM32F4 V2.2 原理图中，以太网接口使用哪款 PHY 芯片？MCU 与 PHY 之间采用什么接口？参考时钟频率是多少？

**期望答案**：
- PHY 芯片：**LAN8720A**
- MCU–PHY 接口：**RMII**（含 TXD0/1、RXD0/1、TXEN、MDIO/MDC、ETH_RESET 等）
- 参考时钟：**25 MHz** 晶振

**required_sources**：
- `data/processed/ipad/logan/p1/sch/Apple MacBookPro A1502 820-3536-A.md`

**must_not_contain**：`千兆`（文档写的是千兆以太网功能描述，PHY 为 LAN8720A 百兆 RMII 方案；若回答「千兆 PHY 芯片型号」且无依据则扣分）

---

### Q-004 · Schematic · Logan P1 音频 Codec

| 字段 | 内容 |
|------|------|
| id | Q-004 |
| category | schematic |
| mandatory | true |
| filters | `project=logan, build=p1` |
| scope_label | build（logan / p1） |

**问题**：同一块 Explorer 开发板原理图里，I2S 音频编解码用的是什么芯片？I2S 总线有哪些信号？

**期望答案**：
- 音频 Codec：**WM8978**
- I2S 信号：**LRCK、MCLK、SCLK、SDIN、SDOUT**
- 可选补充：PHONE / SPEAKER / LINE_IN / MIC 等模拟输出接口

**required_sources**：
- `data/processed/ipad/logan/p1/sch/Apple MacBookPro A1502 820-3536-A.md`

---

### Q-005 · Schematic · 网络名检索

| 字段 | 内容 |
|------|------|
| id | Q-005 |
| category | schematic |
| mandatory | false |
| filters | `project=logan, build=p1` |
| scope_label | build（logan / p1） |

**问题**：logan p1 原理图里以太网 MDIO 信号的网络名是什么？

**期望答案**：**ETH_MDIO**（同属 RMII 以太网相关网络）

**required_sources**：
- `data/processed/ipad/logan/p1/sch/Apple MacBookPro A1502 820-3536-A.md`

---

### Q-006 · Project Common · Mahi PingPong 测试

| 字段 | 内容 |
|------|------|
| id | Q-006 |
| category | scope |
| mandatory | true |
| filters | `project=kingboo, build=common` |
| scope_label | common（kingboo） |

**问题**：Kingboo 项目中 Mahi PingPong Test 的目的是什么？Feature 0x43 返回的数据里，前 4 字节和后 4 字节分别代表什么？

**期望答案**：
- 目的：Unit **Tx 端发送固定包数（OOK）**，与 **Rx 端接收包数（ASK）** 对比，验证收发包数是否一致，确认 Tx/Rx 通讯完整
- Feature `43,A0,00,00,00,A0,00,00,00,00,00,00,00` 中：
  - `A0,00,00,00`（第一组 4 字节）：**PingPong package send number**
  - `A0,00,00,00`（第二组 4 字节）：**PingPong package receive number**
  - 后续 `00,00,00,00`：**PingPong package error number**

**required_sources**：
- `data/processed/ipad/kingboo/common/note/mahi_info.md`

---

### Q-007 · Project Common · Mahi OOK 干扰测试

| 字段 | 内容 |
|------|------|
| id | Q-007 |
| category | scope |
| mandatory | true |
| filters | `project=kingboo, build=common` |
| scope_label | common（kingboo） |

**问题**：Mahi OOK Test 中，Unit 作为 Aggressor 会发送哪三种频率的 OOK-PRBS 信号？最恶劣条件（worse case）下 VDDPA 和 SignalScale 设置是多少？

**期望答案**：
- 三种频率：**53 kHz、70 kHz、105 kHz**
- Worse case：**VDDPA = 7.2 V**，**SignalScale = 50%**
- 目的：以 Mahi OOK 作为干扰源，检测对 Victim 的影响

**required_sources**：
- `data/processed/ipad/kingboo/common/note/mahi_info.md`

---

### Q-008 · Project Common · Mahi LPCD

| 字段 | 内容 |
|------|------|
| id | Q-008 |
| category | scope |
| mandatory | false |
| filters | `project=kingboo, build=common` |
| scope_label | common（kingboo） |

**问题**：Mahi CoEx 文档中 LPCD 是什么？NFC Reader 发送 LPCD 脉冲的频率是多少？

**期望答案**：
- LPCD：**Low Power Card Detection**（低功耗卡检测）
- 脉冲频率：**10 Hz**
- 流程要点：Reader 周期发脉冲 → Pencil 靠近 → 幅值超阈值 → 触发 NFC 交互

**required_sources**：
- `data/processed/ipad/kingboo/common/note/mahi_info.md`

---

### Q-009 · Project Common · Mahi 充电倍率

| 字段 | 内容 |
|------|------|
| id | Q-009 |
| category | scope |
| mandatory | false |
| filters | `project=kingboo, build=common` |
| scope_label | common（kingboo） |

**问题**：Mahi CoEx 工站 Pencil 额定容量 50 mAh 时，三种充电电流 5 mA / 50 mA / 200 mA 分别对应多少 C 倍率？

**期望答案**：
- 5 mA → **0.1 C**
- 50 mA → **1 C**
- 200 mA → **4 C**
- 公式：充电倍率 = 充电电流 / 额定容量

**required_sources**：
- `data/processed/ipad/kingboo/common/note/mahi_info.md`

---

### Q-010 · FA · TI 8D 客退分析

| 字段 | 内容 |
|------|------|
| id | Q-010 |
| category | fa |
| mandatory | true |
| filters | `project=global` |
| scope_label | global |

**问题**：QEM-CCR-2311-00781 报告中，客户反馈的 TI 器件型号和客户料号是什么？TI 判定的根因是什么？是否存在系统性批次风险？

**期望答案**：
- TI P/N：**XTPS612994YBHR**
- Customer P/N：**353S03433**
- 客户问题描述：**output abnormally**（输出异常）
- 根因：**Electrically Induced Physical Damage (EIPD)**，最可能由 **EOS（Electrical Overstress）** 导致
- 系统性风险：**无证据**表明该器件或该生产批次存在系统性问题；历史同 lot 无类似报告

**required_sources**：
- `data/processed/global/fa/QEM-CCR-2311-00781_XTPS612994YBHR.md`

**must_not_contain**：「设计缺陷」「硅片批次不良」等报告中未支持的结论

---

### Q-011 · SOP · E4980A 探头端子

| 字段 | 内容 |
|------|------|
| id | Q-011 |
| category | sop |
| mandatory | false |
| filters | `project=global` |
| scope_label | global |

**问题**：E4980A LCR 测量仪的 HCUR、HPOT、LPOT、LCUR 四个端子分别是什么作用？

**期望答案**：
- **HCUR**：电流发生端子
- **HPOT**：HI 侧电压检测端子
- **LPOT**：LO 侧电压检测端子
- **LCUR**：电流检测端子

**required_sources**：
- `data/processed/global/sop/E4980A LCR 使用.md`

---

### Q-012 · Platform · iPad USB SSH 隧道

| 字段 | 内容 |
|------|------|
| id | Q-012 |
| category | platform |
| mandatory | false |
| filters | `project=global` |
| scope_label | global |

**问题**：iPad 工程手册中，通过 USB 建立 SSH 时，Mac 端应执行什么命令开启隧道？连接端口是多少？

**期望答案**：
- 命令：`tcprelay --portoffset 10000 ssh`
- 监听：`localhost:10022`
- 连接示例：`ssh -o NoHostAuthenticationForLocalhost=yes -p 10022 root@localhost`

**required_sources**：
- `data/processed/global/note/ipadmanal.md`

---

### Q-013 · Platform · iPad 运行模式

| 字段 | 内容 |
|------|------|
| id | Q-013 |
| category | platform |
| mandatory | false |
| filters | `project=global` |
| scope_label | global |

**问题**：iPad 工程手册里 Diags 模式和 iBoot 模式分别用于什么场景？

**期望答案**：
- **iBoot（Recovery Mode）**：系统修复、固件升级、还原设备
- **Diags（Diagnostics Mode）**：工厂测试/维修，硬件自检、传感器校准、日志抓取等

**required_sources**：
- `data/processed/global/note/ipadmanal.md`

---

### Q-015 · Scope · build 检索应命中原理图而非仅 datasheet

| 字段 | 内容 |
|------|------|
| id | Q-015 |
| category | scope |
| mandatory | true |
| filters | `project=logan, build=p1` |
| scope_label | build 优先；可补充 global datasheet |

**问题**（scope 继承验证）：logan p1 Explorer 原理图中以太网 PHY 芯片型号是什么？

**期望答案**：
- **LAN8720A**；板级结论应来自 **logan/p1 原理图**（build 级真相）
- 可补充 global LAN8720A datasheet 作器件参考，但**不得用 datasheet 替代原理图作为板级结论来源**

**required_sources**（至少命中 build 源）：
- `data/processed/ipad/logan/p1/sch/Apple MacBookPro A1502 820-3536-A.md`

**must_not_contain**：将答案仅归因于 `kingboo` 或无关项目

---

### Q-016 · Scope · 跨项目隔离

| 字段 | 内容 |
|------|------|
| id | Q-016 |
| category | scope |
| mandatory | true |
| filters | `project=logan, build=p1` |
| scope_label | 不得混淆 kingboo 与 logan |

**问题**：logan p1 Explorer 以太网 PHY 是 LAN8720A，是否与 kingboo Mahi CoEx 有关？

**期望答案**：
- **否**。logan p1 为 STM32F407 + **LAN8720A** 以太网方案；**Mahi CoEx** 属于 **kingboo** 项目，与 logan 无关。
- 检索 top-k **不得**命中 `kingboo/common/note/mahi_info.md`

**required_sources**：
- `data/processed/ipad/logan/p1/sch/Apple MacBookPro A1502 820-3536-A.md`

**forbidden_sources**：
- `data/processed/ipad/kingboo/common/note/mahi_info.md`

**must_not_contain**：「logan 使用 Mahi」「PingPong Test 在 logan p1 上」

---

### Q-017 · Negative · 库中不存在的板卡

| 字段 | 内容 |
|------|------|
| id | Q-017 |
| category | negative |
| mandatory | true |
| filters | `project=logan, build=p2` |
| scope_label | N/A（应拒答） |

**问题**：logan p2 原理图上 U502 的 FB 引脚连接到哪个网络？

**期望答案**：
- 知识库**无** `logan/p2` 文档 → 应明确 **「知识不足 / insufficient knowledge」**，不得编造网络名或位号。

**required_sources**：无（不应强行命中）

**forbidden_scope**：`logan/p2`（库中不存在，检索结果不得出现该 scope 的 chunk）

**must_not_contain**：任何具体网络名、引脚连接（均为幻觉）

---

### Q-018 · Negative · 不存在的器件参数

| 字段 | 内容 |
|------|------|
| id | Q-018 |
| category | negative |
| mandatory | true |
| filters | `project=global` |
| scope_label | N/A（应拒答） |

**问题**：STM32F407ZGT6 的 GPU 算力是多少 TFLOPS？

**期望答案**：
- STM32F407 为 MCU，**无独立 GPU**；库中 datasheet 无 TFLOPS 指标 → 应拒答或说明「文档未提供 / 不适用」，**不得编造数值**。

**required_sources**：可选命中 `STM32F407ZGT6.md`，但答案必须是「不适用或未记载」

**must_not_contain**：任何 `TFLOPS`、`GPU 核心数` 等编造数据

---

### Q-019 · Negative · 虚构项目

| 字段 | 内容 |
|------|------|
| id | Q-019 |
| category | negative |
| mandatory | true |
| filters | `project=apollo, build=evt` |
| scope_label | N/A（应拒答） |

**问题**：apollo evt 版本的 PMIC 上 VBAT 网络是否连接到 U0902？

**期望答案**：拒答 — 当前索引**无 apollo 项目**任何文档。

**forbidden_scope**：`apollo/evt`

**must_not_contain**：`U0902`、`VBAT` 的具体连接描述

---

### Q-020 · Stability · STM32 主频（多表述）

| 字段 | 内容 |
|------|------|
| id | Q-020 |
| category | stability |
| mandatory | true |
| filters | `project=global` |
| scope_label | global |

**主问题**：STM32F407 最高能跑多少 MHz？

**paraphrases**（均应得到 168 MHz）：
1. What is the maximum CPU frequency of STM32F407ZGT6?
2. F407 主频上限是多少？
3. Cortex-M4F in STM32F407 — peak clock?

**期望答案**：**168 MHz**

**required_sources**：
- `data/processed/global/datasheet/STM32F407ZGT6.md`

---

### Q-021 · Stability · Mahi LPCD（中英混合）

| 字段 | 内容 |
|------|------|
| id | Q-021 |
| category | stability |
| mandatory | false |
| filters | `project=kingboo, build=common` |
| scope_label | common（kingboo） |

**主问题**：LPCD 脉冲频率是多少？

**paraphrases**：
1. Kingboo Mahi 文档里 Low Power Card Detection 的发送频率？
2. NFC reader LPCD pulse rate in mahi_info?

**期望答案**：**10 Hz**

**required_sources**：
- `data/processed/ipad/kingboo/common/note/mahi_info.md`

---

### Q-022 · Stability · FA 根因（口语化）

| 字段 | 内容 |
|------|------|
| id | Q-022 |
| category | stability |
| mandatory | false |
| filters | `project=global` |
| scope_label | global |

**主问题**：XTPS612994YBHR 客退最终是什么原因？

**paraphrases**：
1. TI 8D report QEM-CCR-2311-00781 root cause?
2. 353S03433 这颗料 TI 判定是什么问题？

**期望答案**：**EIPD（Electrically Induced Physical Damage）**，最可能 **EOS** 导致；非批次系统性问题。

**required_sources**：
- `data/processed/global/fa/QEM-CCR-2311-00781_XTPS612994YBHR.md`

---

### Q-023 · Schematic · Explorer U14 页码（V2）

| 字段 | 内容 |
|------|------|
| id | Q-023 |
| category | schematic |
| mandatory | true |
| filters | `project=logan, build=p1` |
| scope_label | build |

**问题**：Explorer STM32F4 V2.2 原理图中，位号 U14 出现在第几页？

**期望答案**：**Page 3**（第 3 页）；U14 与以太网/音频模块同页。

**required_sources**：
- `data/processed/ipad/logan/p1/sch/Apple MacBookPro A1502 820-3536-A.md`

**验证 V2**：chunk 级 `pages` 侧车 + component index（U14 → page 3 chunk）

---

### Q-024 · Datasheet · STM32 3.3V 供电（V2）

| 字段 | 内容 |
|------|------|
| id | Q-024 |
| category | datasheet |
| mandatory | true |
| filters | `project=global, build=global` |
| scope_label | global |

**问题**：STM32F407ZGT6 datasheet 是否列出 3.3V 供电电压？

**期望答案**：是；文档/metadata 含 **3.3V** 供电规格。

**required_sources**：
- `data/processed/global/datasheet/STM32F407ZGT6.md`

**验证 V2**：datasheet 结构化字段 `supply_voltage` + metadata boost

---

### Q-025 · FA · EOS/ESD 关键词（V2）

| 字段 | 内容 |
|------|------|
| id | Q-025 |
| category | fa |
| mandatory | false |
| filters | `project=global, build=global` |
| scope_label | global |

**问题**：QEM-CCR-2311-00781 报告是否涉及 EOS 或 ESD 类失效？

**期望答案**：是；判定 **EIPD/EOS**；keywords 含 **EOS**、**ESD**。

**required_sources**：
- `data/processed/global/fa/QEM-CCR-2311-00781_XTPS612994YBHR.md`

**验证 V2**：FA ingest keyword 提取

---

### Q-026 · Schematic · U13/U14 同页（V2）

| 字段 | 内容 |
|------|------|
| id | Q-026 |
| category | schematic |
| mandatory | false |
| filters | `project=logan, build=p1` |
| scope_label | build |

**问题**：Explorer STM32F4 V2.2 原理图中，U13 与 U14 是否在同一页？

**期望答案**：是；均在 **Page 3**。

**required_sources**：
- `data/processed/ipad/logan/p1/sch/Apple MacBookPro A1502 820-3536-A.md`

**验证 V2**：component index 多 designator 命中同一 page chunk

---

### Q-027 · Datasheet · Figure 58（Figure/Page 消歧）

| 字段 | 内容 |
|------|------|
| id | Q-027 |
| category | datasheet |
| mandatory | false |
| filters | `project=global, build=global` |
| scope_label | global |

**问题**：STM32F407 中 Figure 58 描述的是什么内容？

**期望答案**：Figure 58 = **Synchronous non-multiplexed NOR/PSRAM read timings**（PDF page 134 / Table 77）。

**required_sources**：
- `data/processed/global/datasheet/STM32F407ZGT6.md`

**验证**：Figure N vs Page N 检索消歧（ADR 0005）

---

### Q-028 · Datasheet · non-multiplexed 读时序

| 字段 | 内容 |
|------|------|
| id | Q-028 |
| category | datasheet |
| mandatory | false |
| filters | `project=global, build=global` |
| scope_label | global |

**问题**：Synchronous non-multiplexed NOR/PSRAM read timings 的关键时序参数有哪些？

**期望答案**：含 **FSMC_CLK** 周期、NEx/NOE/NADV 相对 CLK 延迟、**D[15:0]** 数据建立/保持等（page 134）。

**required_sources**：
- `data/processed/global/datasheet/STM32F407ZGT6.md`

**验证**：`non-multiplexed` vs `multiplexed` 变体排序（ADR 0005）

---

## 5. 分类汇总

| 类别 | 题号 | 数量 | 测什么 |
|------|------|------|--------|
| datasheet | Q-001, Q-024, Q-027, Q-028 | 4 | 器件规格 + Figure/Table 精确定位 |
| schematic | Q-003, Q-004, Q-005, Q-023, Q-026 | 5 | 原理图检索、页级元数据、component index |
| scope / project common | Q-006–Q-009, Q-015, Q-016 | 6 | 范围继承、跨项目隔离 |
| fa | Q-010, Q-022, Q-025 | 3 | 失效分析报告 + V2 FA keywords |
| sop | Q-011 | 1 | 仪器操作 SOP |
| platform | Q-012, Q-013 | 2 | 工程手册与平台说明 |
| negative | Q-017–Q-019 | 3 | 拒答与防幻觉 |
| stability | Q-020–Q-022 | 3 | 表述鲁棒性 |
| **合计** | | **26** | |

**必答题（mandatory）**：Q-001, Q-003, Q-004, Q-006, Q-007, Q-010, Q-015, Q-016, Q-017, Q-018, Q-019, Q-020, Q-023, Q-024 — 共 **14** 题。

---

## 6. 评测记录模板

每次评测复制下表，填写日期、git commit、index manifest 日期：

| 日期 | commit | 操作者 | 题号 | R | A | C | S | 备注 |
|------|--------|--------|------|---|---|---|---|------|
| 2026-07-11 | — | — | Q-023–Q-026 | 2 | — | — | — | Phase B retrieval baseline: 4/4 pass |
| 2026-07-11 | — | — | mandatory | — | — | — | — | Phase B retrieval baseline: 14/14 pass |
| 2026-07-10 | `abc1234` | — | Q-001 | 2 | 2 | 2 | — | |
| … | | | | | | | | |

**汇总行**：

- 必答题得分：__ / 28（14 题 × 2 分）
- 负向题拒答：__ / 3
- 加权总分：__ / 2.0

---

## 7. 维护清单

- [ ] 新增 `logan/p2` 或更多 build 后，补充对应 schematic 题
- [ ] 新增 datasheet 后，从目录挑 1–2 个「高频查阅器件」加入 Q-001 同类
- [ ] scope cascade 参数变更后，重跑 Q-015、Q-016
- [ ] LLM / reranker 模型更换后，全量重跑并对比历史记录
- [x] `qa.yaml` + `eval_qa.py` 加载器 + schema 校验
- [x] `scripts/eval_rag.py` 支持 retrieval / generation / both 三种模式

---

*本文件随知识库演进更新；黄金答案以 `data/processed/` 原文为准，若原文纠错，同步修订此处。*
