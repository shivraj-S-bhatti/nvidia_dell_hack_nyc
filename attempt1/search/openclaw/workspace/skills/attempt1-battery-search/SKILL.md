---
name: attempt1-battery-search
description: Retrieve local Attempt 1 S500 battery-tray parts, dependencies, fixture variants, winners, and lineage through the read-only attempt1-search MCP tools.
---

Use this skill for questions about the Attempt 1 S500 battery tray's parts,
dimensions, dependency edges, possible configurations, fixture failures,
winning configuration, or variant ancestry.

1. For ambiguous domain words or unknown fields, call
   `attempt1-search__get_ontology` first.
2. For a physical component, call `attempt1-search__search_parts`. Put an
   imprecise name or typo in `query_text`; fuzzy matching exists only there.
3. For a possible parameter configuration, call
   `attempt1-search__search_variants` with exact typed fields. These are the 27
   variants, not 27 parts.
4. Resolve a fuzzy part name to its exact ID before calling
   `attempt1-search__get_dependencies`.
5. Use `attempt1-search__list_design_runs`, `attempt1-search__get_winner`, and
   `attempt1-search__get_variant_lineage` for run and ancestry questions.

Do not use shell commands or raw MongoDB queries as a substitute for these
tools. Do not attempt writes. State that variant metrics, outcomes, and timing
are fixture/proxy evidence. State that CAD/PartMode artifact fields remain null
when relevant. Never invent a missing part, value, ID, or relationship.

When explaining a positive `trayWidthMm` change, say that the left screws move
toward negative X and the right screws move toward positive X: both move away
from the centerline.
