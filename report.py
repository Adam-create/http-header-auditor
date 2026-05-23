"""
report.py — HTML report and JSON export generation.

build_report() renders a fully self-contained HTML file (no external CDN).
build_json()   serialises results to a structured JSON file.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any

from jinja2 import Environment, BaseLoader

from headers import DomainResult, HeaderStatus


# ---------------------------------------------------------------------------
# Grade / status metadata used by both the template and the JSON exporter
# ---------------------------------------------------------------------------

GRADE_META: dict[str, dict[str, str]] = {
    "A": {"label": "A", "color": "#16a34a", "bg": "#dcfce7", "desc": "Excellent"},
    "B": {"label": "B", "color": "#65a30d", "bg": "#ecfccb", "desc": "Good"},
    "C": {"label": "C", "color": "#d97706", "bg": "#fef3c7", "desc": "Fair"},
    "D": {"label": "D", "color": "#dc2626", "bg": "#fee2e2", "desc": "Poor"},
    "F": {"label": "F", "color": "#991b1b", "bg": "#fee2e2", "desc": "Critical"},
}

STATUS_META: dict[str, dict[str, str]] = {
    "present":    {"icon": "✓", "color": "#16a34a", "bg": "#dcfce7", "label": "Present"},
    "warning":    {"icon": "⚠", "color": "#d97706", "bg": "#fef3c7", "label": "Warning"},
    "absent":     {"icon": "✗", "color": "#dc2626", "bg": "#fee2e2", "label": "Absent"},
    "empty":      {"icon": "✗", "color": "#dc2626", "bg": "#fee2e2", "label": "Empty"},
    "deprecated": {"icon": "~", "color": "#6b7280", "bg": "#f3f4f6", "label": "Deprecated"},
}

# Short explanations for non-technical readers
HEADER_DESC: dict[str, str] = {
    "content-security-policy": (
        "Tells the browser which sources are allowed to load scripts, "
        "styles, images and other resources. Prevents cross-site scripting (XSS)."
    ),
    "strict-transport-security": (
        "Forces the browser to use HTTPS for all future requests to this domain, "
        "preventing protocol-downgrade and man-in-the-middle attacks."
    ),
    "x-content-type-options": (
        "Prevents the browser from guessing (sniffing) the file type. "
        "Stops attacks that disguise malicious files as safe ones."
    ),
    "x-frame-options": (
        "Controls whether the page can be embedded inside an iframe on another site. "
        "Prevents clickjacking attacks."
    ),
    "referrer-policy": (
        "Limits how much URL information is sent to third-party sites when a "
        "user follows a link. Protects user privacy and sensitive query parameters."
    ),
    "permissions-policy": (
        "Restricts which browser features (camera, microphone, geolocation…) "
        "the page and embedded third-party content can access."
    ),
    "x-xss-protection": (
        "Legacy browser XSS filter, now deprecated. Modern browsers rely on "
        "Content-Security-Policy instead."
    ),
}


# ---------------------------------------------------------------------------
# Jinja2 HTML template (fully self-contained — no external assets)
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>HTTP Header Security Report</title>
<style>
  /* ---- Reset & base ---------------------------------------------------- */
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  html { font-size: 15px; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                 "Helvetica Neue", Arial, sans-serif;
    background: #f8fafc;
    color: #1e293b;
    line-height: 1.55;
    padding: 0 0 4rem;
  }
  a { color: inherit; text-decoration: none; }

  /* ---- Layout ---------------------------------------------------------- */
  .page-header {
    background: #0f172a;
    color: #f1f5f9;
    padding: 2rem 2.5rem 1.8rem;
    border-bottom: 3px solid #1d4ed8;
  }
  .page-header h1 { font-size: 1.55rem; font-weight: 700; letter-spacing: -.02em; }
  .page-header p  { color: #94a3b8; font-size: .85rem; margin-top: .3rem; }
  .container { max-width: 1100px; margin: 0 auto; padding: 0 1.5rem; }

  /* ---- Meta strip ------------------------------------------------------ */
  .meta-strip {
    background: #1e293b;
    color: #94a3b8;
    font-size: .78rem;
    padding: .5rem 2.5rem;
    display: flex;
    gap: 2rem;
    flex-wrap: wrap;
  }
  .meta-strip span { white-space: nowrap; }
  .meta-strip strong { color: #cbd5e1; }

  /* ---- Section titles -------------------------------------------------- */
  .section-title {
    font-size: 1rem;
    font-weight: 600;
    color: #475569;
    text-transform: uppercase;
    letter-spacing: .06em;
    margin: 2.2rem 0 .9rem;
    padding-bottom: .4rem;
    border-bottom: 1px solid #e2e8f0;
  }

  /* ---- Summary stats --------------------------------------------------- */
  .stats-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 1rem;
    margin-bottom: 1.5rem;
  }
  .stat-card {
    background: #fff;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    padding: 1.1rem 1.2rem;
    text-align: center;
  }
  .stat-card .value {
    font-size: 2rem;
    font-weight: 700;
    line-height: 1;
  }
  .stat-card .label {
    font-size: .75rem;
    color: #64748b;
    margin-top: .3rem;
    text-transform: uppercase;
    letter-spacing: .05em;
  }

  /* ---- Summary table --------------------------------------------------- */
  .summary-table {
    width: 100%;
    border-collapse: collapse;
    background: #fff;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    overflow: hidden;
    font-size: .88rem;
  }
  .summary-table thead th {
    background: #f1f5f9;
    color: #475569;
    font-weight: 600;
    text-transform: uppercase;
    font-size: .73rem;
    letter-spacing: .07em;
    padding: .75rem 1rem;
    text-align: left;
    border-bottom: 1px solid #e2e8f0;
  }
  .summary-table tbody tr {
    border-bottom: 1px solid #f1f5f9;
    transition: background .12s;
  }
  .summary-table tbody tr:last-child { border-bottom: none; }
  .summary-table tbody tr:hover { background: #f8fafc; }
  .summary-table td { padding: .7rem 1rem; vertical-align: middle; }
  .summary-table .domain { font-weight: 500; font-family: "SF Mono", "Fira Mono", monospace; font-size: .82rem; }
  .summary-table .score-bar-cell { width: 160px; }
  .score-bar-wrap { background: #e2e8f0; border-radius: 4px; height: 7px; overflow: hidden; }
  .score-bar { height: 100%; border-radius: 4px; transition: width .3s; }

  /* ---- Grade badge ----------------------------------------------------- */
  .grade-badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 2.1rem;
    height: 2.1rem;
    border-radius: 6px;
    font-weight: 800;
    font-size: 1rem;
    letter-spacing: -.02em;
  }

  /* ---- Protocol / status chips ---------------------------------------- */
  .chip {
    display: inline-block;
    padding: .15rem .55rem;
    border-radius: 20px;
    font-size: .72rem;
    font-weight: 600;
    letter-spacing: .03em;
    vertical-align: middle;
  }
  .chip-https  { background: #dcfce7; color: #15803d; }
  .chip-http   { background: #fee2e2; color: #b91c1c; }
  .chip-warn   { background: #fef3c7; color: #b45309; }
  .chip-unreachable { background: #f1f5f9; color: #64748b; }

  /* ---- Domain detail cards --------------------------------------------- */
  .domain-card {
    background: #fff;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    margin-bottom: 1.2rem;
    overflow: hidden;
  }
  .domain-card summary {
    list-style: none;
    cursor: pointer;
    padding: 1.1rem 1.4rem;
    display: flex;
    align-items: center;
    gap: 1rem;
    user-select: none;
  }
  .domain-card summary::-webkit-details-marker { display: none; }
  .domain-card summary:hover { background: #f8fafc; }
  .domain-card .toggle-icon {
    font-size: .75rem;
    color: #94a3b8;
    margin-left: auto;
    transition: transform .2s;
    flex-shrink: 0;
  }
  .domain-card[open] .toggle-icon { transform: rotate(90deg); }
  .domain-card .domain-name {
    font-family: "SF Mono", "Fira Mono", monospace;
    font-size: .9rem;
    font-weight: 600;
    color: #1e293b;
    word-break: break-all;
  }
  .domain-card .domain-meta {
    font-size: .75rem;
    color: #64748b;
    margin-top: .15rem;
  }
  .domain-card .score-inline {
    font-size: .82rem;
    color: #64748b;
    white-space: nowrap;
  }

  /* ---- Unreachable banner ---------------------------------------------- */
  .unreachable-banner {
    background: #fef2f2;
    border-top: 1px solid #fecaca;
    padding: 1rem 1.4rem;
    color: #991b1b;
    font-size: .85rem;
    display: flex;
    align-items: center;
    gap: .6rem;
  }

  /* ---- Header table ---------------------------------------------------- */
  .header-table-wrap { padding: 0 1.4rem 1.4rem; }
  .header-table {
    width: 100%;
    border-collapse: collapse;
    font-size: .83rem;
  }
  .header-table thead th {
    background: #f8fafc;
    color: #475569;
    font-size: .71rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: .07em;
    padding: .6rem .8rem;
    text-align: left;
    border-bottom: 1px solid #e2e8f0;
  }
  .header-table tbody tr { border-bottom: 1px solid #f1f5f9; }
  .header-table tbody tr:last-child { border-bottom: none; }
  .header-table td { padding: .75rem .8rem; vertical-align: top; }
  .header-table .col-header { width: 22%; font-weight: 600; }
  .header-table .col-status { width: 11%; }
  .header-table .col-score  { width: 8%;  text-align: right; white-space: nowrap; }
  .header-table .col-value  { width: 28%; }
  .header-table .col-rec    { width: 31%; }

  .status-badge {
    display: inline-flex;
    align-items: center;
    gap: .3rem;
    padding: .18rem .55rem;
    border-radius: 20px;
    font-size: .72rem;
    font-weight: 600;
    white-space: nowrap;
  }

  .raw-value {
    font-family: "SF Mono", "Fira Mono", monospace;
    font-size: .72rem;
    color: #374151;
    background: #f8fafc;
    border: 1px solid #e5e7eb;
    border-radius: 4px;
    padding: .2rem .45rem;
    word-break: break-all;
    display: inline-block;
    max-width: 100%;
  }
  .raw-value.absent { color: #9ca3af; font-style: italic; }

  .detail-bullets {
    list-style: none;
    margin-top: .4rem;
    font-size: .76rem;
    color: #dc2626;
  }
  .detail-bullets li::before { content: "› "; font-weight: 700; }

  .header-desc {
    font-size: .75rem;
    color: #64748b;
    font-style: italic;
    margin-bottom: .5rem;
    border-left: 3px solid #e2e8f0;
    padding-left: .6rem;
  }

  /* ---- TLS warning row ------------------------------------------------- */
  .tls-row td {
    background: #fffbeb;
    color: #92400e;
    font-size: .78rem;
    padding: .5rem .8rem;
    border-top: 1px solid #fde68a;
  }

  /* ---- Toolbar --------------------------------------------------------- */
  .toolbar {
    display: flex;
    gap: .6rem;
    align-items: center;
    margin: 1.2rem 0 .8rem;
    flex-wrap: wrap;
  }
  .btn {
    background: #1d4ed8;
    color: #fff;
    border: none;
    border-radius: 6px;
    padding: .4rem .9rem;
    font-size: .8rem;
    font-weight: 600;
    cursor: pointer;
    transition: background .15s;
  }
  .btn:hover { background: #1e40af; }
  .btn-ghost {
    background: #fff;
    color: #475569;
    border: 1px solid #cbd5e1;
  }
  .btn-ghost:hover { background: #f1f5f9; }

  /* ---- Footer ---------------------------------------------------------- */
  .page-footer {
    text-align: center;
    color: #94a3b8;
    font-size: .75rem;
    margin-top: 3rem;
    padding-top: 1.5rem;
    border-top: 1px solid #e2e8f0;
  }

  /* ---- Print ----------------------------------------------------------- */
  @media print {
    .toolbar, .btn { display: none !important; }
    .domain-card[open] summary .toggle-icon { display: none; }
    body { background: #fff; }
  }
</style>
</head>
<body>

<header class="page-header">
  <h1>HTTP Header Security Report</h1>
  <p>Passive audit — HTTP response header analysis per domain</p>
</header>

<div class="meta-strip">
  <span><strong>Generated:</strong> {{ meta.generated_at }}</span>
  <span><strong>Tool:</strong> HeaderAuditor v{{ meta.tool_version }}</span>
  <span><strong>Targets:</strong> {{ results|length }}</span>
  <span><strong>User-Agent:</strong> {{ meta.user_agent }}</span>
</div>

<div class="container">

  <!-- ===== Summary stats ===== -->
  <p class="section-title">Overview</p>
  <div class="stats-grid">
    {% set reachable = results | selectattr("reachable") | list %}
    <div class="stat-card">
      <div class="value" style="color:#1d4ed8">{{ results|length }}</div>
      <div class="label">Domains audited</div>
    </div>
    <div class="stat-card">
      <div class="value" style="color:#16a34a">{{ reachable|length }}</div>
      <div class="label">Reachable</div>
    </div>
    <div class="stat-card">
      <div class="value" style="color:#dc2626">{{ results|length - reachable|length }}</div>
      <div class="label">Unreachable</div>
    </div>
    {% if reachable %}
    <div class="stat-card">
      {% set avg = (reachable | map(attribute="total_score") | sum / reachable|length) | round(1) %}
      <div class="value" style="color:{{ grade_color(avg|int) }}">{{ avg }}</div>
      <div class="label">Avg. score / 100</div>
    </div>
    {% endif %}
    {% for g in ["A","B","C","D","F"] %}
    {% set count = results | selectattr("grade","equalto",g) | list | length %}
    <div class="stat-card">
      <div class="value">
        <span class="grade-badge"
          style="background:{{ grade_meta[g].bg }};color:{{ grade_meta[g].color }}">
          {{ g }}
        </span>
        &nbsp;{{ count }}
      </div>
      <div class="label">Grade {{ g }} — {{ grade_meta[g].desc }}</div>
    </div>
    {% endfor %}
  </div>

  <!-- ===== Summary table ===== -->
  <p class="section-title">Results at a glance</p>
  <table class="summary-table">
    <thead>
      <tr>
        <th>Domain</th>
        <th>Grade</th>
        <th>Score</th>
        <th class="score-bar-cell">Progress</th>
        <th>Protocol</th>
        <th>Audited at</th>
      </tr>
    </thead>
    <tbody>
      {% for r in results %}
      {% set gm = grade_meta[r.grade] %}
      <tr>
        <td class="domain">
          <a href="#domain-{{ loop.index }}">{{ domain_label(r.url) }}</a>
        </td>
        <td>
          <span class="grade-badge"
            style="background:{{ gm.bg }};color:{{ gm.color }}">{{ r.grade }}</span>
        </td>
        <td><strong>{{ r.total_score }}</strong> / 100</td>
        <td class="score-bar-cell">
          <div class="score-bar-wrap">
            <div class="score-bar"
              style="width:{{ r.total_score }}%;background:{{ gm.color }}"></div>
          </div>
        </td>
        <td>
          {% if not r.reachable %}
            <span class="chip chip-unreachable">UNREACHABLE</span>
          {% elif r.protocol == "HTTPS" %}
            <span class="chip chip-https">HTTPS</span>
            {% if r.tls_warning %}<span class="chip chip-warn">TLS WARN</span>{% endif %}
          {% else %}
            <span class="chip chip-http">HTTP</span>
          {% endif %}
        </td>
        <td style="font-size:.78rem;color:#64748b;">{{ r.audited_at }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>

  <!-- ===== Per-domain detail ===== -->
  <p class="section-title">Detailed analysis</p>

  <div class="toolbar">
    <button class="btn" onclick="expandAll()">Expand all</button>
    <button class="btn btn-ghost" onclick="collapseAll()">Collapse all</button>
  </div>

  {% for r in results %}
  {% set gm = grade_meta[r.grade] %}
  <details class="domain-card" id="domain-{{ loop.index }}">
    <summary>
      <span class="grade-badge"
        style="background:{{ gm.bg }};color:{{ gm.color }};flex-shrink:0">{{ r.grade }}</span>
      <span>
        <div class="domain-name">{{ domain_label(r.url) }}</div>
        <div class="domain-meta">
          {{ r.final_url }}
          {% if r.tls_warning %}&nbsp;·&nbsp;<span style="color:#d97706">⚠ TLS certificate warning</span>{% endif %}
        </div>
      </span>
      <span class="score-inline">
        <strong style="font-size:1.1rem;color:{{ gm.color }}">{{ r.total_score }}</strong>
        <span style="color:#94a3b8">/100</span>
      </span>
      <span class="toggle-icon">▶</span>
    </summary>

    {% if not r.reachable %}
    <div class="unreachable-banner">
      <span>✗</span>
      <span><strong>Unreachable</strong> — {{ r.error_message }}</span>
    </div>
    {% endif %}

    <div class="header-table-wrap">
      <table class="header-table">
        <thead>
          <tr>
            <th class="col-header">Header</th>
            <th class="col-status">Status</th>
            <th class="col-score">Score</th>
            <th class="col-value">Raw value</th>
            <th class="col-rec">Recommendation</th>
          </tr>
        </thead>
        <tbody>
          {% if r.tls_warning %}
          <tr class="tls-row">
            <td colspan="5">
              ⚠&nbsp;<strong>TLS Warning</strong> — The server's certificate could not be
              verified (self-signed or expired). The audit continued with certificate
              verification disabled. Treat these results with caution.
            </td>
          </tr>
          {% endif %}
          {% for h in r.header_results %}
          {% set sm = status_meta[h.status] %}
          <tr>
            <td class="col-header">
              <div><strong>{{ h.display_name }}</strong></div>
              {% set desc = header_desc.get(h.name, "") %}
              {% if desc %}
              <div class="header-desc">{{ desc }}</div>
              {% endif %}
            </td>
            <td class="col-status">
              <span class="status-badge"
                style="background:{{ sm.bg }};color:{{ sm.color }}">
                {{ sm.icon }}&nbsp;{{ sm.label }}
              </span>
            </td>
            <td class="col-score" style="color:{{ sm.color }};font-weight:700">
              {{ h.score_awarded }}<span style="color:#94a3b8;font-weight:400">/{{ h.score_max }}</span>
            </td>
            <td class="col-value">
              {% if h.raw_value %}
                <span class="raw-value">{{ h.raw_value | truncate(120, True, "…") }}</span>
              {% else %}
                <span class="raw-value absent">— not present —</span>
              {% endif %}
            </td>
            <td class="col-rec">
              {{ h.recommendation }}
              {% if h.details %}
              <ul class="detail-bullets">
                {% for d in h.details %}<li>{{ d }}</li>{% endfor %}
              </ul>
              {% endif %}
            </td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </details>
  {% endfor %}

</div><!-- /container -->

<div class="page-footer container">
  <p>
    HeaderAuditor v{{ meta.tool_version }} &nbsp;·&nbsp;
    Passive audit — only standard HTTP requests were sent &nbsp;·&nbsp;
    References:
    <a href="https://owasp.org/www-project-secure-headers/" style="color:#60a5fa">OWASP Secure Headers</a> ·
    <a href="https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers" style="color:#60a5fa">MDN HTTP Headers</a>
  </p>
</div>

<script>
  function expandAll()  { document.querySelectorAll(".domain-card").forEach(d => d.open = true); }
  function collapseAll(){ document.querySelectorAll(".domain-card").forEach(d => d.open = false); }
</script>

</body>
</html>"""


# ---------------------------------------------------------------------------
# Template helpers
# ---------------------------------------------------------------------------

def _grade_color(score: int) -> str:
    if score >= 90: return "#16a34a"
    if score >= 75: return "#65a30d"
    if score >= 50: return "#d97706"
    if score >= 25: return "#dc2626"
    return "#991b1b"


def _domain_label(url: str) -> str:
    from urllib.parse import urlparse
    netloc = urlparse(url).netloc
    return netloc if netloc else url


# ---------------------------------------------------------------------------
# Public: HTML report
# ---------------------------------------------------------------------------

def build_report(
    results: list[DomainResult],
    output_path: Path,
    *,
    tool_version: str,
    user_agent: str,
) -> None:
    env = Environment(loader=BaseLoader(), autoescape=True)
    env.globals["grade_meta"]   = GRADE_META
    env.globals["status_meta"]  = STATUS_META
    env.globals["header_desc"]  = HEADER_DESC
    env.globals["grade_color"]  = _grade_color
    env.globals["domain_label"] = _domain_label

    template = env.from_string(_HTML_TEMPLATE)

    html = template.render(
        results=results,
        meta={
            "tool_version": tool_version,
            "user_agent":   user_agent,
            "generated_at": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        },
    )

    output_path.write_text(html, encoding="utf-8")


# ---------------------------------------------------------------------------
# Public: JSON export
# ---------------------------------------------------------------------------

def build_json(
    results: list[DomainResult],
    output_path: Path,
    *,
    tool_version: str,
) -> None:
    def _serialise_result(r: DomainResult) -> dict[str, Any]:
        return {
            "url":           r.url,
            "final_url":     r.final_url,
            "reachable":     r.reachable,
            "tls_warning":   r.tls_warning,
            "protocol":      r.protocol,
            "audited_at":    r.audited_at,
            "total_score":   r.total_score,
            "grade":         r.grade,
            "error_message": r.error_message,
            "headers": [
                {
                    "name":          h.name,
                    "display_name":  h.display_name,
                    "status":        h.status.value,
                    "raw_value":     h.raw_value,
                    "score_awarded": h.score_awarded,
                    "score_max":     h.score_max,
                    "recommendation": h.recommendation,
                    "details":       h.details,
                }
                for h in r.header_results
            ],
        }

    reachable = [r for r in results if r.reachable]
    avg_score = (
        round(sum(r.total_score for r in reachable) / len(reachable), 1)
        if reachable else 0.0
    )
    grade_dist: dict[str, int] = {g: 0 for g in "ABCDF"}
    for r in results:
        grade_dist[r.grade] = grade_dist.get(r.grade, 0) + 1

    payload = {
        "meta": {
            "tool_version": tool_version,
            "generated_at": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        },
        "summary": {
            "total_domains":      len(results),
            "reachable":          len(reachable),
            "unreachable":        len(results) - len(reachable),
            "average_score":      avg_score,
            "grade_distribution": grade_dist,
        },
        "results": [_serialise_result(r) for r in results],
    }

    output_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
