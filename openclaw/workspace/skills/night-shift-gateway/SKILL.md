---
name: night-shift-gateway
description: Answer questions about the S500 object's ripple/blast-radius, Factory verdicts, and Track rankings through the read-only night-shift-gateway MCP tools.
---

Use this skill for questions about what a part change affects on the S500
assembly, whether a design candidate is a valid assembly, or how a candidate
scored against baseline.

1. For "what else changes if `<part>` gets thicker/changes", call
   `night-shift-gateway__work_order` with the exact part ID. Pass `thicker_mm`
   only when the user names a specific thickness delta.
2. For "is `<candidate>` valid" or "why did Factory reject it", call
   `night-shift-gateway__factory_verdict` with the candidate ID. Omit the ID
   only if the user asks about the whole family.
3. For "how did `<candidate>` score" or "what's the ranking", call
   `night-shift-gateway__track_result` with the candidate ID.

You do two things only: translate the request into one of these typed calls,
and explain the returned evidence in prose. Every number, verdict, and rank in
your answer must come from the tool's returned JSON. Do not compute, estimate,
round, or infer a number the tool did not return, and do not call these tools
to change anything -- all three are read-only. If a part or candidate ID is
unknown or misspelled, say so and ask for the exact ID rather than guessing.

State plainly when a result is baseline-relative (Track), when a verdict was
recomputed deterministically with no model on the path (Factory), and when a
Track result is read from the last stored report rather than a fresh solve.
