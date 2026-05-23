"""
auditor.py — CLI entry point for the HTTP Header Security Auditor.

Fetches HTTP response headers from one or more targets, runs the scoring
engine, and delegates report/JSON generation to report.py.

Usage:
    python auditor.py -u example.com
    python auditor.py -t targets.txt
    python auditor.py -t targets.txt --json --output ./out --verbose
"""

from __future__ import annotations

import argparse
import datetime
import logging
import os
import sys
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, urlunparse

import requests
import requests.exceptions

from headers import DomainResult, analyse_headers

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TOOL_VERSION   = "1.0.0"
DEFAULT_TIMEOUT = 8          # seconds per request
MAX_REDIRECTS  = 5
USER_AGENT     = (
    f"HeaderAuditor/{TOOL_VERSION} "
    "(security audit tool; https://github.com/adoucrispy/http-header-auditor)"
)

logger = logging.getLogger("auditor")


# ---------------------------------------------------------------------------
# URL normalisation
# ---------------------------------------------------------------------------

def _normalise_url(raw: str) -> str:
    """Ensure the target has a scheme. Bare domains default to https://."""
    raw = raw.strip()
    if not raw:
        raise ValueError("Empty URL")
    if "://" not in raw:
        raw = "https://" + raw
    parsed = urlparse(raw)
    # Rebuild to discard trailing whitespace / fragments
    return urlunparse((
        parsed.scheme.lower(),
        parsed.netloc.lower(),
        parsed.path or "/",
        parsed.params,
        parsed.query,
        "",   # strip fragment
    ))


# ---------------------------------------------------------------------------
# HTTP fetch
# ---------------------------------------------------------------------------

def fetch_domain(url: str) -> DomainResult:
    """
    Send a HEAD request (fallback: GET) to *url* and return a DomainResult.

    TLS errors trigger a second attempt with verify=False so the audit
    continues; the result is flagged with tls_warning=True.
    """
    normalised = _normalise_url(url)
    timestamp  = datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z"
    tls_warning = False
    final_url   = normalised

    session = requests.Session()
    session.max_redirects = MAX_REDIRECTS
    session.headers.update({"User-Agent": USER_AGENT})

    def _do_request(verify: bool) -> requests.Response:
        # Prefer HEAD to avoid downloading a response body; fall back to GET
        # if the server returns 405 Method Not Allowed.
        try:
            resp = session.head(
                normalised,
                timeout=DEFAULT_TIMEOUT,
                allow_redirects=True,
                verify=verify,
            )
            if resp.status_code == 405:
                logger.debug("%s — HEAD returned 405, retrying with GET", normalised)
                resp = session.get(
                    normalised,
                    timeout=DEFAULT_TIMEOUT,
                    allow_redirects=True,
                    verify=verify,
                    stream=True,   # avoid downloading the body
                )
                resp.close()
            return resp
        except requests.exceptions.TooManyRedirects:
            raise
        except requests.exceptions.SSLError:
            raise
        except requests.exceptions.Timeout:
            raise
        except requests.exceptions.ConnectionError:
            raise

    try:
        response = _do_request(verify=True)

    except requests.exceptions.SSLError as exc:
        logger.warning(
            "%s — TLS certificate error (%s). Retrying with verify=False.",
            normalised, exc,
        )
        tls_warning = True
        try:
            response = _do_request(verify=False)
        except requests.exceptions.RequestException as inner:
            return _unreachable(normalised, timestamp, str(inner))

    except requests.exceptions.Timeout:
        msg = f"Request timed out after {DEFAULT_TIMEOUT}s"
        logger.warning("%s — %s", normalised, msg)
        return _unreachable(normalised, timestamp, msg)

    except requests.exceptions.TooManyRedirects:
        msg = f"Too many redirects (limit: {MAX_REDIRECTS})"
        logger.warning("%s — %s", normalised, msg)
        return _unreachable(normalised, timestamp, msg)

    except requests.exceptions.ConnectionError as exc:
        msg = f"Connection error: {exc}"
        logger.warning("%s — %s", normalised, msg)
        return _unreachable(normalised, timestamp, msg)

    except requests.exceptions.RequestException as exc:
        msg = f"Request failed: {exc}"
        logger.warning("%s — %s", normalised, msg)
        return _unreachable(normalised, timestamp, msg)

    # Successful response ------------------------------------------------
    final_url = response.url
    protocol  = "HTTPS" if final_url.startswith("https://") else "HTTP"

    # Normalise header names to lowercase (requests keys are case-preserving)
    headers_raw = {k.lower(): v for k, v in response.headers.items()}

    header_results, total_score, grade = analyse_headers(headers_raw)

    logger.info(
        "%s — %s  score=%d  grade=%s%s",
        normalised,
        protocol,
        total_score,
        grade,
        " [TLS WARNING]" if tls_warning else "",
    )

    return DomainResult(
        url=normalised,
        final_url=final_url,
        reachable=True,
        tls_warning=tls_warning,
        protocol=protocol,
        headers_raw=headers_raw,
        header_results=header_results,
        total_score=total_score,
        grade=grade,
        error_message=None,
        audited_at=timestamp,
    )


def _unreachable(url: str, timestamp: str, reason: str) -> DomainResult:
    """Return a zero-score DomainResult for an inaccessible domain."""
    _, score, grade = analyse_headers({})
    return DomainResult(
        url=url,
        final_url=url,
        reachable=False,
        tls_warning=False,
        protocol="N/A",
        headers_raw={},
        header_results=_,
        total_score=0,
        grade="F",
        error_message=reason,
        audited_at=timestamp,
    )


# ---------------------------------------------------------------------------
# Target loading
# ---------------------------------------------------------------------------

def load_targets(path: Path) -> list[str]:
    """Read a targets file and return non-empty, non-comment lines."""
    if not path.exists():
        logger.error("Targets file not found: %s", path)
        sys.exit(1)

    targets: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            targets.append(stripped)

    if not targets:
        logger.error("No valid targets found in %s", path)
        sys.exit(1)

    return targets


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="auditor",
        description="HTTP Header Security Auditor — evaluate security headers and generate a report.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python auditor.py -u example.com\n"
            "  python auditor.py -t targets.txt --json --output ./out\n"
            "  python auditor.py -t targets.txt --verbose\n"
        ),
    )

    # Target selection — mutually exclusive
    target_group = parser.add_mutually_exclusive_group(required=True)
    target_group.add_argument(
        "-u", "--url",
        metavar="DOMAIN",
        help="Single domain or URL to audit (e.g. example.com or https://example.com).",
    )
    target_group.add_argument(
        "-t", "--targets",
        metavar="FILE",
        type=Path,
        help="Path to a file containing one domain/URL per line.",
    )

    # Output options
    parser.add_argument(
        "--output", "-o",
        metavar="DIR",
        type=Path,
        default=Path("output"),
        help="Directory for generated files (default: ./output).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Also export results as results.json.",
    )

    # Verbosity
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable DEBUG-level logging.",
    )

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = _build_parser()
    args   = parser.parse_args()

    # Logging setup
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )

    # Collect targets
    if args.url:
        targets = [args.url]
    else:
        targets = load_targets(args.targets)

    logger.info("Auditing %d target(s)…", len(targets))

    # Run audits
    results: list[DomainResult] = []
    for i, target in enumerate(targets, 1):
        logger.info("[%d/%d] %s", i, len(targets), target)
        result = fetch_domain(target)
        results.append(result)

    # Prepare output directory
    output_dir: Path = args.output
    output_dir.mkdir(parents=True, exist_ok=True)

    # Import report module here to keep startup fast when --help is used
    from report import build_report, build_json  # noqa: PLC0415

    # HTML report (always generated)
    html_path = output_dir / "report.html"
    build_report(results, html_path, tool_version=TOOL_VERSION, user_agent=USER_AGENT)
    logger.info("HTML report written → %s", html_path.resolve())

    # JSON export (optional)
    if args.json:
        json_path = output_dir / "results.json"
        build_json(results, json_path, tool_version=TOOL_VERSION)
        logger.info("JSON export written  → %s", json_path.resolve())

    # Console summary
    _print_summary(results)


def _print_summary(results: list[DomainResult]) -> None:
    """Print a compact results table to stdout."""
    GRADE_COLOR = {"A": "\033[92m", "B": "\033[92m", "C": "\033[93m",
                   "D": "\033[91m", "F": "\033[91m"}
    RESET = "\033[0m"

    # Detect Windows terminal — colour support varies
    use_color = sys.stdout.isatty() and os.name != "nt" or (
        os.name == "nt" and os.environ.get("TERM_PROGRAM") in ("vscode", "alacritty")
    )

    print()
    print(f"{'Domain':<45}  {'Grade':^5}  {'Score':>5}  {'Status'}")
    print("-" * 72)
    for r in results:
        grade_str = r.grade
        if use_color:
            color = GRADE_COLOR.get(r.grade, "")
            grade_str = f"{color}{r.grade}{RESET}"

        domain = urlparse(r.url).netloc or r.url
        if len(domain) > 44:
            domain = domain[:41] + "…"

        if r.reachable:
            status = f"{r.protocol}" + (" [TLS WARN]" if r.tls_warning else "")
        else:
            status = f"UNREACHABLE — {r.error_message}"

        print(f"{domain:<45}  {grade_str:^5}  {r.total_score:>5}  {status}")
    print()


if __name__ == "__main__":
    main()
