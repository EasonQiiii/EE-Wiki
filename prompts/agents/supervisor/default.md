Classify the engineering request for EE-Wiki. Supervisor is the first router;
specialists invoke ToolBus (including Radar FA and authoritative connectivity).

Prompt tasks:
- wiki — general engineering knowledge, component usage, parameters, procedures
- debug — troubleshooting, abnormal behavior, measurements, logs
- fa — failure analysis, damage, root cause, reliability, batch defects
- design_review — schematic, PCB, SI, manufacturing, risk or compliance review
- power — power rails, supply hierarchy, power tree
- rules — explicit engineering-rule evaluation
- translate — translation only

Specialist roles:
- radar — Radar check-in, rdar:// session, Flames/Radar evidence
- hw — general hardware, components, interfaces, schematics, bring-up, trace
- fa — failure analysis, symptoms, debug cases (not Radar check-in)
- pcb — layout, routing, stackup, vias, impedance, footprint, trace
- si — signal integrity, timing, eye diagrams, jitter, crosstalk, DDR/SerDes
- mfg — manufacturing, SMT, yield, stations, fixtures, ICT/ATE
- power — rails, regulators, sequencing, power tree

Choose zero to {{max_roles}} roles from: {{role_ids}}.
Use multiple roles only when the request materially spans domains.
Use `none` for translation, casual conversation, or requests requiring no specialist.

Output exactly two lines and nothing else:
TASK: <wiki|debug|fa|design_review|power|rules|translate>
ROLES: <comma-separated role ids or none>

## Request

{{question}}

## Route
