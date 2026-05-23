"""
headers.py — Header definitions, scoring rules, and analysis logic.

Each header is evaluated for presence, value correctness, and compliance
with security best practices. Scores are summed to produce a 0–100 grade.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Status enum
# ---------------------------------------------------------------------------

class HeaderStatus(str, Enum):
    PRESENT   = "present"    # Header found and value is compliant
    WARNING   = "warning"    # Header found but value is suboptimal
    ABSENT    = "absent"     # Header missing entirely
    EMPTY     = "empty"      # Header present but value is blank/whitespace
    DEPRECATED = "deprecated"  # Header is deprecated (informational)


# ---------------------------------------------------------------------------
# Result dataclass — one per header per domain
# ---------------------------------------------------------------------------

@dataclass
class HeaderResult:
    name: str                              # Canonical header name (lowercase)
    display_name: str                      # Pretty name for the report
    status: HeaderStatus
    raw_value: Optional[str]              # Exact value from the HTTP response
    score_awarded: int                     # Points actually awarded
    score_max: int                         # Maximum points possible
    recommendation: str                    # Human-readable guidance
    details: list[str] = field(default_factory=list)  # Bullet-point findings


# ---------------------------------------------------------------------------
# Top-level domain result
# ---------------------------------------------------------------------------

@dataclass
class DomainResult:
    url: str
    final_url: str                         # URL after redirects
    reachable: bool
    tls_warning: bool                      # True if cert was invalid / self-signed
    protocol: str                          # "HTTPS" or "HTTP"
    headers_raw: dict[str, str]           # Normalised lowercase headers
    header_results: list[HeaderResult]
    total_score: int
    grade: str
    error_message: Optional[str] = None   # Set when reachable is False
    audited_at: str = ""                  # ISO-8601 timestamp (filled by auditor)


# ---------------------------------------------------------------------------
# Individual header analyser functions
# ---------------------------------------------------------------------------

def _analyse_csp(raw: Optional[str]) -> HeaderResult:
    name = "content-security-policy"
    display = "Content-Security-Policy"
    max_pts = 25

    if not raw:
        return HeaderResult(
            name=name, display_name=display,
            status=HeaderStatus.ABSENT, raw_value=raw,
            score_awarded=0, score_max=max_pts,
            recommendation=(
                "Implement a Content-Security-Policy header. Start with "
                "'default-src \\'self\\'' and tighten per resource type."
            ),
        )

    score = 25
    details: list[str] = []

    # Unsafe directives — severe deductions
    if "unsafe-inline" in raw:
        score -= 10
        details.append("'unsafe-inline' detected — allows inline script/style injection.")
    if "unsafe-eval" in raw:
        score -= 10
        details.append("'unsafe-eval' detected — allows eval() and similar sinks.")

    # Wildcard sources
    if re.search(r"(?:default-src|script-src|style-src)\s+[^;]*\*", raw):
        score -= 5
        details.append("Wildcard (*) source detected in a critical directive.")

    score = max(score, 0)
    status = HeaderStatus.PRESENT if score >= 15 else HeaderStatus.WARNING

    rec = (
        "Remove 'unsafe-inline' and 'unsafe-eval'. Use nonces or hashes for "
        "inline code. Avoid wildcard origins in script/style directives."
        if details else
        "CSP looks good. Consider adding 'upgrade-insecure-requests' and "
        "'block-all-mixed-content' if not already present."
    )

    return HeaderResult(
        name=name, display_name=display,
        status=status, raw_value=raw,
        score_awarded=score, score_max=max_pts,
        recommendation=rec, details=details,
    )


def _analyse_hsts(raw: Optional[str]) -> HeaderResult:
    name = "strict-transport-security"
    display = "Strict-Transport-Security"
    max_pts = 20
    MIN_MAX_AGE = 31_536_000  # 1 year

    if not raw:
        return HeaderResult(
            name=name, display_name=display,
            status=HeaderStatus.ABSENT, raw_value=raw,
            score_awarded=0, score_max=max_pts,
            recommendation=(
                "Add 'Strict-Transport-Security: max-age=31536000; "
                "includeSubDomains; preload' to enforce HTTPS."
            ),
        )

    score = 20
    details: list[str] = []

    # max-age check
    ma_match = re.search(r"max-age=(\d+)", raw, re.IGNORECASE)
    if not ma_match:
        score -= 10
        details.append("max-age directive is missing.")
    else:
        max_age = int(ma_match.group(1))
        if max_age < MIN_MAX_AGE:
            score -= 8
            details.append(
                f"max-age={max_age} is below the recommended minimum of "
                f"{MIN_MAX_AGE:,} seconds (1 year)."
            )

    if "includesubdomains" not in raw.lower():
        score -= 5
        details.append("'includeSubDomains' is missing — subdomains remain unprotected.")

    score = max(score, 0)
    status = HeaderStatus.PRESENT if score >= 15 else HeaderStatus.WARNING

    rec = (
        "Set max-age to at least 31 536 000 s, add includeSubDomains, and "
        "consider submitting the domain to the HSTS preload list."
        if details else
        "HSTS is well configured. Verify the domain is on the preload list."
    )

    return HeaderResult(
        name=name, display_name=display,
        status=status, raw_value=raw,
        score_awarded=score, score_max=max_pts,
        recommendation=rec, details=details,
    )


def _analyse_xcto(raw: Optional[str]) -> HeaderResult:
    name = "x-content-type-options"
    display = "X-Content-Type-Options"
    max_pts = 15

    if not raw:
        return HeaderResult(
            name=name, display_name=display,
            status=HeaderStatus.ABSENT, raw_value=raw,
            score_awarded=0, score_max=max_pts,
            recommendation=(
                "Set 'X-Content-Type-Options: nosniff' to prevent MIME-type "
                "sniffing attacks."
            ),
        )

    if raw.strip().lower() == "nosniff":
        return HeaderResult(
            name=name, display_name=display,
            status=HeaderStatus.PRESENT, raw_value=raw,
            score_awarded=15, score_max=max_pts,
            recommendation="Correctly set. No action required.",
        )

    return HeaderResult(
        name=name, display_name=display,
        status=HeaderStatus.WARNING, raw_value=raw,
        score_awarded=5, score_max=max_pts,
        recommendation=(
            f"Value '{raw}' is non-standard. The only valid value is 'nosniff'."
        ),
        details=[f"Unexpected value: '{raw}'. Expected exactly 'nosniff'."],
    )


def _analyse_xfo(raw: Optional[str]) -> HeaderResult:
    name = "x-frame-options"
    display = "X-Frame-Options"
    max_pts = 15

    if not raw:
        return HeaderResult(
            name=name, display_name=display,
            status=HeaderStatus.ABSENT, raw_value=raw,
            score_awarded=0, score_max=max_pts,
            recommendation=(
                "Set 'X-Frame-Options: DENY' or 'SAMEORIGIN' to prevent "
                "clickjacking. Prefer CSP frame-ancestors for modern browsers."
            ),
        )

    normalised = raw.strip().upper()
    if normalised in ("DENY", "SAMEORIGIN"):
        return HeaderResult(
            name=name, display_name=display,
            status=HeaderStatus.PRESENT, raw_value=raw,
            score_awarded=15, score_max=max_pts,
            recommendation="Correctly set. No action required.",
        )

    # ALLOWFROM is deprecated and rarely valid
    return HeaderResult(
        name=name, display_name=display,
        status=HeaderStatus.WARNING, raw_value=raw,
        score_awarded=5, score_max=max_pts,
        recommendation=(
            "Use 'DENY' or 'SAMEORIGIN'. 'ALLOW-FROM' is deprecated and "
            "unsupported in modern browsers."
        ),
        details=[f"Non-recommended value: '{raw}'."],
    )


# Referrer-Policy values ordered from most to least restrictive
_REFERRER_RESTRICTIVE = {
    "no-referrer",
    "no-referrer-when-downgrade",
    "strict-origin",
    "strict-origin-when-cross-origin",
    "origin",
    "origin-when-cross-origin",
    "same-origin",
}

_REFERRER_PERMISSIVE = {"unsafe-url", ""}


def _analyse_referrer(raw: Optional[str]) -> HeaderResult:
    name = "referrer-policy"
    display = "Referrer-Policy"
    max_pts = 10

    if not raw:
        return HeaderResult(
            name=name, display_name=display,
            status=HeaderStatus.ABSENT, raw_value=raw,
            score_awarded=0, score_max=max_pts,
            recommendation=(
                "Set 'Referrer-Policy: strict-origin-when-cross-origin' or "
                "'no-referrer' to limit referrer leakage."
            ),
        )

    value = raw.strip().lower()
    if value in _REFERRER_RESTRICTIVE:
        # Most restrictive values get full score
        top_values = {"no-referrer", "strict-origin", "strict-origin-when-cross-origin"}
        score = 10 if value in top_values else 7
        return HeaderResult(
            name=name, display_name=display,
            status=HeaderStatus.PRESENT, raw_value=raw,
            score_awarded=score, score_max=max_pts,
            recommendation="Referrer-Policy is well configured.",
        )

    if value in _REFERRER_PERMISSIVE:
        return HeaderResult(
            name=name, display_name=display,
            status=HeaderStatus.WARNING, raw_value=raw,
            score_awarded=2, score_max=max_pts,
            recommendation=(
                "Value 'unsafe-url' leaks the full URL to all origins. "
                "Use 'strict-origin-when-cross-origin' or stricter."
            ),
            details=["'unsafe-url' sends full URL including path and query to third parties."],
        )

    return HeaderResult(
        name=name, display_name=display,
        status=HeaderStatus.WARNING, raw_value=raw,
        score_awarded=3, score_max=max_pts,
        recommendation=(
            f"Value '{raw}' is unrecognised. "
            "Use a standard Referrer-Policy value."
        ),
        details=[f"Unrecognised value: '{raw}'."],
    )


def _analyse_permissions(raw: Optional[str]) -> HeaderResult:
    name = "permissions-policy"
    display = "Permissions-Policy"
    max_pts = 10

    if not raw or not raw.strip():
        return HeaderResult(
            name=name, display_name=display,
            status=HeaderStatus.ABSENT, raw_value=raw,
            score_awarded=0, score_max=max_pts,
            recommendation=(
                "Add a Permissions-Policy header to restrict browser feature "
                "access (camera, microphone, geolocation, etc.)."
            ),
        )

    details: list[str] = []
    score = 10

    # Warn if powerful features are unrestricted
    powerful_features = ("camera", "microphone", "geolocation", "payment", "usb")
    for feature in powerful_features:
        # A feature listed without () or with (*) is overly permissive
        if re.search(rf"{feature}=\*", raw):
            score -= 2
            details.append(f"Feature '{feature}' is set to wildcard (*).")

    score = max(score, 0)
    status = HeaderStatus.PRESENT if score >= 8 else HeaderStatus.WARNING

    rec = (
        "Restrict powerful browser features explicitly. "
        "Example: 'camera=(), microphone=(), geolocation=(self)'."
        if details else
        "Permissions-Policy is present. Verify all sensitive features are restricted."
    )

    return HeaderResult(
        name=name, display_name=display,
        status=status, raw_value=raw,
        score_awarded=score, score_max=max_pts,
        recommendation=rec, details=details,
    )


def _analyse_xxss(raw: Optional[str], has_csp: bool) -> HeaderResult:
    """X-XSS-Protection is deprecated. Penalise absence only when CSP is missing."""
    name = "x-xss-protection"
    display = "X-XSS-Protection"
    max_pts = 5

    if not raw:
        if has_csp:
            return HeaderResult(
                name=name, display_name=display,
                status=HeaderStatus.DEPRECATED, raw_value=raw,
                score_awarded=5, score_max=max_pts,
                recommendation=(
                    "X-XSS-Protection is deprecated. CSP provides equivalent "
                    "or stronger protection — no action required."
                ),
            )
        return HeaderResult(
            name=name, display_name=display,
            status=HeaderStatus.ABSENT, raw_value=raw,
            score_awarded=0, score_max=max_pts,
            recommendation=(
                "X-XSS-Protection is deprecated. Implement a robust CSP instead "
                "of relying on this legacy header."
            ),
            details=["CSP is also absent — combined gap leaves XSS unmitigated at the header level."],
        )

    # Present but deprecated — informational
    return HeaderResult(
        name=name, display_name=display,
        status=HeaderStatus.DEPRECATED, raw_value=raw,
        score_awarded=5, score_max=max_pts,
        recommendation=(
            "X-XSS-Protection is deprecated in modern browsers. "
            "It can cause issues in IE. Rely on CSP instead."
        ),
    )


# ---------------------------------------------------------------------------
# Grade mapping
# ---------------------------------------------------------------------------

def score_to_grade(score: int) -> str:
    if score >= 90:
        return "A"
    if score >= 75:
        return "B"
    if score >= 50:
        return "C"
    if score >= 25:
        return "D"
    return "F"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def analyse_headers(headers_raw: dict[str, str]) -> tuple[list[HeaderResult], int, str]:
    """
    Analyse a normalised (lowercase keys) header dict.

    Returns:
        (list of HeaderResult, total_score, grade)
    """
    # Resolve each header value (None when absent)
    def get(name: str) -> Optional[str]:
        v = headers_raw.get(name, "").strip()
        return v if v else None

    csp_raw  = get("content-security-policy")
    has_csp  = csp_raw is not None

    results: list[HeaderResult] = [
        _analyse_csp(csp_raw),
        _analyse_hsts(get("strict-transport-security")),
        _analyse_xcto(get("x-content-type-options")),
        _analyse_xfo(get("x-frame-options")),
        _analyse_referrer(get("referrer-policy")),
        _analyse_permissions(get("permissions-policy")),
        _analyse_xxss(get("x-xss-protection"), has_csp),
    ]

    total = sum(r.score_awarded for r in results)
    grade = score_to_grade(total)
    return results, total, grade
