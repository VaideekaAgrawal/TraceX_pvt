# TraceX Security Architecture

## Overview

TraceX implements defense-in-depth security with multiple layers of protection for financial crime investigation data.

---

## 1. Authentication

### JWT-Based Authentication
```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   Client    │───▶│  /api/auth  │───▶│  JWT Token  │
│   (Login)   │    │   /login    │    │  (8h expiry)│
└─────────────┘    └─────────────┘    └─────────────┘
                         │
                         ▼
              ┌─────────────────────┐
              │  Validate Credentials│
              │  (LDAP/AD or DB)    │
              └─────────────────────┘
```

### Token Structure
```json
{
  "sub": "user_001",           // User ID
  "role": "INVESTIGATOR",      // Role for RBAC
  "username": "john.doe",
  "iat": 1719763200,           // Issued at
  "exp": 1719792000            // Expires (8 hours)
}
```

### Implementation
- Use `infrastructure/security.py` for JWT functions
- Configure via environment variables:
  - `JWT_SECRET` — Minimum 32 bytes, keep secret
  - `JWT_EXPIRATION_HOURS` — Default 8 hours

---

## 2. Authorization (RBAC)

### Role Hierarchy
| Role | Permissions | Use Case |
|------|-------------|----------|
| **ADMIN** | Full access | System administrators |
| **INVESTIGATOR** | Read all + write cases/evidence | Fraud investigation team |
| **ANALYST** | Read accounts, transactions, patterns | Data analysis team |
| **VIEWER** | Read overview and alerts only | Management dashboards |

### Permission Matrix
| Resource | ADMIN | INVESTIGATOR | ANALYST | VIEWER |
|----------|-------|--------------|---------|--------|
| Accounts | R/W/D | R | R | ❌ |
| Transactions | R/W/D | R | R | ❌ |
| Alerts | R/W/D | R | R | R |
| Patterns | R/W/D | R | R | ❌ |
| Cases | R/W/D | R/W | ❌ | ❌ |
| Evidence | R/W/D | R/W | ❌ | ❌ |
| Graph | R/W/D | R | R | ❌ |
| System Config | R/W/D | ❌ | ❌ | ❌ |

### Usage Example
```python
from infrastructure.security import get_current_user, require_permission

@app.get("/api/evidence/{case_id}")
@require_permission("read:evidence")
async def get_evidence(case_id: str, user: User = Depends(get_current_user)):
    audit_logger.log(user.user_id, "VIEW", "evidence", case_id, request)
    return evidence_service.get(case_id)
```

---

## 3. Rate Limiting

### Configuration
| Endpoint Type | Limit | Window |
|---------------|-------|--------|
| Read endpoints | 100/min | 60 seconds |
| Write endpoints | 20/min | 60 seconds |
| Upload endpoints | 5/min | 60 seconds |
| Authentication | 10/min | 60 seconds |

### Response Headers
```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 45
X-RateLimit-Reset: 1719763260
```

### Production: Use Redis
```python
# For distributed rate limiting, replace in-memory limiter
# with Redis-backed implementation
redis_client = redis.Redis.from_url(os.getenv("REDIS_URL"))
```

---

## 4. Audit Logging

### Logged Events
| Event | Logged Fields |
|-------|---------------|
| Login/Logout | user_id, ip, timestamp, success |
| Data Access | user_id, resource, resource_id, timestamp |
| Evidence Generation | user_id, case_id, account_ids, timestamp |
| Configuration Change | user_id, setting, old_value, new_value |
| Export/Download | user_id, resource, format, timestamp |

### Log Format
```json
{
  "timestamp": "2026-06-30T10:15:00Z",
  "user_id": "user_001",
  "action": "VIEW",
  "resource": "account",
  "resource_id": "ACC_12345",
  "ip_address": "192.168.1.100",
  "user_agent": "Mozilla/5.0...",
  "details": {"query_filters": {"risk_level": "HIGH"}}
}
```

### Retention
- Hot storage: 90 days (queryable)
- Cold storage: 7 years (compliance)

---

## 5. Data Protection

### Data Classification
| Level | Data Types | Protection |
|-------|-----------|------------|
| **SECRET** | Investigation notes, evidence | Encrypted at rest + audit |
| **CONFIDENTIAL** | Account details, transactions | Encrypted at rest |
| **INTERNAL** | Aggregated stats, patterns | Standard access control |
| **PUBLIC** | API documentation | None |

### Data Masking
```python
# Mask account IDs for non-privileged users
mask_account_id("ACC123456789")  # → "ACC***89"

# Mask amounts based on role
mask_amount(1500000, "VIEWER")   # → "***"
mask_amount(1500000, "ANALYST")  # → "₹15 L"
mask_amount(1500000, "ADMIN")    # → "₹15,00,000.00"
```

### Evidence Integrity
- All evidence packs include SHA-256 hash
- Hash stored separately for tamper detection
- Verification endpoint: `GET /api/evidence/{id}/verify`

---

## 6. Network Security

### Production Deployment
```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  Internet   │───▶│   WAF/CDN   │───▶│   Load      │
│             │    │  (CloudFront)│    │   Balancer  │
└─────────────┘    └─────────────┘    └─────────────┘
                                            │
                   ┌────────────────────────┼────────────────────────┐
                   │        Private VPC                              │
                   │  ┌─────────────┐    ┌─────────────┐            │
                   │  │  API Server │    │  Database   │            │
                   │  │  (port 8000)│    │  (Neo4j)    │            │
                   │  └─────────────┘    └─────────────┘            │
                   └─────────────────────────────────────────────────┘
```

### TLS Configuration
- TLS 1.3 only (disable 1.0, 1.1, 1.2)
- Strong cipher suites
- HSTS enabled (max-age=31536000)

---

## 7. Security Checklist

### Development
- [ ] Never commit secrets to git
- [ ] Use `.env` files (gitignored) for local secrets
- [ ] Run security linter (bandit) before commit

### Deployment
- [ ] Rotate JWT_SECRET on each deployment
- [ ] Enable WAF rules for SQL injection, XSS
- [ ] Configure VPC security groups
- [ ] Enable CloudWatch/Datadog alerts

### Operations
- [ ] Review audit logs weekly
- [ ] Rotate credentials quarterly
- [ ] Penetration testing annually
- [ ] Security training for all developers

---

## 8. Incident Response

### Security Event Severity
| Level | Example | Response Time |
|-------|---------|---------------|
| **P1 Critical** | Data breach, unauthorized access | Immediate |
| **P2 High** | Brute force attempt, suspicious activity | 1 hour |
| **P3 Medium** | Failed login spike, rate limit exceeded | 4 hours |
| **P4 Low** | Configuration issue, certificate warning | 24 hours |

### Contact
- Security Team: security@unionbank.com
- Incident Hotline: +91-XXX-XXXXXXX
