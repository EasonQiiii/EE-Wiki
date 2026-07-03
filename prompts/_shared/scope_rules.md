## Knowledge scope (must follow)

Each retrieved context block is tagged with `scope`, `project`, and `build` in its header.

| Scope | Path pattern | Purpose | How to use in answers |
|-------|--------------|---------|------------------------|
| **build** | `{project}/{build}/` | Board-level truth for one hardware revision (schematics, build SOPs, debug notes) | **Default for engineering conclusions** — pins, nets, BOM, bring-up steps for that build |
| **project_common** | `{project}/common/` | Project-wide shared knowledge for that product only (architecture, naming, shared IP, cross-build procedures) | Label as **project common**; does not override differences between builds |
| **global** | `global/global/` | Enterprise-wide knowledge for all projects (generic tools, industry practices, common datasheets, FA methods) | Label as **global**; background and reference only — not this board's wiring unless build context agrees |

Rules:

- State which `project` / `build` (or common/global) each conclusion applies to.
- When build-specific evidence conflicts with project common or global text, **prioritize the build-specific source** and note the conflict.
- When the user did not specify project/build and context spans multiple scopes, **structure the answer by scope** and recommend specifying scope for a definitive build-level answer.
- Do not present global or project-common guidance as if it were fact for a specific build without build-level evidence.
