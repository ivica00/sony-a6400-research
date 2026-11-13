#!/usr/bin/env python3
"""Extract the published "Benefits and Improvements" text from Sony firmware pages.

The support pages return 403 to a plain HTTP client, so this runs through a *browser* the
operator already has open and attached (see the repository's browser tooling); nothing is
posted, no account is used and no page is modified.  The tool's job is only to turn what the
page shows into a stable JSON file that a later reader can compare against.

Usage::

    python3 -I tools/research/patch_notes.py --pages docs/evidence/cross_model/patch-pages.tsv \
        --out patch-notes.json

Input TSV: ``model<TAB>firmware_page_url``.  Output JSON::

    {"<model>": {"page": "<url>", "text": "<Benefits and Improvements>...",
                 "versions": [{"version": "4.00", "date": "2021-03-10"}, ...]}}

The extraction is deliberately dumb: it takes the page's own text block and then parses it.
It never synthesises a version or a date that the page does not print.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

#: The section heading the support pages use.  Both spellings occur; either ends the block.
START_MARKERS = ("Benefits and Improvements",)

VERSION_RE = re.compile(r"Ver\.\s*(\d+(?:\.\d+)?)\s*\((\d{1,2}-\d{1,2}-\d{4})\)")
NAME_RE = re.compile(r"Name:\s*(Update_[A-Za-z0-9]+\.exe)")
BLOCK_CHARS = 12000
#: One expanded version entry is a few hundred to a couple of thousand characters.
ENTRY_CHARS = 2500


def _run(session: str, *args: str, timeout: int = 120) -> str:
    """One browser command.  ``AGENT_BROWSER_CDP`` supplies the DevTools endpoint of the
    operator's browser, which is what makes the read work where a plain HTTP client is 403."""
    command = ["agent-browser", "--session", session]
    cdp = os.environ.get("AGENT_BROWSER_CDP")
    if cdp:
        command += ["--cdp", cdp]
    proc = subprocess.run(command + list(args),
                          capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"agent-browser {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def _eval(session: str, js: str) -> str:
    out = _run(session, "eval", js)
    if out.startswith('"') and out.endswith('"'):
        try:
            return json.loads(out)
        except json.JSONDecodeError:
            pass
    return out


def read_page(session: str, url: str, settle: float = 3.0) -> dict:
    _run(session, "tab", "new", url)
    time.sleep(settle)
    # open the collapsed history if the page has one; absence is not an error
    _eval(session, "(()=>{const a=Array.from(document.querySelectorAll('a,button'))"
                   ".find(e=>/Previous Benefits|View previous benefits/i.test(e.textContent));"
                   "if(a){a.click();return 1}return 0})()")
    time.sleep(1.5)
    text = _eval(session, "(()=>{const t=document.body.innerText;"
                          "for(const m of " + json.dumps(list(START_MARKERS)) + "){const i=t.indexOf(m);"
                          f"if(i>=0)return t.slice(i,i+{BLOCK_CHARS})}}return ''}})()")
    # Some pages list the previous versions as links that expand one entry at a time.  Every
    # such link is opened and its text appended, so a page that only shows the newest entry on
    # arrival still yields its full history.  Nothing is invented: an entry with no text is
    # recorded with an empty body rather than filled in.
    labels = _eval(session, "(()=>{const o=[];document.querySelectorAll('a,button')"
                            ".forEach(e=>{const t=e.textContent.trim();"
                            "if(/^Ver\\.\\s*\\d+\\.\\d+\\s*\\(/.test(t)&&t.length<40)o.push(t)});"
                            "return JSON.stringify([...new Set(o)])})()")
    try:
        wanted = json.loads(labels) if isinstance(labels, str) else list(labels)
    except json.JSONDecodeError:
        wanted = []
    entries: list[dict] = []
    for label in wanted:
        body = _eval(session, "(()=>{const el=Array.from(document.querySelectorAll('a,button'))"
                              ".find(e=>e.textContent.trim()===" + json.dumps(label) + ");"
                              "if(!el)return '';el.click();const t=document.body.innerText;"
                              "const i=t.indexOf(" + json.dumps(label) + ");"
                              f"return i>=0?t.slice(i,i+{ENTRY_CHARS}):''}})()")
        time.sleep(0.4)
        found = VERSION_RE.match(label) or VERSION_RE.search(label + " ()")
        parts = label.split()
        entries.append({
            "label": label,
            "version": parts[1] if len(parts) > 1 else None,
            "text": body,
            "length": len(body),
        })
    versions = [{"version": v, "date": d} for v, d in VERSION_RE.findall(text)]
    if not versions:
        versions = [{"version": e["version"], "date": None} for e in entries if e["version"]]
    name = NAME_RE.search(text)
    return {
        "page": url,
        "text": text,
        "versions": versions,
        "entries": entries,
        "updater_name": name.group(1) if name else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pages", type=Path, required=True, help="model<TAB>url listing")
    parser.add_argument("--out", type=Path, required=True, help="destination JSON")
    parser.add_argument("--session", default="pi-patch-notes",
                        help="browser session name, so this never touches another agent's tab")
    args = parser.parse_args(argv)

    rows = [line.split("\t") for line in args.pages.read_text().splitlines() if line.strip()]
    if not rows or rows[0][0] != "model":
        print("pages file must start with a 'model<TAB>firmware_page' header", file=sys.stderr)
        return 2

    result: dict[str, dict] = {}
    for model, *_rest in rows[1:]:
        if not _rest or not _rest[0].startswith("http"):
            print(f"SKIP {model}: no page url", file=sys.stderr)
            continue
        try:
            entry = read_page(args.session, _rest[0])
        except (RuntimeError, subprocess.TimeoutExpired) as exc:
            print(f"FAIL {model}: {exc}", file=sys.stderr)
            result[model] = {"page": _rest[0], "error": str(exc), "text": "", "versions": []}
            continue
        result[model] = entry
        print(f"{model:12s} versions={len(entry['versions']):2d} "
              f"bytes={len(entry['text']):5d} updater={entry['updater_name']}")

    args.out.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    print(f"wrote {args.out}", file=sys.stderr)
    return 0 if all("error" not in v for v in result.values()) else 3


if __name__ == "__main__":
    sys.exit(main())
