# HTTP Header Security Auditor

> Passive CLI audit tool for HTTP security headers — generates a self-contained HTML report and a machine-readable JSON export.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)
![Audit type](https://img.shields.io/badge/Audit-Passive%20%2F%20Legal-brightgreen)

---

## Table of contents

1. [Context and motivation](#context-and-motivation)
2. [Features](#features)
3. [Installation](#installation)
4. [Usage](#usage)
5. [Headers analysed and scoring](#headers-analysed-and-scoring)
6. [Grade scale](#grade-scale)
7. [Real-world results](#real-world-results)
8. [Report structure](#report-structure)
9. [Known limitations](#known-limitations)
10. [References](#references)

---

## Context and motivation

HTTP response headers are the first line of defence between a web server and a browser. A server can instruct the browser to enforce HTTPS, refuse to be embedded in an iframe, restrict script origins, and much more — all through a few header lines sent with every response.

In practice, these headers are frequently absent, misconfigured, or set to permissive defaults. Manual auditing is tedious and error-prone at scale. This tool automates the process:

- **Passive** — one standard HTTP request per target, no crawling, no login, no payload injection.
- **Legal** — equivalent to what any browser does when visiting a page.
- **Actionable** — every finding comes with a concrete recommendation, not just a flag.
- **Portable** — the output is a single HTML file that works offline and can be attached to a report or opened by a non-technical stakeholder.

---

## Features

- Analyses 7 security headers per domain: CSP, HSTS, X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Permissions-Policy, X-XSS-Protection
- Weighted scoring system (0–100) → grade A to F inspired by SSL Labs
- Handles redirects automatically (up to 5 hops), follows HTTP → HTTPS chains
- TLS certificate errors are flagged and the audit continues (non-blocking)
- Unreachable domains produce a zero-score row rather than crashing the run
- HTML report: fully self-contained (single file, no CDN, works offline), colour-coded, readable by a non-technical audience
- JSON export: machine-readable, suitable for CI pipelines or downstream tooling
- Structured logging (`INFO` by default, `DEBUG` with `--verbose`)

---

## Installation

**Requirements:** Python 3.10+

```bash
git clone https://github.com/adoucrispy/http-header-auditor.git
cd http-header-auditor
pip install requests jinja2
```

No virtual environment is required, but one is recommended for isolation:

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install requests jinja2
```

---

## Usage

### Audit a single domain

```bash
python auditor.py -u example.com
python auditor.py -u https://example.com
```

### Audit a list of domains

```bash
python auditor.py -t targets.txt
```

`targets.txt` — one domain or URL per line, lines starting with `#` are ignored:

```
# Production domains
https://www.example.com
https://api.example.com
blog.example.com
```

### Full option reference

```
usage: auditor [-h] (-u DOMAIN | -t FILE) [--output DIR] [--json] [--verbose]

options:
  -u, --url DOMAIN      Single domain or URL to audit
  -t, --targets FILE    File containing one domain/URL per line
  -o, --output DIR      Output directory (default: ./output)
  --json                Also export results as results.json
  --verbose             Enable DEBUG-level logging
```

### Examples

```bash
# Audit one domain, verbose mode
python auditor.py -u github.com --verbose

# Audit a list, produce HTML + JSON, custom output directory
python auditor.py -t targets.txt --json --output ./reports/2026-05-23

# Redirect output to a log file
python auditor.py -t targets.txt --json 2>audit.log
```

### Output files

| File | Always generated | Description |
|---|---|---|
| `output/report.html` | Yes | Interactive HTML report, self-contained |
| `output/results.json` | With `--json` | Structured JSON, one object per domain |

---

## Headers analysed and scoring

Each header is evaluated for **presence**, **value correctness**, and **compliance** with current best practices. Partial scores are awarded for headers that are present but misconfigured.

| Header | Weight | What is checked |
|---|---|---|
| `Content-Security-Policy` | 25 pts | Presence · absence of `unsafe-inline` / `unsafe-eval` · no wildcard in critical directives |
| `Strict-Transport-Security` | 20 pts | `max-age` ≥ 31 536 000 s (1 year) · `includeSubDomains` directive |
| `X-Content-Type-Options` | 15 pts | Exact value `nosniff` |
| `X-Frame-Options` | 15 pts | Value is `DENY` or `SAMEORIGIN` |
| `Referrer-Policy` | 10 pts | Restrictive value (`no-referrer`, `strict-origin`, `strict-origin-when-cross-origin`…) |
| `Permissions-Policy` | 10 pts | Presence · no wildcard on sensitive features (camera, microphone, geolocation…) |
| `X-XSS-Protection` | 5 pts | Deprecated — no penalty if CSP is present as a modern substitute |

**Total: 100 pts**

### Scoring logic in detail

**CSP (25 pts)**
- `unsafe-inline` detected → −10 pts (enables inline script/style injection)
- `unsafe-eval` detected → −10 pts (enables `eval()` and related sinks)
- Wildcard `*` in `default-src`, `script-src`, or `style-src` → −5 pts
- Absent → 0 pts

**HSTS (20 pts)**
- `max-age` missing → −10 pts
- `max-age` < 31 536 000 → −8 pts
- `includeSubDomains` missing → −5 pts
- Header absent → 0 pts

**X-XSS-Protection (5 pts)**
- Absent *and* CSP is also absent → 0 pts (combined gap)
- Absent *but* CSP is present → 5 pts (CSP is the modern replacement)
- Present → 5 pts + informational deprecation notice

---

## Grade scale

| Score | Grade | Interpretation |
|---|---|---|
| 90 – 100 | **A** | Excellent — headers are well configured |
| 75 – 89 | **B** | Good — minor gaps, low residual risk |
| 50 – 74 | **C** | Fair — several headers missing or misconfigured |
| 25 – 49 | **D** | Poor — significant exposure |
| 0 – 24 | **F** | Critical — most headers absent |

---

## Real-world results

Audit performed on 23 May 2026, one HEAD request per domain, no authentication.

| Domain | Grade | Score | Notable findings |
|---|---|---|---|
| www.google.com | **F** | 20 / 100 | CSP present but contains `unsafe-inline` and `unsafe-eval` · No `Permissions-Policy` · No `X-Frame-Options` |
| www.github.com | **C** | 73 / 100 | CSP contains `unsafe-inline` (−10 pts) · `Referrer-Policy` non-standard value (3 / 10 pts) · No `Permissions-Policy` |
| owasp.org | **C** | 72 / 100 | No `Permissions-Policy` · `Referrer-Policy` partially restrictive |
| www.mozilla.org | **C** | 60 / 100 | CSP present with `unsafe-inline` · No `Permissions-Policy` |
| www.cloudflare.com | **B** | 75 / 100 | Good overall · `Referrer-Policy` non-standard · No `Permissions-Policy` |

**Observation:** `Permissions-Policy` is the most consistently absent header across all five domains, including those of security-focused organisations. `Content-Security-Policy` is widely deployed but rarely hardened (the `unsafe-inline` exception is almost ubiquitous, often required by legacy analytics or UI frameworks).

---

## Report structure

### HTML report (`report.html`)

```
┌─ Page header ─────────────────────────────────────────────────┐
│  Tool name · "Passive audit — HTTP response header analysis"   │
├─ Meta strip ──────────────────────────────────────────────────┤
│  Generated · Tool version · Number of targets · User-Agent    │
├─ Overview (stats grid) ───────────────────────────────────────┤
│  Domains audited · Reachable · Unreachable · Avg. score       │
│  Grade distribution A / B / C / D / F                         │
├─ Results at a glance (summary table) ─────────────────────────┤
│  Domain · Grade badge · Score · Progress bar · Protocol       │
├─ Detailed analysis (one collapsible card per domain) ─────────┤
│  Per card:                                                     │
│    Grade badge · Domain · Final URL · Score                   │
│    ┌─ Header table ──────────────────────────────────────────┐ │
│    │ Header · Status · Score · Raw value · Recommendation    │ │
│    │ (× 7 rows, one per analysed header)                     │ │
│    └─────────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────────┘
```

The report is a **single self-contained `.html` file** — no CDN, no external fonts, no JavaScript libraries. It opens in any browser without an internet connection and can be attached to an email or stored in a git repository.

### JSON export (`results.json`)

```json
{
  "meta": {
    "tool_version": "1.0.0",
    "generated_at": "2026-05-23T21:34:13Z"
  },
  "summary": {
    "total_domains": 5,
    "reachable": 5,
    "unreachable": 0,
    "average_score": 60.0,
    "grade_distribution": { "A": 0, "B": 1, "C": 3, "D": 0, "F": 1 }
  },
  "results": [
    {
      "url": "https://www.github.com/",
      "final_url": "https://github.com/",
      "reachable": true,
      "tls_warning": false,
      "protocol": "HTTPS",
      "audited_at": "2026-05-23T21:34:12Z",
      "total_score": 73,
      "grade": "C",
      "error_message": null,
      "headers": [
        {
          "name": "content-security-policy",
          "display_name": "Content-Security-Policy",
          "status": "present",
          "raw_value": "default-src 'none'; ...",
          "score_awarded": 15,
          "score_max": 25,
          "recommendation": "Remove 'unsafe-inline' and 'unsafe-eval'...",
          "details": ["'unsafe-inline' detected — allows inline script/style injection."]
        }
      ]
    }
  ]
}
```

---

## Known limitations

**Scope**
- Only the initial HTTP response headers are analysed. Headers set by JavaScript (`document.cookie`, `meta` tags) are out of scope.
- A single request per domain — headers may vary by path, query string, or user-agent. Critical paths (login, API endpoints) should be audited separately.
- No authenticated requests — headers behind a login wall are not evaluated.

**Protocol**
- HEAD is used by default for efficiency; some servers return different headers for HEAD vs GET. The tool falls back to GET on HTTP 405.
- HTTP/2 and HTTP/3 pseudo-headers are not analysed.
- Only one IP per domain is tested; CDN edge nodes may return different headers per region.

**Scoring**
- The `Content-Security-Policy` analysis is lexical, not semantic. A syntactically valid but logically broken policy (e.g., a trusted domain that itself serves attacker-controlled content) will still score well.
- `Permissions-Policy` scoring only checks for wildcard overuse; it does not validate the full feature list against best-practice baselines.
- The `X-XSS-Protection` deprecation logic assumes that any CSP presence partially compensates — a weak CSP and a missing `X-XSS-Protection` will still score 0 on that header.

**Operational**
- Default timeout: 8 seconds per request. Slow servers may be incorrectly marked as unreachable.
- TLS certificate validation errors trigger a retry with `verify=False`. Results from such domains should be treated with caution — the server identity is unconfirmed.
- No rate limiting between requests. For large target lists on shared infrastructure, add a delay between requests to avoid triggering WAF rules.

---

## References

**Standards and specifications**
- [RFC 6797 — HTTP Strict Transport Security (HSTS)](https://datatracker.ietf.org/doc/html/rfc6797)
- [RFC 7034 — HTTP Header Field X-Frame-Options](https://datatracker.ietf.org/doc/html/rfc7034)
- [W3C Content Security Policy Level 3](https://www.w3.org/TR/CSP3/)
- [W3C Permissions Policy](https://www.w3.org/TR/permissions-policy-1/)
- [W3C Referrer Policy](https://www.w3.org/TR/referrer-policy/)

**OWASP**
- [OWASP Secure Headers Project](https://owasp.org/www-project-secure-headers/)
- [OWASP HTTP Security Response Headers Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/HTTP_Headers_Cheat_Sheet.html)
- [OWASP Clickjacking Defense Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Clickjacking_Defense_Cheat_Sheet.html)

**MDN Web Docs**
- [Content-Security-Policy](https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Content-Security-Policy)
- [Strict-Transport-Security](https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Strict-Transport-Security)
- [X-Content-Type-Options](https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/X-Content-Type-Options)
- [X-Frame-Options](https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/X-Frame-Options)
- [Referrer-Policy](https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Referrer-Policy)
- [Permissions-Policy](https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Permissions-Policy)

**Additional resources**
- [securityheaders.com](https://securityheaders.com) — online reference scanner
- [HSTS Preload List](https://hstspreload.org) — submit domains for browser-level HSTS preloading
- [Can I Use — Feature Policy](https://caniuse.com/?search=permissions-policy) — browser compatibility for Permissions-Policy

---

*This tool performs passive, read-only audits. It sends one standard HTTP request per target — equivalent to a browser visit. No exploitation, no crawling, no authentication bypass.*
