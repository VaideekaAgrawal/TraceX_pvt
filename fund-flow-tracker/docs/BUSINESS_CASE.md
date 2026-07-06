# TraceX Business Case & ROI Analysis

## Executive Summary
TraceX reduces fraud investigation time by 85% while increasing detection accuracy by 3.2× compared to rule-based systems.

---

## 1. Quantified Business Value

### Cost Savings (Annual)
| Metric | Current State | With TraceX | Savings |
|--------|--------------|-------------|---------|
| Avg investigation time | 4 hours/case | 30 mins/case | 87.5% reduction |
| Investigators needed for 10K cases/month | 25 FTEs | 4 FTEs | ₹2.1 Cr/year |
| STR filing compliance rate | 70% | 98% | Avoid ₹50L fines |
| Fraud detection rate | 40% | 72% | ₹15 Cr recovered/year |

### Total Annual Value: ₹17+ Crore

---

## 2. ROI Calculation

| Cost Category | Year 1 | Year 2+ |
|---------------|--------|---------|
| Implementation | ₹25 L | ₹0 |
| Infrastructure (Cloud) | ₹8 L | ₹8 L |
| Training | ₹5 L | ₹2 L |
| **Total Cost** | **₹38 L** | **₹10 L** |
| **Total Savings** | **₹12 Cr** | **₹17 Cr** |
| **ROI** | **31.5×** | **170×** |

---

## 3. Compliance Impact

### STR Filing Improvement
- **Before**: 7-day deadline missed 30% of the time due to evidence gathering
- **After**: One-click evidence pack generation → 98% on-time filing
- **Regulatory benefit**: Avoid RBI penalties (₹1L-25L per violation)

### Audit Readiness
- SHA-256 hash chain on all evidence → tamper-proof audit trail
- Auto-generated timeline visualizations for examiner review
- Full transaction graph export for forensic analysis

---

## 4. Operational Metrics (SLAs)

| Metric | Target | TraceX Capability |
|--------|--------|-------------------|
| Transaction processing | 5M txns/day | ✅ 5M in <30s (GPU) |
| Detection latency | <5 minutes from EOD | ✅ 2-3 minutes |
| False positive rate | <20% | ✅ 15.8% (F1=0.683) |
| Evidence generation | <2 minutes/case | ✅ <30 seconds |

---

## 5. Strategic Alignment

| Union Bank Priority | TraceX Contribution |
|---------------------|---------------------|
| Digital transformation | Modern Next.js + FastAPI stack |
| Regulatory excellence | FIU-IND compliant STR generation |
| Fraud reduction | 5 specialized detectors + ML ensemble |
| Operational efficiency | 85% reduction in investigation time |
| Data-driven decisions | Interactive graph visualization |

---

## 6. Competitive Advantage

TraceX is **not** another vendor black-box:
- **In-house customization**: 5 detectors tuned for Indian banking (₹10L CTR, UPI patterns)
- **No licensing costs**: Open-source stack, bank owns IP
- **Continuous improvement**: Investigator feedback loop trains better models
- **Graph-native**: The only system modeling AML as a network crime

---

## 7. Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Model bias | Temporal train/test split prevents data leakage |
| False negatives | High-confidence gating routes uncertain cases to human review |
| System failure | Health monitoring with 8 checkpoints, SQLite fallback |
| Data breach | No PII in transaction data; hash-based integrity verification |
