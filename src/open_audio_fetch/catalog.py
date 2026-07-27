"""Load and validate the source catalog — the project's center of gravity.

`catalog.json` is a community-contributable registry of *where free & legal
audio lives*. `catalog_schema.json` is the contract every entry must satisfy,
including the mandatory legality fields (a source without a license + a rights
link is rejected). To avoid the schema and the checker drifting apart, the
validator here is a small interpreter over the schema itself — it supports just
the JSON-Schema keywords the catalog uses, and reads all enums/patterns from the
schema file. `open-audio-fetch --validate-catalog` and CI both call `validate()`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

CATALOG_PATH = Path(__file__).with_name("catalog.json")
SCHEMA_PATH = Path(__file__).with_name("catalog_schema.json")

# JSON-Schema "type" -> Python type(s). int/bool kept distinct on purpose.
_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "null": type(None),
}


def load_catalog(path: Path | None = None) -> dict:
    with open(path or CATALOG_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def load_schema(path: Path | None = None) -> dict:
    with open(path or SCHEMA_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def _is_type(value, tname: str) -> bool:
    py = _TYPES[tname]
    if tname == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if tname == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, py)


def _validate(node: dict, schema: dict, root: dict, path: str, errors: list[str]):
    """Validate `node` against `schema` (a subset of JSON Schema), collecting
    human-readable errors with a JSON-pointer-ish `path`."""
    if "$ref" in schema:
        ref = schema["$ref"]
        target = root
        for part in ref.lstrip("#/").split("/"):
            target = target[part]
        _validate(node, target, root, path, errors)
        return

    # type (may be a string or a list of allowed types)
    if "type" in schema:
        types = schema["type"]
        types = [types] if isinstance(types, str) else types
        if not any(_is_type(node, t) for t in types):
            errors.append(f"{path}: expected type {types}, got {type(node).__name__}")
            return  # further checks assume the type held

    if "const" in schema and node != schema["const"]:
        errors.append(f"{path}: must equal {schema['const']!r}, got {node!r}")

    if "enum" in schema and node not in schema["enum"]:
        errors.append(f"{path}: {node!r} not in {schema['enum']}")

    if isinstance(node, str):
        pat = schema.get("pattern")
        if pat and not re.search(pat, node):
            errors.append(f"{path}: {node!r} does not match /{pat}/")
        if schema.get("format") == "uri" and "://" not in node:
            errors.append(f"{path}: {node!r} is not a URI")
        if "minLength" in schema and len(node) < schema["minLength"]:
            errors.append(f"{path}: shorter than minLength {schema['minLength']}")

    if isinstance(node, (int, float)) and not isinstance(node, bool):
        if "minimum" in schema and node < schema["minimum"]:
            errors.append(f"{path}: {node} < minimum {schema['minimum']}")

    if isinstance(node, list):
        if "minItems" in schema and len(node) < schema["minItems"]:
            errors.append(f"{path}: fewer than minItems {schema['minItems']}")
        if schema.get("uniqueItems") and len(node) != len({json.dumps(x, sort_keys=True) for x in node}):
            errors.append(f"{path}: items must be unique")
        item_schema = schema.get("items")
        if item_schema:
            for i, item in enumerate(node):
                _validate(item, item_schema, root, f"{path}[{i}]", errors)

    if isinstance(node, dict):
        props = schema.get("properties", {})
        for req in schema.get("required", []):
            if req not in node:
                errors.append(f"{path}: missing required field {req!r}")
        if schema.get("additionalProperties") is False:
            for key in node:
                if key not in props:
                    errors.append(f"{path}: unexpected field {key!r}")
        for key, subschema in props.items():
            if key in node:
                _validate(node[key], subschema, root, f"{path}.{key}", errors)


def validate(catalog: dict | None = None, schema: dict | None = None) -> list[str]:
    """Return a list of validation errors ([] means the catalog is valid).

    Enforces the schema (types, enums, patterns, required fields, the legality
    gate) plus one cross-entry rule the schema can't express: unique ids.
    """
    catalog = catalog if catalog is not None else load_catalog()
    schema = schema if schema is not None else load_schema()
    errors: list[str] = []
    _validate(catalog, schema, schema, "catalog", errors)

    seen: dict[str, int] = {}
    for i, src in enumerate(catalog.get("sources", [])):
        if isinstance(src, dict) and "id" in src:
            sid = src["id"]
            if sid in seen:
                errors.append(f"catalog.sources[{i}].id: duplicate id {sid!r}")
            seen[sid] = i
    return errors


# --- health-check diagnosis --------------------------------------------------

OK, WARN, FAIL = "OK", "WARN", "FAIL"


def diagnose(source: dict, robots_allows: bool, reachable: bool) -> tuple[str, str]:
    """Classify a live health-check of one source into (level, note).

    Pure so `--doctor`'s policy is unit-testable without the network. A source
    that ships a working adapter but is now blocked/unreachable is a FAIL; robots
    drift on a non-active source is a WARN.
    """
    active = source.get("adapter_status") in ("implemented", "experimental")
    claim = bool(source.get("robots_ok"))
    notes = []

    if robots_allows != claim:
        notes.append(
            f"robots now {'ALLOWS' if robots_allows else 'DENIES'} but catalog "
            f"says robots_ok={claim}"
        )
    if not robots_allows:
        # Blocked is only a failure for a source we claim to actively fetch.
        return (FAIL if active else WARN, "; ".join(notes) or "robots disallows")
    if not reachable:
        return (FAIL if active else WARN, "; ".join(notes + ["URL unreachable"]))
    if notes:
        return (WARN, "; ".join(notes))
    return (OK, "reachable; robots ok")


# --- rendered human view ----------------------------------------------------

_GROUPS = [
    ("Music", {"music", "classical", "remix", "samples", "sound-effects"}),
    ("Audiobooks & Classics", {"audiobooks", "classics", "poetry"}),
    ("Podcasts", {"podcasts"}),
    ("Educational & Historical", {"educational", "historical", "live-concerts"}),
    ("Aggregators & Indexes", {"index"}),
]
_MARK = {"implemented": "✓", "experimental": "⚑", "planned": "○", "index-only": "ⓘ"}
_REDIST = {"yes": "yes", "conditional": "conditional", "no": "personal-only", "mixed": "per-item"}


def _group_of(src: dict) -> str:
    cats = set(src.get("categories", []))
    for name, members in _GROUPS:
        if cats & members:
            return name
    return _GROUPS[-1][0]


def render_sites(catalog: dict | None = None) -> str:
    """Render SITES.md from the catalog — the single source of truth.

    Deterministic (sources sorted by id within a fixed group order) so a
    freshness test can assert the checked-in file matches byte for byte.
    """
    catalog = catalog if catalog is not None else load_catalog()
    sources = catalog["sources"]

    out: list[str] = []
    out.append("<!-- GENERATED FROM src/open_audio_fetch/catalog.json — DO NOT EDIT BY HAND.")
    out.append("     Regenerate with:  python3 scripts/gen_sites.py  -->")
    out.append("")
    out.append("# The Index of Free-Audio Sources")
    out.append("")
    out.append(
        "The human-readable view of the project's index. The machine-readable "
        "source of truth is\n[`catalog.json`](src/open_audio_fetch/catalog.json) "
        "(validated against [`catalog_schema.json`](src/open_audio_fetch/catalog_schema.json)); "
        "the live view is `python3 -m open_audio_fetch --catalog`."
    )
    out.append("")
    out.append(
        "Every source here offers audio **free for personal use** and its terms/robots "
        "permit fetching.\n**Redistribute** says whether you may re-share what you "
        "download: `yes` (PD/CC0/CC-BY), `conditional`\n(CC with NC/SA/ND terms), "
        "`personal-only` (e.g. podcasts), or `per-item` (varies)."
    )
    out.append("")
    out.append(
        "**Adapter**: ✓ implemented · ⚑ experimental (best-effort) · ○ planned · "
        "ⓘ index/aggregator."
    )
    out.append("")

    for group_name, _ in _GROUPS:
        rows = sorted(
            (s for s in sources if _group_of(s) == group_name),
            key=lambda s: s["id"],
        )
        if not rows:
            continue
        out.append(f"## {group_name}")
        out.append("")
        out.append("| Adapter | Source | License | Redistribute | Access |")
        out.append("|---|---|---|---|---|")
        for s in rows:
            mark = _MARK.get(s["adapter_status"], " ")
            name = f"[{s['name']}]({s['url']})"
            redist = _REDIST.get(s["redistributable"], s["redistributable"])
            out.append(
                f"| {mark} | {name} | {s['license']} | {redist} | {s['access']} |"
            )
        out.append("")

    counts = {}
    for s in sources:
        counts[s["adapter_status"]] = counts.get(s["adapter_status"], 0) + 1
    summary = ", ".join(f"{counts[k]} {k}" for k in sorted(counts))
    out.append("---")
    out.append("")
    out.append(f"**{len(sources)} sources** — {summary}.")
    out.append("")
    out.append(
        "Know a source we're missing? It must be **free & legal** (offered free, "
        "terms/robots permit fetching). See [CONTRIBUTING.md](CONTRIBUTING.md) — "
        "adding one is a small PR to `catalog.json`."
    )
    out.append("")
    return "\n".join(out)


# --- static website ---------------------------------------------------------

def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def render_html(catalog: dict | None = None) -> str:
    """Render the index as one self-contained HTML page (for GitHub Pages).

    Deterministic (sorted like SITES.md) so a freshness test can pin it. Pure
    string building — no external assets, works offline."""
    catalog = catalog if catalog is not None else load_catalog()
    sources = catalog["sources"]
    active = sum(1 for s in sources if s["adapter_status"] in ("implemented", "experimental"))

    rows = []
    for group_name, _ in _GROUPS:
        grp = sorted((s for s in sources if _group_of(s) == group_name), key=lambda s: s["id"])
        if not grp:
            continue
        rows.append(f'<h2>{_esc(group_name)}</h2>')
        rows.append('<table><thead><tr><th>Adapter</th><th>Source</th>'
                    '<th>License</th><th>Redistribute</th><th>Access</th></tr></thead><tbody>')
        for s in grp:
            mark = _MARK.get(s["adapter_status"], "&nbsp;")
            redist = _REDIST.get(s["redistributable"], s["redistributable"])
            cats = " ".join(sorted(s["categories"]))
            rows.append(
                f'<tr data-cats="{_esc(cats)}"><td class="mark">{mark}</td>'
                f'<td><a href="{_esc(s["url"])}">{_esc(s["name"])}</a></td>'
                f'<td>{_esc(s["license"])}</td><td>{_esc(redist)}</td>'
                f'<td>{_esc(s["access"])}</td></tr>'
            )
        rows.append('</tbody></table>')
    body = "\n".join(rows)

    return f"""<!doctype html>
<!-- GENERATED FROM src/open_audio_fetch/catalog.json — do not edit by hand.
     Regenerate: python3 scripts/gen_site.py -->
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>open-audio-fetch — index of free &amp; legal audio sources</title>
<style>
:root{{color-scheme:light dark}}
body{{font:16px/1.5 system-ui,sans-serif;max-width:64rem;margin:2rem auto;padding:0 1rem}}
h1{{margin-bottom:.2rem}} .sub{{opacity:.75;margin-top:0}}
table{{border-collapse:collapse;width:100%;margin:.5rem 0 2rem}}
th,td{{text-align:left;padding:.4rem .6rem;border-bottom:1px solid #8883}}
th{{font-size:.8rem;text-transform:uppercase;letter-spacing:.03em;opacity:.7}}
.mark{{font-size:1.1rem;width:2rem;text-align:center}}
a{{color:inherit}} code{{background:#8882;padding:.1rem .3rem;border-radius:.2rem}}
.legend{{font-size:.9rem;opacity:.8}}
</style></head><body>
<h1>open-audio-fetch</h1>
<p class="sub">A worldwide, community-maintained index of where <strong>free &amp; legal audio</strong> lives — and a polite tool to fetch it.</p>
<p class="legend"><strong>{len(sources)} sources</strong> ({active} with a working adapter). Adapter: ✓ implemented · ⚑ experimental · ○ planned · ⓘ index. <strong>Redistribute</strong>: <code>yes</code> PD/CC0/CC-BY · <code>conditional</code> CC terms · <code>personal-only</code> · <code>per-item</code>. Every source offers audio free for personal use and permits fetching.</p>
<p class="legend">Machine-readable: <a href="https://github.com/">catalog.json</a>. Add a source via a small PR — see CONTRIBUTING.md.</p>
{body}
<hr><p class="legend">Generated from <code>catalog.json</code> (CC0). Code MIT. The audio keeps each source's own license.</p>
</body></html>
"""
