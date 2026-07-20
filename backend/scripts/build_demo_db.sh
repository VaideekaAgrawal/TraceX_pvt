#!/usr/bin/env bash
# Build the crisp, India-centric pilot demo database from scratch.
#
# Produces a small (~200 KYC customers / ~2.7k transactions) but fully-KYC-linked
# dataset with a curated L1 / L2 / false-negative case mix and a reasonable alert
# count — as opposed to the full-scale IBM benchmark DB (5M txns, no KYC), which
# is kept separately for the ML "validated at scale" credential.
#
# Reproducible: fixed DEMO_SEED means the same dataset every run. Idempotent per
# generator. Usage (from backend/):
#     ./scripts/build_demo_db.sh
#
# Requires: a working venv at backend/.venv, PII_HMAC_KEY + OPENROUTER_API_KEY in
# .env (for relationship hashing / AI features). Points at data/tracex_demo.db.
set -euo pipefail
cd "$(dirname "$0")/.."

PY=.venv/bin/python
DB_PATH="$(cd .. && pwd)/data/tracex_demo.db"
export DATABASE_URL="sqlite:///${DB_PATH}"
export ENV=dev
PASSWORD="${DEMO_PASSWORD:-TraceX@2026}"

echo "Building demo DB at ${DB_PATH}"
rm -f "${DB_PATH}"

echo "1/6 schema"
.venv/bin/alembic upgrade head >/dev/null

echo "2/6 demo data (KYC + pilot transactions + relationships + historical cases)"
$PY scripts/generate_demo_data.py --skip-golden-scenarios >/dev/null

echo "3/6 rules (enable the crisp set, disable the noisy peer/behavioural detectors)"
$PY - <<'PY'
from sqlalchemy import text
from db.session import SessionLocal
from db.enums import ActorType
from detection.rules.seed import seed_builtin_rules
s = SessionLocal()
seed_builtin_rules(s, actor_type=ActorType.SYSTEM, actor_id="demo-build"); s.commit()
# peer_deviation / behavioural_shift are noisy on synthetic small-peer-group data;
# income_mismatch is the meaningful profile-mismatch signal and stays enabled.
s.execute(text("update rule_definitions set enabled=0 where rule_id in "
               "('builtin_peer_deviation','builtin_behavioural_shift')")); s.commit()
PY

echo "4/6 users (investigator1, investigator2, compliance1 — password: ${PASSWORD})"
$PY scripts/create_user.py --username investigator1 --email investigator1@demo.local \
    --password "${PASSWORD}" --full-name "Investigator One" --role INVESTIGATOR >/dev/null
$PY scripts/create_user.py --username investigator2 --email investigator2@demo.local \
    --password "${PASSWORD}" --full-name "Investigator Two" --role INVESTIGATOR >/dev/null
$PY scripts/create_user.py --username compliance1 --email compliance1@demo.local \
    --password "${PASSWORD}" --full-name "Compliance Lead" --role ADMIN_COMPLIANCE >/dev/null

echo "5/6 train detection model"
$PY scripts/train_detection_model.py >/dev/null

echo "6/6 run detection pipeline (one case per flagged account)"
$PY scripts/run_detection_pipeline.py --top-n-to-case 55 2>&1 | grep -iE "generated|created .*case"

echo "Done. Point the app at it: DATABASE_URL=${DATABASE_URL}"
