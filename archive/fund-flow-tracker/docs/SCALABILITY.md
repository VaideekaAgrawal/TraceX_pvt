# TraceX Scalability & Enterprise Architecture

## 1. Current Scalability Features

### Already Implemented ✅
| Feature | Implementation | Benefit |
|---------|---------------|---------|
| Stateless API | All state in DB | Horizontal scaling |
| Database Adapter | SQLite ↔ Neo4j | Flexible deployment |
| Response Caching | TTLCache (30s) | Reduced DB load |
| Batch Processing | 200K edge batches | Memory-safe graph building |
| GPU Acceleration | CUDA XGBoost | 10× faster ML training |
| Docker Support | Dockerfile | Container deployment |

---

## 2. Kubernetes Deployment Architecture

### Production Topology
```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Kubernetes Cluster                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │                        Ingress Controller                          │  │
│  │               (NGINX / AWS ALB Ingress Controller)                 │  │
│  └───────────────────────────┬────────────────────────────────────────┘  │
│                              │                                           │
│  ┌───────────────────────────┼───────────────────────────────────────┐  │
│  │                     Service Mesh (Optional Istio)                  │  │
│  └───────────────────────────┬───────────────────────────────────────┘  │
│                              │                                           │
│  ┌──────────────┐   ┌───────┴───────┐   ┌──────────────────────────┐   │
│  │  Frontend    │   │   API Server  │   │   Background Workers     │   │
│  │  Deployment  │   │   Deployment  │   │   (Detection Pipeline)   │   │
│  │  replicas: 3 │   │  replicas: 5  │   │   replicas: 2            │   │
│  │  HPA: 3-10   │   │  HPA: 3-20    │   │   HPA: 1-5               │   │
│  └──────────────┘   └───────────────┘   └──────────────────────────┘   │
│          │                  │                        │                  │
│          └──────────────────┼────────────────────────┘                  │
│                             │                                           │
│  ┌──────────────────────────┴────────────────────────────────────────┐  │
│  │                     Internal Services                              │  │
│  │  ┌───────────┐   ┌───────────┐   ┌───────────┐   ┌────────────┐  │  │
│  │  │   Redis   │   │   Neo4j   │   │   Kafka   │   │ Prometheus │  │  │
│  │  │  (Cache)  │   │ (Graph DB)│   │  (Events) │   │ (Metrics)  │  │  │
│  │  │ replicas:3│   │ replicas:3│   │ replicas:3│   │ replicas:2 │  │  │
│  │  └───────────┘   └───────────┘   └───────────┘   └────────────┘  │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Kubernetes Manifests

### API Server Deployment
```yaml
# k8s/api-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: tracex-api
  labels:
    app: tracex
    component: api
spec:
  replicas: 3
  selector:
    matchLabels:
      app: tracex
      component: api
  template:
    metadata:
      labels:
        app: tracex
        component: api
    spec:
      containers:
      - name: api
        image: tracex/api:latest
        ports:
        - containerPort: 8000
        resources:
          requests:
            memory: "512Mi"
            cpu: "250m"
          limits:
            memory: "2Gi"
            cpu: "1000m"
        env:
        - name: DB_BACKEND
          value: "neo4j"
        - name: NEO4J_URI
          valueFrom:
            secretKeyRef:
              name: tracex-secrets
              key: neo4j-uri
        - name: JWT_SECRET
          valueFrom:
            secretKeyRef:
              name: tracex-secrets
              key: jwt-secret
        livenessProbe:
          httpGet:
            path: /health/live
            port: 8000
          initialDelaySeconds: 10
          periodSeconds: 30
        readinessProbe:
          httpGet:
            path: /health/ready
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 10
---
apiVersion: v1
kind: Service
metadata:
  name: tracex-api-svc
spec:
  selector:
    app: tracex
    component: api
  ports:
  - port: 80
    targetPort: 8000
  type: ClusterIP
```

### Horizontal Pod Autoscaler
```yaml
# k8s/api-hpa.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: tracex-api-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: tracex-api
  minReplicas: 3
  maxReplicas: 20
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 60
      policies:
      - type: Pods
        value: 4
        periodSeconds: 60
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
      - type: Percent
        value: 25
        periodSeconds: 60
```

---

## 4. Performance Benchmarks

### Current Performance (Single Instance)
| Metric | Value | Target |
|--------|-------|--------|
| Transaction ingestion | 5M in 30s | ✅ Met |
| Graph construction | 517K nodes in 5s | ✅ Met |
| Detection pipeline | Full run in 45s | ✅ Met |
| API response (p95) | 200ms | ✅ Met |
| Evidence generation | 2s/pack | ✅ Met |

### Projected Scaled Performance
| Scale | Instances | Throughput | Latency (p99) |
|-------|-----------|------------|---------------|
| Small (Dev) | 1 API | 100 req/s | 500ms |
| Medium (POC) | 3 API | 500 req/s | 300ms |
| Large (Prod) | 10 API | 2000 req/s | 200ms |
| Enterprise | 20 API + 3 Neo4j | 5000 req/s | 150ms |

---

## 5. Data Partitioning Strategy

### Time-Based Partitioning (Neo4j)
```cypher
// Partition transactions by month
CREATE INDEX tx_timestamp_idx FOR (t:Transaction) ON (t.timestamp)

// Archive old transactions to cold storage
MATCH (t:Transaction)
WHERE t.timestamp < datetime() - duration({months: 6})
CALL apoc.export.json.query(
  "MATCH (t:Transaction) WHERE t.timestamp < $cutoff RETURN t",
  "archive_" + date() + ".json",
  {params: {cutoff: datetime() - duration({months: 6})}}
)
```

### Account Sharding (Future)
```
┌─────────────────────────────────────────────────────────────┐
│                    Account Router                            │
│  shard_id = hash(account_id) % num_shards                   │
└───────────────────────┬─────────────────────────────────────┘
                        │
    ┌───────────────────┼───────────────────┐
    │                   │                   │
┌───┴───┐         ┌─────┴─────┐       ┌─────┴─────┐
│Shard 1│         │  Shard 2  │       │  Shard 3  │
│ A-H   │         │   I-P     │       │   Q-Z     │
└───────┘         └───────────┘       └───────────┘
```

---

## 6. Observability Stack

### Metrics (Prometheus)
```python
# Add to api/server.py
from prometheus_client import Counter, Histogram, generate_latest

REQUEST_COUNT = Counter(
    'tracex_requests_total',
    'Total requests',
    ['method', 'endpoint', 'status']
)
REQUEST_LATENCY = Histogram(
    'tracex_request_duration_seconds',
    'Request latency',
    ['method', 'endpoint']
)
DETECTION_DURATION = Histogram(
    'tracex_detection_duration_seconds',
    'Detection pipeline duration',
    ['detector']
)

@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type="text/plain")
```

### Alerting Rules
```yaml
# prometheus/alerts.yml
groups:
- name: tracex
  rules:
  - alert: HighLatency
    expr: histogram_quantile(0.99, tracex_request_duration_seconds) > 2
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "High API latency detected"
      
  - alert: DetectionPipelineSlow
    expr: tracex_detection_duration_seconds > 120
    for: 10m
    labels:
      severity: critical
    annotations:
      summary: "Detection pipeline taking too long"
      
  - alert: HighErrorRate
    expr: rate(tracex_requests_total{status=~"5.."}[5m]) / rate(tracex_requests_total[5m]) > 0.05
    for: 5m
    labels:
      severity: critical
    annotations:
      summary: "Error rate exceeds 5%"
```

---

## 7. Disaster Recovery

### Backup Strategy
| Component | Backup Frequency | Retention | Recovery Time |
|-----------|------------------|-----------|---------------|
| Neo4j Database | Every 4 hours | 30 days | < 1 hour |
| SQLite (dev) | Daily | 7 days | < 15 min |
| Evidence Packs | Real-time (S3) | 7 years | < 5 min |
| ML Models | On training | 90 days | < 10 min |

### Recovery Procedures
1. **Database Failure**
   - Automatic failover to replica (Neo4j cluster)
   - SQLite restore from S3 backup if needed
   
2. **API Pod Failure**
   - Kubernetes auto-restarts failed pods
   - HPA scales up if capacity constrained
   
3. **Region Failure**
   - DNS failover to secondary region
   - RTO: 15 minutes, RPO: 4 hours

---

## 8. Cost Estimation

### Cloud Run (Small Scale)
| Resource | Specification | Monthly Cost |
|----------|--------------|--------------|
| API (2 instances) | 2 vCPU, 4GB | $100 |
| Frontend (2 instances) | 1 vCPU, 2GB | $50 |
| Neo4j Aura (free) | 200K nodes | $0 |
| Cloud Storage | 50GB | $5 |
| **Total** | | **$155/month** |

### GKE (Production Scale)
| Resource | Specification | Monthly Cost |
|----------|--------------|--------------|
| GKE Cluster | 3 nodes, e2-standard-4 | $300 |
| API Pods (avg 5) | 1 vCPU, 2GB each | Included |
| Neo4j Enterprise | 3-node cluster | $500 |
| Redis | HA cluster | $100 |
| Kafka | 3 brokers | $200 |
| Monitoring | Prometheus + Grafana | $50 |
| **Total** | | **$1,150/month** |
