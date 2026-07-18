"""The Investigation Copilot — ROADMAP Phase 10.

The "does stuff for me" assistant: cross-case and investigator-personal, in
contrast to the Recommendation Engine (Phase 9), which is bound to one case. It
stands entirely on the Phase 8/9 substrate — the same agent loop, grounding
validator, tool catalog, and PII egress gate — with two things built *here* that
Phase 8 deliberately deferred (committed decisions 9 and 10):

  1. **PII re-hydration (decision 9).** The one place the zero-egress invariant
     legitimately bends. The model still never sees a name — it reasons over
     `customer_id`, which is already a durable, non-identifying pseudonym — and
     the Copilot swaps `customer_id -> name` ONLY in the reply shown to the
     investigator (`rehydration.py`). Names are never sent to the model and never
     persisted; the persisted `ai_interactions` row keeps `customer_id`, so it
     stays auditable and PII-free at rest. "The name never crossed to the model"
     is a provable claim.

  2. **The `notes.body` free-text guardrail (decision 10).** `notes.body` is the
     project's only *live* attacker-influenceable free-text surface. The chosen
     posture is the strictest defensible one: note text is **never fed into an
     LLM prompt**. The Copilot can *write* a note (`write_case_note`) and the
     investigator reads notes through the existing case UI, but no note body ever
     reaches the model — so there is no prompt-injection surface to defend, and
     decision 10 ("free text stays out of every prompt") holds literally.

Layout:
  scoping.py      — which cases this user may touch (RBAC: an INVESTIGATOR's own
                    cases; an ADMIN_COMPLIANCE reviewer's queue).
  rehydration.py  — customer_id -> name, applied at the display boundary only.
  catalog.py      — CopilotCatalog: investigator-scoped tools; case_id is a
                    *validated argument*, never bound at construction (the whole
                    point of a cross-case agent), and per-case fact tools delegate
                    to Phase 9's case-bound ToolCatalog so nothing is re-derived.
  engine.py       — ask(): the agent loop + grounding + re-hydration + persist.
"""
