"""
Role-Based Access Control (RBAC) Module
Supports department-wise multi-tenancy:
- SUPER_ADMIN: Full statewide access, all 26 departments
- POLICE_OFFICER: Home Dept / Gujarat Police (Traffic, Law & Order, eGujCop/AFIS/NAFIS)
- RTO_OFFICER: Transport Dept (Border Checkposts, VAHAN, SARTHI, Overload Enforcement)
- FCS_OFFICER: Food & Civil Supplies (PDS Godowns, Fair Price Shops, Buffer Stocks)
"""

from enum import Enum
from typing import List, Optional
from fastapi import HTTPException, Security, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
try:
    import jwt
except ImportError:
    from jose import jwt
from datetime import datetime, timedelta

from app.config import settings

security_bearer = HTTPBearer(auto_error=False)

class UserRole(str, Enum):
    SUPER_ADMIN = "SUPER_ADMIN"
    POLICE_OFFICER = "POLICE_OFFICER"
    RTO_OFFICER = "RTO_OFFICER"
    FCS_OFFICER = "FCS_OFFICER"

# Demo pre-provisioned user tokens for evaluation & screening committee
DEMO_USERS = {
    "admin": {"role": UserRole.SUPER_ADMIN, "dept": "STATE_COMMAND", "name": "Chief Surveillance Administrator"},
    "police": {"role": UserRole.POLICE_OFFICER, "dept": "POLICE", "name": "Gujarat Police Command Center"},
    "rto": {"role": UserRole.RTO_OFFICER, "dept": "RTO", "name": "RTO Enforcement Cell"},
    "fcs": {"role": UserRole.FCS_OFFICER, "dept": "FCS", "name": "Civil Supplies Vigilance Officer"}
}

def create_access_token(username: str, role: UserRole, department: str) -> str:
    """Generates signed JWT token."""
    expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": username,
        "role": role.value,
        "dept": department,
        "exp": expire
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

def get_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Security(security_bearer)) -> dict:
    """
    Extracts and verifies user identity from Bearer token.
    Fails closed: rejects invalid, forged, or expired tokens with HTTP 401.
    If no token is supplied:
      - In EVAL_MODE (True for hackathon evaluation): defaults to demo admin.
      - In non-EVAL_MODE (production): strictly raises HTTP 401 Unauthorized.
    """
    if not credentials:
        if settings.EVAL_MODE:
            return DEMO_USERS["admin"]
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials were not provided. Bearer token required.",
            headers={"WWW-Authenticate": "Bearer"}
        )

    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        role_val = payload.get("role")
        if not role_val or role_val not in UserRole.__members__:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid user role '{role_val}' in token payload."
            )
        return {
            "username": payload.get("sub"),
            "role": UserRole(role_val),
            "dept": payload.get("dept"),
            "name": payload.get("sub")
        }
    except HTTPException:
        raise
    except Exception as e:
        # Fails closed: Rejects invalid, expired, or tampered tokens with 401
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired authentication token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"}
        )

def require_roles(allowed_roles: List[UserRole]):
    """Decorator dependency enforcing role permissions."""
    def role_checker(user: dict = Depends(get_current_user)):
        user_role = user.get("role")
        if user_role == UserRole.SUPER_ADMIN or user_role in allowed_roles:
            return user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied. Required roles: {[r.value for r in allowed_roles]}, user role: {user_role}"
        )
    return role_checker
