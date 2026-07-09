# TraceX Integration Roadmap

## Core Banking System Integration

### Phase 1: Data Ingestion (Current)
- ✅ CSV upload via UI
- ✅ CLI-based EOD ingestion (`scripts/ingest_eod.py`)
- ✅ Idempotent processing with SHA-256 file hashing

### Phase 2: CBS Integration (Planned)
```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Finacle/T24    │────▶│  Kafka/MQ       │────▶│    TraceX       │
│  Transaction    │     │  Message Queue  │     │    Ingestion    │
│  Log Export     │     │                 │     │    Service      │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

**Supported CBS Systems:**
| CBS | Integration Method | API/Protocol |
|-----|-------------------|--------------|
| Finacle (Infosys) | Finacle APIs | REST + SOAP |
| T24 (Temenos) | TAFj OFS | OFS Messaging |
| BaNCS (TCS) | BaNCS Open | REST APIs |
| FIS Profile | Profile Anywhere | MQ Series |

### Phase 3: Real-Time Streaming (Future)
```python
# Kafka consumer configuration
kafka_config = {
    "bootstrap_servers": "ubi-kafka-cluster:9092",
    "topics": ["ubi.transactions.neft", "ubi.transactions.rtgs", 
               "ubi.transactions.upi", "ubi.transactions.imps"],
    "consumer_group": "tracex-detection-group",
    "auto_offset_reset": "latest",
}
```

---

## API Integration Points

### Existing APIs (Ready for Integration)
| Endpoint | Purpose | Integration Use |
|----------|---------|-----------------|
| `POST /api/ingest/upload` | Transaction upload | CBS batch export |
| `GET /api/anomaly` | Anomaly scores | Risk dashboard |
| `POST /api/evidence/generate` | STR generation | Compliance workflow |
| `GET /api/accounts/{id}` | Account details | Case management |

### Planned APIs (Roadmap)
| Endpoint | Purpose | Timeline |
|----------|---------|----------|
| `POST /api/stream/ingest` | Real-time transaction | Q3 2026 |
| `POST /api/feedback/label` | Investigator TP/FP | Q2 2026 |
| `GET /api/model/retrain` | Trigger retraining | Q3 2026 |
| `POST /api/alerts/escalate` | Case escalation | Q2 2026 |

---

## Compliance System Integration

### FIU-IND Reporting
```
TraceX Evidence Pack → FIU-IND Portal Upload
                    ↓
    ┌───────────────────────────────────────┐
    │ STR JSON Payload                       │
    │ - entity_details: account_info         │
    │ - suspicion_grounds: pattern_type      │
    │ - transaction_details: full_timeline   │
    │ - supporting_documents: pdf_bytes      │
    │ - integrity_hash: sha256               │
    └───────────────────────────────────────┘
```

### Audit Trail Integration
- All evidence packs include SHA-256 hash for integrity verification
- Checkpoint history exported for compliance auditors
- Model version tracking for explainability requirements
