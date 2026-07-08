"""
Security Module — Authentication, Authorization, and Audit Logging.

Implements:
- JWT-based authentication
- Role-based access control (RBAC)
- API rate limiting
- Audit trail logging

Production deployment should use proper secret management (Vault, AWS Secrets Manager).
"""
import hashlib
import hmac
import logging
import os
import time
from datetime import datetime, timedelta
from functools import wraps
from typing import Any, Callable, Dict, List, Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

# JWT library - graceful fallback if not installed
try:
    import jwt
    JWT_AVAILABLE = True
except ImportError:
    JWT_AVAILABLE = False

logger = logging.getLogger(__name__)


# ── Configuration ────────────────────────────────────────────────────────

# IMPORTANT: In production, use environment variables or secret manager
JWT_SECRET = os.getenv("JWT_SECRET", "CHANGE_ME_IN_PRODUCTION_USE_32_BYTES_MIN")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = int(os.getenv("JWT_EXPIRATION_HOURS", "8"))

# Rate limiting configuration
RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS", "100"))  # Per minute
RATE_LIMIT_WINDOW_SECONDS = 60


# ── Models ───────────────────────────────────────────────────────────────

class User(BaseModel):
    """User model for authentication."""
    user_id: str
    username: str
    email: str
    role: str  # ADMIN, INVESTIGATOR, ANALYST, VIEWER
    department: Optional[str] = None
    is_active: bool = True


class TokenPayload(BaseModel):
    """JWT token payload."""
    sub: str  # user_id
    role: str
    exp: int
    iat: int


class AuditEntry(BaseModel):
    """Audit log entry."""
    timestamp: str
    user_id: str
    action: str
    resource: str
    resource_id: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


# ── Role-Based Access Control ────────────────────────────────────────────

ROLE_PERMISSIONS = {
    "ADMIN": [
        "read:*", "write:*", "delete:*", "admin:*",
    ],
    "INVESTIGATOR": [
        "read:accounts", "read:transactions", "read:alerts", "read:patterns",
        "write:cases", "write:evidence", "read:graph",
        "write:feedback",  # Can mark TP/FP
    ],
    "ANALYST": [
        "read:accounts", "read:transactions", "read:alerts", "read:patterns",
        "read:graph", "read:overview",
    ],
    "VIEWER": [
        "read:overview", "read:alerts",
    ],
}


def has_permission(user_role: str, required_permission: str) -> bool:
    """Check if a role has the required permission."""
    permissions = ROLE_PERMISSIONS.get(user_role, [])
    
    # Check for wildcard permissions
    if "read:*" in permissions and required_permission.startswith("read:"):
        return True
    if "write:*" in permissions and required_permission.startswith("write:"):
        return True
    if "delete:*" in permissions and required_permission.startswith("delete:"):
        return True
    if "admin:*" in permissions and required_permission.startswith("admin:"):
        return True
    
    return required_permission in permissions


# ── JWT Authentication ───────────────────────────────────────────────────

security = HTTPBearer(auto_error=False)


def create_token(user: User) -> str:
    """Create JWT token for authenticated user."""
    if not JWT_AVAILABLE:
        raise HTTPException(500, "JWT library not installed")
    
    now = datetime.utcnow()
    payload = {
        "sub": user.user_id,
        "role": user.role,
        "username": user.username,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=JWT_EXPIRATION_HOURS)).timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_token(token: str) -> TokenPayload:
    """Verify JWT token and return payload."""
    if not JWT_AVAILABLE:
        raise HTTPException(500, "JWT library not installed")
    
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return TokenPayload(**payload)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token has expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid token: {e}")


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> Optional[User]:
    """
    FastAPI dependency to get current authenticated user.
    
    Usage:
        @app.get("/protected")
        async def protected_route(user: User = Depends(get_current_user)):
            ...
    """
    # Allow bypass in development (SECURITY_ENABLED=false)
    if os.getenv("SECURITY_ENABLED", "true").lower() == "false":
        return User(
            user_id="dev_user",
            username="developer",
            email="dev@tracex.local",
            role="ADMIN",
        )
    
    if not credentials:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")
    
    payload = verify_token(credentials.credentials)
    
    # In production, fetch full user from database
    return User(
        user_id=payload.sub,
        username=payload.sub,  # Would be fetched from DB
        email=f"{payload.sub}@tracex.local",
        role=payload.role,
    )


def require_permission(permission: str):
    """
    Decorator to require specific permission.
    
    Usage:
        @app.get("/admin-only")
        @require_permission("admin:users")
        async def admin_route(user: User = Depends(get_current_user)):
            ...
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, user: User = None, **kwargs):
            if user is None:
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")
            if not has_permission(user.role, permission):
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN,
                    f"Permission denied: {permission} required (your role: {user.role})"
                )
            return await func(*args, user=user, **kwargs)
        return wrapper
    return decorator


# ── Rate Limiting ────────────────────────────────────────────────────────

class RateLimiter:
    """Simple in-memory rate limiter (use Redis in production)."""
    
    def __init__(self, requests_per_minute: int = RATE_LIMIT_REQUESTS):
        self.limit = requests_per_minute
        self.window = RATE_LIMIT_WINDOW_SECONDS
        self._requests: Dict[str, List[float]] = {}

    def _get_client_id(self, request: Request) -> str:
        """Get unique client identifier."""
        # Use IP + user_id if authenticated
        ip = request.client.host if request.client else "unknown"
        user_id = getattr(request.state, "user_id", "anonymous")
        return f"{ip}:{user_id}"

    def is_allowed(self, request: Request) -> bool:
        """Check if request is allowed under rate limit."""
        client_id = self._get_client_id(request)
        now = time.time()
        
        # Clean old requests
        if client_id in self._requests:
            self._requests[client_id] = [
                t for t in self._requests[client_id]
                if now - t < self.window
            ]
        else:
            self._requests[client_id] = []
        
        # Check limit
        if len(self._requests[client_id]) >= self.limit:
            return False
        
        self._requests[client_id].append(now)
        return True

    def get_remaining(self, request: Request) -> int:
        """Get remaining requests in current window."""
        client_id = self._get_client_id(request)
        now = time.time()
        
        if client_id not in self._requests:
            return self.limit
        
        recent = [t for t in self._requests[client_id] if now - t < self.window]
        return max(0, self.limit - len(recent))


rate_limiter = RateLimiter()


async def check_rate_limit(request: Request):
    """FastAPI dependency to check rate limits."""
    if not rate_limiter.is_allowed(request):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Rate limit exceeded. Please wait before making more requests.",
            headers={"Retry-After": str(RATE_LIMIT_WINDOW_SECONDS)},
        )


# ── Audit Logging ────────────────────────────────────────────────────────

class AuditLogger:
    """Audit logger for security-sensitive operations."""
    
    def __init__(self):
        self._entries: List[AuditEntry] = []
        self._max_entries = 10000  # In production, use proper storage

    def log(self, user_id: str, action: str, resource: str,
            resource_id: Optional[str] = None,
            request: Optional[Request] = None,
            details: Optional[Dict] = None):
        """Log an audit event."""
        entry = AuditEntry(
            timestamp=datetime.utcnow().isoformat(),
            user_id=user_id,
            action=action,
            resource=resource,
            resource_id=resource_id,
            ip_address=request.client.host if request and request.client else None,
            user_agent=request.headers.get("user-agent") if request else None,
            details=details,
        )
        
        self._entries.append(entry)
        
        # Rotate old entries
        if len(self._entries) > self._max_entries:
            self._entries = self._entries[-self._max_entries:]
        
        # Also log to application logger
        logger.info(
            "AUDIT: user=%s action=%s resource=%s:%s",
            user_id, action, resource, resource_id or ""
        )

    def get_entries(self, user_id: Optional[str] = None,
                    action: Optional[str] = None,
                    since: Optional[str] = None,
                    limit: int = 100) -> List[AuditEntry]:
        """Query audit entries with filters."""
        result = self._entries
        
        if user_id:
            result = [e for e in result if e.user_id == user_id]
        if action:
            result = [e for e in result if e.action == action]
        if since:
            result = [e for e in result if e.timestamp >= since]
        
        return result[-limit:]


audit_logger = AuditLogger()


# ── Data Masking ─────────────────────────────────────────────────────────

def mask_account_id(account_id: str) -> str:
    """Mask account ID for privacy (show first 3 and last 2 chars)."""
    if len(account_id) <= 5:
        return "***"
    return f"{account_id[:3]}***{account_id[-2:]}"


def mask_amount(amount: float, user_role: str) -> str:
    """Mask transaction amounts based on role."""
    if user_role in ("ADMIN", "INVESTIGATOR"):
        return f"₹{amount:,.2f}"
    # Analysts see rounded amounts
    if user_role == "ANALYST":
        if amount >= 1e7:
            return f"₹{amount/1e7:.1f} Cr"
        if amount >= 1e5:
            return f"₹{amount/1e5:.1f} L"
        return f"₹{amount/1e3:.0f} K"
    # Viewers see only risk level
    return "***"


# ── Secure Hashing ───────────────────────────────────────────────────────

def hash_sensitive_data(data: str) -> str:
    """Hash sensitive data using SHA-256."""
    return hashlib.sha256(data.encode()).hexdigest()


def verify_hash(data: str, expected_hash: str) -> bool:
    """Verify data against expected hash."""
    actual_hash = hash_sensitive_data(data)
    return hmac.compare_digest(actual_hash, expected_hash)
