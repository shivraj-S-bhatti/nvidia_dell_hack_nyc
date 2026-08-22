# Attempt 1 battery-tray search context

This is a local, read-only retrieval surface for one bounded hackathon
experiment: assembly `s500-battery-tray-v1`.

Keep these two record types separate:

- **Parts:** six physical proxy components in `attempt1_cad.parts`: one mounting
  board, one pad, and four M2.5x6 mounting screws.
- **Variants:** 27 fixture-backed parameter configurations in
  `attempt1_search.variants`. They are not 27 physical parts.

The Search run explores exactly three values for each parameter:

- `trayWidthMm`: 100, 105, 110 mm
- `boardThicknessMm`: 2, 2.5, 3 mm
- `padThicknessMm`: 2, 2.5, 3 mm

It ranks valid records by maximum `clearanceGainProxyMm`, then minimum
`materialVolumeProxyMm3`, then lowest ordinal. Both metrics are deterministic
proxies. Outcomes and timing are fixtures. They are not claims from CAD,
PartMode, Warp, or a physical test. `partModeRevision` and `artifactPath` are
currently null on variants because that later integration has not happened.

Use `get_ontology` when a request is ambiguous. Use `search_parts` for part
names, including misspellings or aliases. All other filters are exact and
typed. Never invent IDs, dimensions, or relationships, and never claim that a
tool result changed the database: every exposed operation is read-only.

For `trayWidthMm`, increasing width moves the left screw columns toward
negative X and the right screw columns toward positive X. Both sides therefore
move **away from the centerline**, not inward.
