#!/usr/bin/env python3
"""
QLD Term Dates Scraper — Extended (null-safe)
---------------------------------------------
Scrapes the main Term Dates page and follows "Future school dates" (and "Past" if present).
Extracts ONLY the "Queensland term dates" (Terms 1–4) per year.

Null-safety improvements:
- Removes zero-width characters and NBSPs
- Deduplicates patterns like "Term 2: Term 2:" that appear due to nested tags
- Robust date parsing that ignores spurious tokens and respects explicit years
"""

import argparse
import json
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, NavigableString, Tag

SOURCE_URL = "https://education.qld.gov.au/about-us/calendar/term-dates"

MONTHS = {
    "January": 1, "February": 2, "March": 3, "April": 4,
    "May": 5, "June": 6, "July": 7, "August": 8,
    "September": 9, "October": 10, "November": 11, "December": 12
}

WEEKDAYS = {
    "monday","tuesday","wednesday","thursday","friday","saturday","sunday"
}

TERM_LINE_RE = re.compile(
    r"Term\s+([1-4])\s*:\s*(.*?)\s+to\s+(.*?)\s*[—–-]\s*([0-9]+)\s*weeks?",
    re.IGNORECASE | re.DOTALL,
)

STOP_SECTION_TITLES = {
    "staff professional development days",
    "school holidays",
}

ZERO_WIDTH_RE = re.compile(r"[\u200B\u200C\u200D\u2060\ufeff]")
NBSP_RE = re.compile(r"\u00A0")

def clean_block(text: str) -> str:
    # Normalize hyphens/dashes and strip zero-width + NBSPs
    text = NBSP_RE.sub(" ", text)
    text = ZERO_WIDTH_RE.sub("", text)
    text = text.replace("\u2014", "—").replace("\u2013", "–").replace("--", "—")
    # Deduplicate "Term X: Term X:" or "Term X\nTerm X\n:" patterns
    text = re.sub(r"(Term\s+[1-4]\s*:\s*)(?:Term\s+[1-4]\s*:\s*)+", r"\1", text, flags=re.I)
    text = re.sub(r"(Term\s+[1-4])\s*\n\s*\1\s*:", r"\1: ", text, flags=re.I)
    # Collapse weird "Term 2:  Term 2:" with extra spaces/newlines
    text = re.sub(r"(Term\s+[1-4]\s*:\s*)\s*(?:\bTerm\s+[1-4]\s*:\s*)+", r"\1", text, flags=re.I)
    return text

DATE_RE = re.compile(
    r"(?:(?:Mon|Tues|Wed|Thu|Thur|Fri|Sat|Sun|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+)?"
    r"(\d{1,2})\s+([A-Za-z]+)(?:\s+(\d{4}))?",
    re.IGNORECASE
)

def parse_date(text: str, year_context: int) -> Optional[str]:
    """
    Parse variants like 'Tuesday 28 January' or '28 January 2027'.
    If a year is present in the text, it overrides the year_context (handles cross-year Term 4).
    """
    # Remove any stray 'Term X:' that leaked into date text
    text = re.sub(r"^Term\s+[1-4]\s*:\s*", "", text.strip(), flags=re.I)
    text = ZERO_WIDTH_RE.sub("", text).replace("\u00A0", " ")
    m = DATE_RE.search(text)
    if not m:
        return None
    day = int(m.group(1))
    month_name = m.group(2).strip()
    year = int(m.group(3)) if m.group(3) and m.group(3).isdigit() else year_context
    # Normalise month (title case)
    month_name = month_name[:1].upper() + month_name[1:].lower()
    month = MONTHS.get(month_name)
    if not month:
        return None
    try:
        return f"{year:04d}-{month:02d}-{day:02d}"
    except Exception:
        return None

def get_last_updated(soup: BeautifulSoup) -> Optional[str]:
    text_all = soup.get_text(" ", strip=True)
    m = re.search(r"Last updated\s+([0-9]{1,2}\s+\w+\s+[0-9]{4})", text_all, flags=re.I)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%d %B %Y").date().isoformat()
    except Exception:
        return None

def heading_text(tag: Tag) -> str:
    return tag.get_text(" ", strip=True) if isinstance(tag, Tag) else ""

def find_anchor_after_year(heading: Tag) -> Optional[Tag]:
    """
    Within the siblings after a year heading, find the 'Queensland term dates' subheading.
    If not found before the next year heading, return the year heading itself as anchor.
    """
    for sib in heading.next_siblings:
        if isinstance(sib, Tag) and re.match(r"^h[1-6]$", sib.name or "", flags=re.I):
            # If next year encountered, stop search
            if re.search(r"\b20[0-9]{2}\b", heading_text(sib)):
                return heading  # fallback
            # Otherwise check for target subheading
            if "queensland term dates" in heading_text(sib).lower():
                return sib
    return heading  # fallback

def collect_block_text_until_stop(anchor: Tag) -> str:
    """
    Collect text from the anchor until the next heading OR a heading with a stop title.
    """
    collected: List[str] = []
    for node in anchor.next_elements:
        if isinstance(node, Tag) and re.match(r"^h[1-6]$", node.name or "", flags=re.I):
            title = heading_text(node).lower()
            if any(stop in title for stop in STOP_SECTION_TITLES) or "queensland term dates" not in title:
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
    return clean_block(block)

def extract_terms_for_year(year: int, heading: Tag) -> List[Dict]:
    """
    Get terms for a given year heading by locating the 'Queensland term dates' anchor
    and parsing its block until the next heading or stop section.
    """
    anchor = find_anchor_after_year(heading)
    block_text = collect_block_text_until_stop(anchor)
    terms: List[Dict] = []
    for m in TERM_LINE_RE.finditer(block_text):
        num = int(m.group(1))
        start_text = m.group(2).strip()
        end_text = m.group(3).strip()
        weeks = int(m.group(4))
        start_iso = parse_date(start_text, year)
        end_iso = parse_date(end_text, year)
        terms.append({
            "number": num,
            "name": f"Term {num}",
            "start_date": start_iso,
            "end_date": end_iso,
            "weeks": weeks,
            "raw": f"Term {num}: {start_text} to {end_text}—{weeks} weeks",
        })
    # Deduplicate by number and return in order
    by_num: Dict[int, Dict] = {}
    for t in terms:
        by_num[t["number"]] = t
    return [by_num[n] for n in sorted(by_num.keys())]

def parse_years_from_page(html: str) -> Tuple[Optional[str], Dict[int, List[Dict]]]:
    soup = BeautifulSoup(html, "html.parser")
    last_updated = get_last_updated(soup)
    years_map: Dict[int, List[Dict]] = {}

    headings = soup.find_all(re.compile(r"^h[1-6]$"))
    for h in headings:
        txt = heading_text(h)
        ym = re.search(r"\b(20[0-9]{2})\b", txt)
        if not ym:
            continue
        year = int(ym.group(1))
        terms = extract_terms_for_year(year, h)
        if terms:
            years_map[year] = terms

    # Global fallback (rare)
    if not years_map:
        txt_all = clean_block(soup.get_text("\n", strip=True))
        ym = re.search(r"\b(20[0-9]{2})\b", txt_all)
        if ym:
            inferred_year = int(ym.group(1))
            terms = []
            for m in TERM_LINE_RE.finditer(txt_all):
                num = int(m.group(1))
                start_text = m.group(2).strip()
                end_text = m.group(3).strip()
                weeks = int(m.group(4))
                start_iso = parse_date(start_text, inferred_year)
                end_iso = parse_date(end_text, inferred_year)
                terms.append({
                    "number": num,
                    "name": f"Term {num}",
                    "start_date": start_iso,
                    "end_date": end_iso,
                    "weeks": weeks,
                    "raw": f"Term {num}: {start_text} to {end_text}—{weeks} weeks",
                })
            if terms:
                years_map[inferred_year] = sorted(terms, key=lambda t: t["number"])

    return last_updated, years_map

def find_related_links(html: str, base_url: str) -> Dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    out = {}
    for a in soup.find_all("a", href=True):
        text = a.get_text(" ", strip=True).lower()
        if "future school dates" in text:
            out["future"] = urljoin(base_url, a["href"])
        elif "past school dates" in text or "previous school dates" in text:
            out["past"] = urljoin(base_url, a["href"])
    return out

def scrape(include_future: bool = True, include_past: bool = True) -> Dict:
    sess = requests.Session()
    headers = {"User-Agent": "Mozilla/5.0 (compatible; QLDTermDatesBot/5.0)"}

    # Main page
    r = sess.get(SOURCE_URL, headers=headers, timeout=30)
    r.raise_for_status()
    main_html = r.text

    last_updated, years_all = parse_years_from_page(main_html)

    # Discover related pages
    links = find_related_links(main_html, SOURCE_URL)

    # Future page(s)
    if include_future and "future" in links:
        rf = sess.get(links["future"], headers=headers, timeout=30)
        rf.raise_for_status()
        lu_fut, years_fut = parse_years_from_page(rf.text)
        if lu_fut and (not last_updated or lu_fut > last_updated):
            last_updated = lu_fut
        years_all.update(years_fut)

    # Past page(s)
    if include_past and "past" in links:
        rp = sess.get(links["past"], headers=headers, timeout=30)
        rp.raise_for_status()
        lu_past, years_past = parse_years_from_page(rp.text)
        if lu_past and (not last_updated or lu_past > last_updated):
            last_updated = lu_past
        years_all.update(years_past)

    # Assemble sorted years
    years_list = [{"year": y, "terms": sorted(terms, key=lambda t: t["number"])} for y, terms in years_all.items()]
    years_list.sort(key=lambda y: y["year"])

    return {
        "source": SOURCE_URL,
        "last_updated": last_updated,
        "years": years_list,
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", help="Path to write JSON. If omitted, prints to stdout.")
    ap.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    ap.add_argument("--no-future", action="store_true", help="Do not follow 'Future school dates'")
    ap.add_argument("--no-past", action="store_true", help="Do not follow 'Past school dates'")
    args = ap.parse_args()

    data = scrape(include_future=not args.no_future, include_past=not args.no_past)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2 if args.pretty else None)
        print(f"Wrote {args.out}")
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2 if args.pretty else None))

if __name__ == "__main__":
    main()

