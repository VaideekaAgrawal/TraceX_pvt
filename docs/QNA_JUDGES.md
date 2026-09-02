# TraceX — Judge Q&A Prep

Anticipated questions from the panel (Union Bank officials, faculty, competition judges) with short, honest, confident answers. Answers are grounded in `docs/METRICS.md` / `SYSTEM_DEVELOPMENT_PLAN.md` — the *current* rebuilt system, not the old hackathon-era docs (see `docs/PRESENTATION_PREP_CHECKLIST.md` for why that distinction matters).

Keep answers to 15–30 seconds. A judge asking a follow-up is a good sign — don't over-answer the first pass.

---

## Product & problem

**Q: Why does this matter to a bank that already has an AML system?**
Existing rules engines generate alerts — they don't help resolve them. We sit downstream: a bank keeps its existing detection, TraceX turns the resulting alert into a defensible, documented decision faster. That's a three-week pilot, not a rip-and-replace.

**Q: What specific typologies does it catch?**
Layering (multi-hop chains), round-tripping (circular flows), structuring (transactions deliberately kept below the ₹10L reporting threshold), dormant-account reactivation, profile-vs-behavior mismatch, and fan-out/fan-in mule patterns — six detectors, all mapped to RBI/FATF-mandated typologies.

**Q: Isn't structuring detection just a threshold check?**
No — a hard rule alone is trivially evaded (transact at ₹9.5L instead of ₹10L forever). We combine the hard rule with an unsupervised model over a rolling 30-day window, so a pattern of near-threshold behavior gets flagged even if no single transaction looks obviously wrong.

## How it works

**Q: Walk me through what happens when a transaction comes in.**
It lands in the transaction graph. Detectors and two ML models (an unsupervised Isolation Forest and a supervised XGBoost) score the account. Flagged accounts become cases, auto-assigned to an investigator with an SLA timer. The investigator gets a one-hop money-flow view, a network risk score, and an AI explanation — then decides: escalate, request info, or close.

**Q: Why two ML models instead of one?**
They cover different failure modes. Isolation Forest needs no labeled data and works from day one on a bank with zero history of confirmed fraud. XGBoost is more precise but needs labeled cases to learn from. We ensemble both with the rule-based typology flags and graph centrality, so no single model's blind spot sinks the whole score.

**Q: What does the AI actually do, and what stops it from making things up?**
It writes the plain-language explanation, ranks recommended next actions, and answers investigator questions — but it never decides anything. Every factual claim it makes has to cite a fact our own backend computed; a separate validator checks that citation after generation and silently drops any sentence that doesn't resolve. We've watched this fire for real: in one live test the model stated a number that appeared in no cited fact, and the gate rejected it before an investigator ever saw it.

**Q: Does personal customer data ever reach the AI model?**
No — by design, not by promise. The tools that feed the AI are built so PII isn't in the data they return at all, and there's a second gate that raises an error rather than silently stripping data if anything PII-shaped tries to reach a prompt. We can say "it never left our perimeter," not just "we tried to de-identify it."

## Data, privacy & security

**Q: What data did you train and test on?**
A large public benchmark of real (but anonymized, synthetic-institution) transactions — over five million transactions, zero real customer PII — plus an engineered India-specific dataset for demonstration. No real bank customer data has ever touched this system.

**Q: How is access controlled?**
Two roles, enforced server-side, not just hidden in the UI: an Investigator can triage, escalate, and recommend outcomes; only Admin/Compliance can close a case, approve a report, or touch the watchlist. We tested this directly — an investigator calling the "close case" action straight against the API, bypassing the interface entirely, gets a real permission error, not a UI-level block.

**Q: What happens to the audit trail?**
Every investigator action and every AI interaction writes to one hash-chained audit log — so it can't be silently edited after the fact. We verified the chain integrity across nearly 700,000 log rows.

## Regulatory alignment

**Q: What regulations does this actually map to?**
PMLA 2002 (record-keeping and STR filing obligations), the RBI AML/KYC master direction, RBI's dormant-account guidance, and FATF Recommendations 10 and 20. Each detector and workflow step traces back to one of these.

**Q: Is the filed report legally valid?**
The structure follows FIU-IND's format, but we're explicit that it's a prototype pending formal schema/compliance review — we'd rather say that plainly than overclaim something a real compliance team would need to sign off on.

## Results & honesty about numbers

**Q: Your precision/recall numbers look low — why?**
Because we're reporting the honest, full-scale number, not a cherry-picked one. On the full benchmark, under half a percent of accounts are actually positive — an extremely imbalanced, genuinely hard classification problem. AUC-ROC of 0.778 shows the model has real discriminative power at that base rate; precision and recall in isolation are exactly what you'd expect from this kind of skew. That's also *why* it's one signal in an ensemble with rules and graph structure, not the sole decision-maker.

**Q: How do we know this actually works, not just that it runs?**
We didn't just pass unit tests — we drove it against a live backend and frontend with real data. Concrete example: two simultaneous requests to create a case for the same alert both returned success, and we confirmed in the database that exactly one case row was created, no duplicate. That's the kind of bug that only shows up under real concurrent use, and we went looking for it.

## Team & feasibility

**Q: How long did this take, and who built it?**
This is a from-scratch rebuild across dozens of focused engineering sessions — [fill in your actual team size/timeline here], covering backend, ML, and frontend end to end, with test coverage and CI enforced throughout, not bolted on at the end.

**Q: Is this a signed pilot with Union Bank?**
No, and we want to be precise about that — this is a competition track and an evaluation conversation, not a signed deployment. We're presenting it as a serious pilot-ready system, not an existing customer engagement.

**Q: What's the biggest thing left to do before this is production-ready?**
Real bank data validation, a formal compliance/legal review of the STR format and the FATF/RBI action mappings we've built in, and a dedicated security review pass — we've done rigorous internal testing, but a regulated financial product needs external review before it touches real accounts.
