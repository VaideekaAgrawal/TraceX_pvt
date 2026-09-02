# TraceX, explained simply

For you, not for the judges — no jargon, no numbers to memorize. If you can explain it this way to a friend outside tech, you can explain it to anyone.

---

## The problem, in one sentence

Banks catch a huge pile of suspicious-looking transactions every day, but they don't have enough people to actually look into most of them — so real money laundering hides inside a mountain of noise.

## An analogy

Imagine a bank's fraud team gets 45,000 emails a day flagged as "maybe spam." They have time to actually read maybe 50 of them. Ninety percent of the 45,000 really are junk. But somewhere in that pile are the handful of emails that are a real scam draining someone's account — and there's no way to tell which ones without opening every single one.

That's the AML (anti-money-laundering) alert problem. Banks already have systems that generate the alerts. What's missing is something that helps a human actually get through them — figuring out which ones matter, connecting the dots between accounts, and writing up the case so it's ready to file with regulators.

That's what TraceX does. It doesn't replace the bank's existing alert system — it sits right after it and does the part that's currently manual, slow, and inconsistent.

## What TraceX actually does, step by step

1. **It draws a map.** Every bank account becomes a dot, every transaction between two accounts becomes a line connecting them. Once you can see the map instead of a spreadsheet, patterns jump out — money bouncing through five accounts and coming back to where it started, money deliberately split into amounts just under the ₹10 lakh limit that triggers extra scrutiny, an account that's been silent for eight months suddenly moving a crore overnight.

2. **It scores every account.** Two different machine-learning models look at each account's behavior — one that doesn't need to be told what "suspicious" looks like in advance (it just notices what's statistically weird), and one that's learned from confirmed past cases. Their opinions get combined with the map patterns into one risk score.

3. **It explains itself in plain English.** Instead of handing an investigator a table of numbers, TraceX writes a short paragraph: *"This account was dormant for eight months, then received 1.2 crore across 15 transactions in a single day — 25 times their declared income."* Every sentence in that paragraph is double-checked by a separate piece of code before it's shown — if the AI states a number that isn't backed by an actual fact the system computed, that sentence gets silently deleted. The AI can describe what happened; it is never allowed to decide anything or make a number up.

4. **It gets smarter from feedback.** Every time an investigator marks a case as "yes this was real" or "no this was a false alarm," the system quietly adjusts which kinds of accounts it prioritizes next — so the queue gets more relevant to that specific bank over time, without anyone retraining a model by hand.

5. **It writes the paperwork.** If a case turns out to be real, TraceX can generate the formal suspicious-activity report banks are legally required to file — with a tamper-evident digital fingerprint (so nobody can quietly edit it after the fact) — instead of an investigator assembling it by hand over several hours.

## What makes it different from "just another dashboard"

Most tools in this space show you numbers and expect a human to connect the dots. TraceX behaves more like a junior analyst doing the first pass of the investigation for you — it finds the pattern, explains it, suggests what to do next, and drafts the paperwork. A human investigator still makes every real decision (escalate, close, file), but they're not starting from a blank spreadsheet.

## Where it's honest about its limits

- It's been tested on a large public benchmark dataset and realistic simulated Indian bank data — never on a real bank's actual customer data.
- Its raw prediction accuracy on that benchmark is modest in isolation (it's a genuinely hard, needle-in-a-haystack problem) — it's meant to be one signal among several, not the only thing deciding a case.
- The formal report format follows the regulator's structure but hasn't been legally certified.
- This is a competition prototype and an evaluation conversation with Union Bank, not a signed, deployed contract — and it should never be described as one.

## The one-line version

**TraceX turns a bank's pile of unresolved money-laundering alerts into a small number of well-explained, ready-to-act-on cases — by mapping the money, scoring the risk, explaining it in plain language, and drafting the paperwork, so a human investigator spends their time deciding instead of digging.**
