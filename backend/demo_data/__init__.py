"""
Demo & Training Data Studio (ROADMAP Phase 1B) -- a reproducible generator
producing three separate concerns, strictly isolated from the real ingest
path (`db/ingest.py`, `data/HI-Small_accounts.csv`):

  1. Training/reference data (`historical_cases.py`) -- a historical
     `cases`/`case_feature_vector`/`detection_feedback` corpus so Similar
     Historical Cases retrieval and the RL bandit both have something real
     to work from, not a cold start.
  2. KYC/customer mock (`kyc_customers.py`) -- `pep_status`/`sanction_status`
     /`kyc_status`/occupation-income-mismatch coverage the real IBM CSV
     dataset doesn't carry.
  3. Mock showcase data (`relationships.py`, `golden_scenarios.py`) --
     shared-attribute relationship networks (no transaction link) and one
     curated, detector-triggering network per typology.

Entry point: `seed.run_demo_data_studio`. CLI: `scripts/generate_demo_data.py`.

Every id this package creates is `demo_data.config.DemoDataConfig.prefix`
("DEMO-") -prefixed and every write goes through the normal repository layer
(`db/repositories/`) with `ActorType.SYSTEM, actor_id="demo-data-studio"` (or
the CLI's own actor id) -- there is no second, unaudited write path here.
"""
from __future__ import annotations
