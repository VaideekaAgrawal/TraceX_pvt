"""
Domain constants for TraceX — Indian banking AML context.
All thresholds aligned with PMLA/RBI guidelines.
"""

# Account types found in Indian PSBs
ACCOUNT_TYPES = [
    "savings", "current", "salary", "NRO", "NRE",
    "overdraft", "prepaid_card",
]

# Transaction channels
CHANNELS = [
    "net_banking", "mobile_app", "UPI", "NEFT", "RTGS",
    "IMPS", "ATM", "branch_cash", "cheque",
]

# Branch cities (Indian tier-1 and tier-2)
BRANCH_CITIES = [
    "Mumbai", "Delhi", "Bengaluru", "Chennai", "Kolkata",
    "Hyderabad", "Pune", "Ahmedabad", "Jaipur", "Lucknow",
    "Nagpur", "Indore", "Bhopal", "Surat", "Kochi", "Guwahati",
]

# Occupation categories
OCCUPATIONS = [
    "salaried", "self_employed", "business_owner", "professional",
    "retired", "student", "homemaker", "farmer", "NRI",
]

# Income brackets (annual, INR)
INCOME_BRACKETS = {
    "low":       (100_000,   500_000),
    "medium":    (500_001, 1_500_000),
    "high":    (1_500_001, 5_000_000),
    "very_high": (5_000_001, 50_000_000),
}

# Regulatory thresholds (RBI / PMLA)
CTR_THRESHOLD = 1_000_000          # ₹10 lakh — CTR reporting threshold
STRUCTURING_LOWER = 900_000        # ₹9 lakh — structuring detection lower bound
STRUCTURING_UPPER = 999_999        # Just below ₹10 lakh
SUSPICIOUS_VELOCITY = 5            # Transactions in <10 min window
MAX_DORMANT_DAYS = 180             # 6 months = dormant

# IBM AML channel mapping to Indian context
IBM_CHANNEL_MAP = {
    "ACH": "NEFT",
    "Wire": "RTGS",
    "Cheque": "cheque",
    "Cash": "branch_cash",
    "Credit Card": "net_banking",
    "Bitcoin": "UPI",
    "Reinvestment": "IMPS",
}

# Approximate FX rates for IBM data conversion to INR
FX_RATES = {
    "US Dollar": 83.0,
    "Euro": 91.0,
    "UK Pound": 106.0,
    "Yuan": 11.5,
    "Yen": 0.56,
    "Rupee": 1.0,
    "Indian Rupee": 1.0,
    "Ruble": 0.93,
    # Note: this dataset's "Bitcoin" amounts are already on the same numeric
    # scale as its fiat-currency amounts (not raw BTC quantities), so treat
    # it like a normal foreign currency rather than multiplying by a real
    # whole-BTC/INR rate (which previously inflated ~20% of transactions to
    # nonsensical values, e.g. Rs 11,791 -> Rs 6,485 crore).
    "Bitcoin": 83.0,
    "Saudi Riyal": 22.1,
    "Swiss Franc": 95.0,
    "Australian Dollar": 55.0,
    "Canadian Dollar": 62.0,
    "Brazilian Real": 16.5,
    "Mexican Peso": 4.8,
}

# Risk level thresholds
RISK_LEVELS = {
    "LOW":      (0, 25),
    "MEDIUM":   (26, 50),
    "HIGH":     (51, 75),
    "CRITICAL": (76, 100),
}

RISK_COLORS = {
    "LOW": "#2ecc71",
    "MEDIUM": "#f39c12",
    "HIGH": "#e67e22",
    "CRITICAL": "#e74c3c",
}

# Confidence levels
CONFIDENCE_LEVELS = {
    "Weak":   1,
    "Moderate": 2,
    "Strong": 3,
    "Very Strong": 4,
}

# FIU-IND suspicion categories
SUSPICION_CATEGORIES = {
    1: "Identity documents appear false/forged",
    2: "Transactions inconsistent with customer profile",
    3: "Structuring/Smurfing to avoid reporting threshold",
    4: "Layering through multiple accounts/entities",
    5: "Use of shell companies or nominees",
    6: "Rapid movement of funds (pass-through)",
    7: "Round-tripping / circular transactions",
    8: "Transactions with high-risk jurisdictions",
    9: "Unusual cash transactions",
    10: "Trade-based money laundering indicators",
    11: "Terrorist financing indicators",
    12: "Counterfeit currency involvement",
    13: "Other (specify in narrative)",
}

# Investigation priority
PRIORITY_LABELS = {
    "P1": "🔴 Immediate",
    "P2": "🟠 High",
    "P3": "🟡 Medium",
    "P4": "🟢 Low",
}
