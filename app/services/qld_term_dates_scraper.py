#!/usr/bin/env python3
"""
QLD Term Dates Scraper (clean rewrite)
-------------------------------------
Scrapes the Queensland Department of Education term dates from:
  https://education.qld.gov.au/about-us/calendar/term-dates

Outputs JSON to stdout by default, or to a file with --out path.
Optionally pretty-print with --pretty.

Usage:
  python qld_term_dates_scraper_clean.py --out term_dates.json --pretty

Requires: requests, beautifulsoup4
"""

import argparse
import json
import re
from datetime import datetime
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup, NavigableString, Tag

SOURCE_URL = "https://education.qld.gov.au/about-us/calendar/term-dates"

MONTHS = {
    "January": 1, "February": 2, "March": 3, "April": 4,
    "May": 5, "June": 6, "July": 7, "August": 8,
    "September": 9, "October": 10, "November": 11, "December": 12
}

TERM_LINE_RE = re.compile(
    r"Term\s+([1-4])\s*:\s*(.*?)\s+to\s+(.*?)\s*[—–-]\s*([0-9]+)\s*weeks?",
    re.IGNORECASE | re.DOTALL,
)

def normalize_text(s: str) -> str:
    """Normalize dash variants; keep newlines intact for multiline regex."""
    return s.replace("\u2014", "—").replace("\u2013", "–").replace("--", "—")

def parse_date(text: str, year: int) -> str:
    """
    Convert 'Tuesday 28 January' or '28 January' to 'YYYY-MM-DD'.
    """
    text = text.strip().replace("\xa0", " ")
    parts = text.split()
    # Drop weekday if present
    if parts and not parts[0][0].isdigit():
        parts = parts[1:]
    if len(parts) < 2:
        raise ValueError(f"Unrecognized date format: {text!r}")
    # Some pages might have '28 January' or '28 January 2025' (we ignore trailing year if present)
    day = int(re.sub(r"[^0-9]", "", parts[0]))
    month_name = parts[1]
    month = MONTHS.get(month_name)
    if not month:
        raise ValueError(f"Unknown month in {text!r}")
    return f"{year:04d}-{month:02d}-{day:02d}"

def get_last_updated(soup: BeautifulSoup) -> Optional[str]:
    text_all = soup.get_text(" ", strip=True)
    m = re.search(r"Last updated\s+([0-9]{1,2}\s+\w+\s+[0-9]{4})", text_all, flags=re.I)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%d %B %Y").date().isoformat()
    except Exception:
        return None

def collect_block_text_until_next_heading(start: Tag) -> str:
    """Collect concatenated text from `start` until the next heading tag."""
    collected: List[str] = []
    for node in start.next_elements:
        if isinstance(node, Tag) and re.match(r"^h[1-6]$", node.name or "", flags=re.I):
            break
        if isinstance(node, Tag):
            t = node.get_text(" ", strip=True)
        elif isinstance(node, NavigableString):
            t = str(node).strip()
        else:
            continue
        if t:
            collected.append(t)
    block = "\n".join(collected)
    return normalize_text(block)

def extract_terms_from_year_block(year: int, heading: Tag, all_headings: List[Tag]) -> List[Dict]:
    """
    Given a year heading, gather text until next heading and parse all 'Term X: ...' lines.
    Also tries to locate a 'Queensland term dates' subheading; if found, starts from there instead.
    """
    # Find 'Queensland term dates' subheading under this year; else start at the year heading itself
    anchor: Optional[Tag] = None
    for node in heading.next_elements:
        if isinstance(node, Tag) and re.match(r"^h[1-6]$", node.name or "", flags=re.I):
            # If this is another heading at same or higher level (any heading), stop search
            if node is not heading:
                break
        if isinstance(node, Tag) and node.name.lower().startswith("h"):
            if "Queensland term dates" in node.get_text(" ", strip=True):
                anchor = node
                break
    if anchor is None:
        anchor = heading

    text_block = collect_block_text_until_next_heading(anchor)
    terms: List[Dict] = []
    for m in TERM_LINE_RE.finditer(text_block):
        num = int(m.group(1))
        start_text = m.group(2).strip()
        end_text = m.group(3).strip()
        weeks = int(m.group(4))
        try:
            start_iso = parse_date(start_text, year)
            end_iso = parse_date(end_text, year)
        except Exception:
            start_iso = None
            end_iso = None
        terms.append({
            "number": num,
            "name": f"Term {num}",
            "start_date": start_iso,
            "end_date": end_iso,
            "weeks": weeks,
            "raw": f"Term {num}: {start_text} to {end_text}—{weeks} weeks",
        })
    # Ensure ordered and unique by term number
    uniq: Dict[int, Dict] = {}
    for t in terms:
        uniq[t["number"]] = t
    return [uniq[n] for n in sorted(uniq.keys())]

def scrape_term_dates(url: str = SOURCE_URL) -> Dict:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; QLDTermDatesBot/2.0; +https://education.qld.gov.au/)"
    }
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    last_updated = get_last_updated(soup)

    # Gather all headings that contain a year like 2025, 2026, etc.
    headings = soup.find_all(re.compile(r"^h[1-6]$"))
    years_data: List[Dict] = []

    for h in headings:
        txt = h.get_text(" ", strip=True)
        ym = re.search(r"\b(20[0-9]{2})\b", txt)
        if not ym:
            continue
        year = int(ym.group(1))
        terms = extract_terms_from_year_block(year, h, headings)
        if terms:
            years_data.append({"year": year, "terms": terms})

    # Fallback: single inferred year if none captured properly
    if not years_data:
        txt_all = soup.get_text("\n", strip=True)
        ym = re.search(r"\b(20[0-9]{2})\b", txt_all)
        inferred_year = int(ym.group(1)) if ym else datetime.utcnow().year
        block = normalize_text(txt_all)
        terms = []
        for m in TERM_LINE_RE.finditer(block):
            num = int(m.group(1))
            start_text = m.group(2).strip()
            end_text = m.group(3).strip()
            weeks = int(m.group(4))
            try:
                start_iso = parse_date(start_text, inferred_year)
                end_iso = parse_date(end_text, inferred_year)
            except Exception:
                start_iso = None
                end_iso = None
            terms.append({
                "number": num,
                "name": f"Term {num}",
                "start_date": start_iso,
                "end_date": end_iso,
                "weeks": weeks,
                "raw": f"Term {num}: {start_text} to {end_text}—{weeks} weeks",
            })
        if terms:
            years_data.append({"year": inferred_year, "terms": sorted(terms, key=lambda t: t["number"])})

    return {
        "source": url,
        "last_updated": last_updated,
        "years": years_data,
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", help="Path to write JSON. If omitted, prints to stdout.")
    ap.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    args = ap.parse_args()

    data = scrape_term_dates(SOURCE_URL)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2 if args.pretty else None)
        print(f"Wrote {args.out}")
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2 if args.pretty else None))

if __name__ == "__main__":
    main()

