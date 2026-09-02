# TraceX — Startup / Investor-Style Q&A Prep

For the version of the panel that thinks like an investor, not just a technical judge: market, business model, moat, scaling, money. Numbers here are traced to `docs/METRICS.md` and the commercial model in `SYSTEM_DEVELOPMENT_PLAN.md` — say the assumptions out loud as assumptions, don't present them as measured facts. Sophisticated judges respect that distinction; pretending an assumption is a measurement is the fastest way to lose credibility with this audience.

---

## Market size & growth

**Q: How big is this market, really?**
We built it bottom-up, not top-down: 309 addressable Indian institutions across three tiers (large public/private/foreign banks, small finance banks and NBFCs, larger urban cooperative banks), each with an assumed contract value, giving roughly ₹114.5 crore of serviceable annual revenue in India alone. That cross-checks against a broader India RegTech market of about $606 million in 2025 growing at 16% a year, inside a global AML software market headed from $3.2 billion to $9.1 billion by 2034.

**Q: Is that big enough to be venture-scale?**
Honestly, not on its own — ₹115 crore of Indian SAM is a good business, not a fund-returning one by itself. The thesis has to include export: FATF's framework is the same everywhere, so the product doesn't need re-architecture to sell into other FATF-aligned emerging markets. That's not hypothetical — Clari5, a Bengaluru-built financial-crime platform, expanded into 15+ countries before being acquired by Perfios in February 2025, specifically to strengthen fraud and risk capability and expand into MENA and Southeast Asia. That's our closest real precedent, both for "can an India-built product win domestic bank accounts" and "does this category have live strategic acquirers."

**Q: Who's actually growing the underlying demand?**
Digital transaction volume in India is compounding fast, which mechanically increases alert volume and AML workload regardless of what any one bank does — UPI alone processed over 21 billion transactions in a single recent month, up ~29% year-on-year. More digital rails means more laundering surface area and more alerts nobody has time to resolve.

## Business model & pricing

**Q: How do you actually make money?**
Two tiers. The lead motion is private-cloud SaaS — deployed inside the bank's own cloud account, so the bank keeps data custody (which kills the #1 objection to AML SaaS) while we still get recurring revenue. The enterprise tier is an on-premise license for banks with hard data-residency mandates — market-comparable pricing in that segment runs roughly ₹50 lakh setup plus ₹20 lakh a year in support, which is the motion incumbents already use to sell into Indian PSU banks.

**Q: What does the sales cycle actually look like?**
A three-week pilot, deliberately kept below the threshold that triggers a full procurement process: week one proves detection against the bank's own historical filings from just a CSV export, week two calibrates thresholds with their compliance team, week three puts a couple of real investigators on live cases and produces a written evaluation. No core-banking integration required to start.

## Unit economics

**Q: What's your actual cost of goods sold?**
Almost entirely LLM inference, and we measured it rather than estimated it — a real recommendation call runs about $0.07 to $0.10, at roughly 14,500 prompt tokens across 282 injected facts. Modeled against a heavy enterprise account doing ~2,000 cases a month at ~3 AI calls per case, annual inference cost lands near ₹5.3 lakh against a ₹1.2 crore contract — call it 96% gross margin. To be precise: the per-call cost is measured; the case-volume assumption is modeled, not observed from a live customer yet.

**Q: What if inference costs balloon as you scale?**
It's already the primary variable-cost lever we're watching, and there's headroom we haven't pulled yet — a full case's graph context alone can run ~56,000 tokens before summarization; we built a trimmed version specifically to cut that down, and there's more to squeeze. It's also provider-agnostic — the AI gateway talks to any chat-completions-compatible endpoint, so an on-premise model (vLLM, TGI, Ollama) is a config change, not a rewrite, for a customer who wants to eliminate the external inference cost entirely.

## Competitors & moat

**Q: What stops Oracle or NICE Actimize from just building this?**
Nothing stops them from trying, but two things make it hard to copy quickly. First, our core differentiator is enforced in code, not in a prompt — a deterministic validator that drops any AI claim that isn't backed by a computed fact. That's an architectural decision, not a feature flag; retrofitting it onto an existing prompt-governed system is a rebuild, not a patch. Second, we're not trying to displace them — we sit downstream of whatever detection engine a bank already runs, which makes the first sale a three-week pilot instead of a multi-year procurement fight against an incumbent's install base.

**Q: Who do you actually compete with day one?**
Nobody directly, by design — we're positioned as the investigation layer, complementary to whatever alert-generation system (Oracle FCCM, NICE Actimize, or similar) a bank already has. Long-term, Clari5/Perfios is the closest comparable in ambition, and the honest caveat is that the incumbent set now includes a well-capitalized domestic consolidator, not just slower foreign enterprise suites.

**Q: What's defensible about the AI layer specifically, technically?**
Three things, stacked: claims are grounded against server-computed facts and validated post-generation, not just prompted to be accurate; PII never reaches the model at all — the tools are shaped so it can't be in the response, with a fail-closed gate behind that; and the case-scoped graph boundary means the AI's context is bounded and secure by construction, not by convention. We can prove all three live, not just describe them.

## Technology & scaling

**Q: Does this actually scale past a demo?**
The architecture is already built for it, even where the current deployment isn't at that scale yet. Storage is SQLite today behind a repository interface, with Postgres as the documented production swap. The graph engine is NetworkX behind an adapter, with Neo4j as the funded-production path — the adapter boundary exists in code today; the Neo4j implementation doesn't yet, and we say that plainly rather than implying it's already there. Every graph query is scoped to one case's neighborhood, not the whole bank's ledger, so query cost doesn't grow with total transaction volume — that's a security property and a scaling property at the same time.

**Q: What breaks first at real bank scale?**
Two honest answers. Graph storage — NetworkX is in-process and RAM-bound, which is fine because case-scoping keeps subgraphs small regardless of total ledger size, but a bank-wide analytical query across the full graph would need the Neo4j swap first. And LLM cost, which is the variable-cost lever above — it scales linearly with case volume unless we keep trimming context, which we're actively doing.

## Team & fundraising

**Q: What's the raise, and what's it for?**
Modeled around a ₹10 crore raise supporting a seven-person team — funding the compliance hire below, real bank-data pilots, and the Neo4j/Postgres production swap.

**Q: Why should we trust four engineers with no AML background on a regulated compliance product?**
Fair challenge, and we're not going to pretend otherwise — we don't have an AML domain expert on the team today. That's explicitly the first senior hire out of the round: a compliance lead who can close the domain gap directly, rather than us guessing at regulatory nuance. In the meantime, the three-week pilot structure is designed so a bank's own compliance team calibrates thresholds with us in week two — we're not asking anyone to trust our regulatory judgment in a vacuum.

**Q: What's the long-term vision — where does this go in five years?**
Own the investigation layer in Indian banking first, proven through paid pilots and renewals, then export into other FATF-aligned emerging markets on the same product without re-architecture — the same trajectory Clari5 ran before being acquired. Whether the end state is an independent platform at scale or a strategic acquisition by a larger financial-crime or core-banking vendor, both outcomes are live in this category right now.
