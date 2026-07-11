"""
AI Orchestration layer -- shared AI substrate, Recommendation Engine,
Copilot (`docs/ROADMAP.md` Phase 8-10).

`account_explanation.py` (ROADMAP Phase 5) is a deliberate exception to
"built last": a small, self-contained port of the archive's existing
fact-injected per-account explanation panel, added now because it's a
genuinely strong, already-built L1 triage feature (`SYSTEM_DEVELOPMENT_PLAN
.md` §4.1) that doesn't need to wait on the Phase 8 LLM gateway/PII-
redaction middleware/tool catalog this package will eventually hold. See
that module's own docstring for the full guardrail reasoning -- it is
explicitly NOT the Phase 8 substrate and should not be extended toward one.
"""
from __future__ import annotations
