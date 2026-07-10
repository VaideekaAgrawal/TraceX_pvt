# Golden Edge-Case Scenarios

Companion doc to `backend/demo_data/golden_scenarios.py` (ROADMAP Phase 1B).
Hand-written, **not** auto-generated — ids below are pulled directly from
`backend/demo_data/identifiers.py`'s deterministic id builders (same seed
every run: `demo_data.config.DEMO_SEED`), so this doc does not drift from
the code that actually produces them. Re-generate the dataset with
`python scripts/generate_demo_data.py` (from `backend/`) and every id below
will be identical.

Each scenario is a small, dedicated network (own customers/accounts/
transactions, not drawn from the general KYC pool — see that module's own
docstring for why) engineered to genuinely trip its detector under
`backend/detection/config.py::DEFAULT_DETECTION_CONFIG`'s real thresholds,
not just described in prose. `backend/tests/demo_data/test_golden_scenarios.py`
runs the real detectors against this data in CI and asserts every scenario
below actually fires.

**Known, pre-existing coverage gap** (not introduced or fixed by this
phase — see `backend/detection/rules/seed.py`'s own module docstring and
`docs/SESSION_LOG.md`): `db/enums.py::DetectionType` has only 5 members
(`layering`, `round_trip`, `structuring`, `dormancy`, `profile_mismatch`).
There is no persistable `fan_out`/`fan_in` detection type and no dedicated
sanction-match detector. Two scenarios' *narrative* typology (what an
investigator would call the pattern) therefore differs from the real
`DetectionType` their fabricated transactions actually trip — called out
explicitly below, not hidden.

---

## 1. Clean Multi-Hop Layering Chain

- **Typology:** layering
- **Expected `DetectionType`:** `layering`
- **Accounts:** `DEMO-ACC-LAYERING-01` → `02` → `03` → `04` → `05`
- **Shape:** 4-hop chain, amounts decreasing ₹10,00,000 → ₹7,00,000 →
  ₹4,50,000 → ₹2,50,000, all inside 45 minutes.
- **Feature triggered:** `LayeringDetector`'s tight-window pass — hops (4)
  ≥ `layering_min_hops` (3), decay_ratio (1.0) ≥ 0.5, time span (45 min) ≤
  `layering_time_window_minutes` (120).
- **Expected system output:** a `layering` alert on `DEMO-ACC-LAYERING-01`
  (or whichever account the ensemble scores highest across the chain)
  covering all 5 accounts.
- **Edge case proved:** the Investigation Path Recommendation and Copilot
  can walk a genuinely fast, decaying multi-hop chain end to end from a
  single alert.

## 2. Structuring Across Branches

- **Typology:** structuring
- **Expected `DetectionType`:** `structuring`
- **Accounts:** source `DEMO-ACC-STRUCTURING-01`; destinations
  `DEMO-ACC-STRUCTURING-02..05` (branch cities Mumbai/Delhi/Chennai/Kolkata).
- **Shape:** 4 transactions of ₹9.5L / ₹9.6L / ₹9.4L / ₹9.7L over 21 days,
  all just under the ₹10L CTR threshold, to 4 different destinations at 4
  different branches.
- **Feature triggered:** `StructuringDetector._detect_classic` — ≥3
  same-source transactions in `[₹9L, ₹10L)` within a 30-day window (4
  present, span 21 days).
- **Expected system output:** a `structuring` alert on
  `DEMO-ACC-STRUCTURING-01`.
- **Edge case proved:** structuring detection doesn't require repeated
  transactions to the *same* destination — dispersing near-threshold amounts
  across multiple counterparties/branches still fires.

## 3. Circular Round-Trip Flow

- **Typology:** round_trip
- **Expected `DetectionType`:** `round_trip`
- **Accounts:** `DEMO-ACC-ROUNDTRIP-01` → `02` → `03` → back to `01`.
- **Shape:** ₹5L → ₹4.9L → ₹4.8L around the loop within 40 minutes; 96% of
  the originating debit returns to the start node.
- **Feature triggered:** `RoundTripDetector` — cycle length (3) ≤ 12,
  return_ratio (0.96) ≥ `round_trip_amount_return_ratio` (0.85).
- **Expected system output:** a `round_trip` alert covering all 3 accounts.
- **Edge case proved:** a tight, fast-closing 3-node loop with near-total
  fund preservation is caught even without any single large transaction.

## 4. Dormant Account Reactivation

- **Typology:** dormancy
- **Expected `DetectionType`:** `dormancy`
- **Accounts:** dormant account `DEMO-ACC-DORMANCY-01`; pre-dormancy
  counterparties `DEMO-ACC-DORMANCY-02..03`; post-dormancy counterparties
  `DEMO-ACC-DORMANCY-04..08`.
- **Shape:** two ₹10K deposits, then a 200-day gap, then five ₹6L outgoing
  transactions in as many days.
- **Feature triggered:** `DormancyDetector` — max gap (200 days) ≥
  `dormancy_threshold_days` (180), burst count (5) ≥
  `dormancy_burst_min_txns` (5), burst/pre average ratio (~60x) ≥
  `dormancy_multiplier` (10.0).
- **Expected system output:** a `dormancy` alert on
  `DEMO-ACC-DORMANCY-01`.
- **Edge case proved:** a long-idle account suddenly moving large volume is
  caught purely from its own transaction history, no external profile data
  needed.

## 5. Income vs. Volume Profile Mismatch

- **Typology:** profile_mismatch
- **Expected `DetectionType`:** `profile_mismatch`
- **Customer:** `DEMO-CUST-PROFILE-01` (declared annual income ₹2,00,000).
- **Account:** `DEMO-ACC-PROFILE-01`; counterparties
  `DEMO-ACC-PROFILE-02..06`.
- **Watchlist:** `DEMO-WL-PROFILE-01` (income/volume-mismatch escalation
  candidate).
- **Shape:** 5 transactions of ₹5L each (in and out) in a week — ₹25L total
  volume against a ₹2L declared income (12.5x).
- **Feature triggered:** `ProfileMismatchDetector._detect_income_mismatch`
  — volume/declared-income ratio (12.5) > 10.
- **Expected system output:** a `profile_mismatch` alert on
  `DEMO-ACC-PROFILE-01`.
- **Edge case proved:** Customer Snapshot's declared-income field genuinely
  drives detection, not just display.

## 6. Sanctioned-Entity Peer-Volume Outlier ("sanction match")

- **Typology (narrative):** sanction_match — **actual `DetectionType`:**
  `profile_mismatch` (peer-deviation sub-type; see the coverage-gap note
  above — no dedicated sanction detector exists yet).
- **Customers:** peers `DEMO-CUST-SANCTION-01..11`; sanctioned outlier
  `DEMO-CUST-SANCTION-12`.
- **Accounts:** peers `DEMO-ACC-SANCTION-01..11`; outlier
  `DEMO-ACC-SANCTION-12`; shared destination hub `DEMO-ACC-SANCTION-13`.
- **Watchlist:** `DEMO-WL-SANCTION-01` (mock OFAC/UN sanctions-list match on
  the outlier customer).
- **Shape:** 12 accounts share the same declared occupation/income bracket.
  11 peers each send ₹1L to the shared hub; the 12th (sanctioned) sends
  ₹100Cr to the same hub — a peer z-score of ~3.2 (threshold 3.0).
- **Feature triggered:** `ProfileMismatchDetector._detect_peer_deviation` —
  |z-score| (~3.2) > `profile_mismatch_z_threshold` (3.0), peer group size
  (12) ≥ `peer_min_group_size` (5).
- **Expected system output:** a `profile_mismatch` alert on
  `DEMO-ACC-SANCTION-12`, **plus** an active `watchlist` row a future
  auto-escalation phase (Phase 11) can key off of for automatic priority
  bump.
- **Edge case proved:** a sanctions-list match combined with anomalous
  peer-relative volume is demo-able end to end today, even though the
  system doesn't yet have a first-class sanction-match detector — the
  Watchlist row is the concrete anchor that phase needs.

## 7. Funnel Mule (Fan-In Then Layer-Out)

- **Typology (narrative):** funnel_mule — **actual `DetectionType`:**
  `layering` (see the coverage-gap note above — fan-in isn't a persistable
  `DetectionType`, but the mule's downstream forwarding is a real layering
  chain).
- **Accounts:** senders `DEMO-ACC-FUNNEL-01..03`; mule `DEMO-ACC-FUNNEL-04`;
  downstream hops `DEMO-ACC-FUNNEL-05..06`.
- **Shape:** 3 senders converge on the mule within minutes (₹10L, ₹1.5L,
  ₹1L), which forwards onward through a 2-hop decreasing chain (₹7L →
  ₹4L).
- **Feature triggered:** `LayeringDetector` — the highest-contributing
  sender's own outbound leg starts a valid tight-window chain
  (sender → mule → hop1 → hop2), decay_ratio 1.0, span 20 minutes.
- **Expected system output:** a `layering` alert covering
  `DEMO-ACC-FUNNEL-01`, `-04`, `-05`, `-06` (and, depending on which
  sender's chain the detector's start-candidate ordering picks first,
  possibly a second alert rooted at `-02` or `-03`).
- **Edge case proved:** a fan-in-then-layer-out mule structure is
  demo-able even though this system has no first-class "funnel" detector —
  the layering half of the pattern is enough to surface it for
  investigation, where the fan-in shape becomes visible in the ego-graph.

---

## Known-correct investigation paths & feature explanations

The full prose "known-correct investigation path" and "feature explanation"
for each scenario (used by the Recommendation Engine / Copilot demo) live in
code as the single source of truth, not duplicated here:
`backend/demo_data/golden_scenarios.py::SCENARIOS` (`GoldenScenario.
known_correct_investigation_path` / `.feature_explanation` per entry).
