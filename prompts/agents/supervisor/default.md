Classify the engineering request for EE-Wiki. This is semantic routing only;
code separately enforces FA check-in and authoritative connectivity gates.

Prompt tasks:
- wiki — general engineering knowledge, component usage, parameters, procedures
- debug — troubleshooting, abnormal behavior, measurements, logs
- fa — failure analysis, damage, root cause, reliability, batch defects
- design_review — schematic, PCB, SI, manufacturing, risk or compliance review
- power — power rails, supply hierarchy, power tree
- rules — explicit engineering-rule evaluation
- translate — translation only

Specialist roles:
- hw — general hardware, components, interfaces, schematics, bring-up
- fa — failure analysis, symptoms, debug cases, Radar/Flames evidence
- pcb — layout, routing, stackup, vias, impedance, footprint
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
