"""The Recommendation Engine — ROADMAP Phase 9.

The intelligent "what next" agent. Its defining property, enforced in code and
not requested in a prompt: **the rules define the action space; the LLM only
ranks and explains within it.** It can never invent an action (the action
catalog is closed), and — inheriting Phase 8's grounding contract — it can never
assert a number it was not handed.

Layout:
  action_catalog.py  — the fixed, closed set of recommendable next steps, each
                       mapped to a typology and a regulatory anchor.
  rule_grounding.py  — turns a case's already-fired alerts into structured
                       evidence records, and from them the set of *eligible*
                       actions. This is what populates `ai_interactions.rule_anchors`.
  engine.py          — orchestrates: eligible actions -> agentic reasoning loop
                       (orchestration/agent_loop.py) -> validate -> deterministic
                       rank -> persist. Also the cross-question path.
"""
