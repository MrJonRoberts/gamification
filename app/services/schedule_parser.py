import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from typing import List, Dict, Any, Optional

TERM_DATES_URL = "https://education.qld.gov.au/about-us/calendar/term-dates"
PUBLIC_HOLIDAYS_URL = "https://www.qld.gov.au/recreation/travel/holidays/public"

def parse_date(date_str: str, year: int) -> Optional[datetime]:
    """Parses date like 'Tuesday 27 January' or 'Thursday 2 April' for a given year."""
    # Remove day of week
    parts = date_str.split()
    if len(parts) >= 3:
        # Expected: ['Tuesday', '27', 'January']
        day = parts[1]
        month = parts[2]
        # Clean up day (might have 'st', 'nd', 'rd', 'th')
        day = re.sub(r'(\d+)(st|nd|rd|th)', r'\1', day)
        try:
            dt_str = f"{day} {month} {year}"
            return datetime.strptime(dt_str, "%d %B %Y")
        except ValueError:
            return None
    return None

def fetch_term_dates(year: int, url: str = TERM_DATES_URL) -> List[Dict[str, Any]]:
    response = requests.get(url)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')

    full_text = soup.get_text(separator=" ")

    # Look for "Queensland term dates"
    section_matches = list(re.finditer(r"Queensland term dates", full_text))
    relevant_text = ""
    for sm in section_matches:
        # Check if the year is mentioned shortly before this section
        preceding = full_text[max(0, sm.start()-200):sm.start()]
        if str(year) in preceding:
            # Found the correct section for the year
            section_start = sm.end()
            # Look for the next major heading or section
            next_sec = re.search(r"Staff professional development days|School holidays|Future school dates", full_text[section_start:])
            section_end = section_start + next_sec.start() if next_sec else len(full_text)
            relevant_text = full_text[section_start:section_end]
            break

    if not relevant_text:
        # Fallback: search anywhere for "Term X: ... to ..." and use the ones that fit the year if they aren't too many
        relevant_text = full_text

    pattern = r"Term\s+(\d)\s*:\s*(.*?)\s+to\s+(.*?)(?:—| - |$|\n)"
    matches = list(re.finditer(pattern, relevant_text))

    terms = []
    seen_terms = set()
    for match in matches:
        term_num = int(match.group(1))
        if term_num in seen_terms:
            continue
        start_str = match.group(2).strip()
        end_str = match.group(3).strip()

        start_date = parse_date(start_str, year)
        end_date = parse_date(end_str, year)

        if start_date and end_date:
            terms.append({
                "number": term_num,
                "name": f"Term {term_num}",
                "start_date": start_date.date(),
                "end_date": end_date.date()
            })
            seen_terms.add(term_num)

    return sorted(terms, key=lambda x: x['number'])

def fetch_public_holidays(year: int, url: str = PUBLIC_HOLIDAYS_URL) -> List[Dict[str, Any]]:
    response = requests.get(url)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')

    holidays = []

    table = soup.find('table') # Usually the first table
    if not table:
        return []

    headers = [th.get_text().strip() for th in table.find_all('th')]
    # Find which column corresponds to the requested year
    year_col_idx = -1
    for i, h in enumerate(headers):
        if str(year) in h:
            year_col_idx = i
            break

    if year_col_idx == -1:
        # Maybe the year is in the first row of tbody
        rows = table.find_all('tr')
        if rows:
            first_row_cells = rows[0].find_all(['td', 'th'])
            for i, cell in enumerate(first_row_cells):
                if str(year) in cell.get_text():
                    year_col_idx = i
                    break

    if year_col_idx == -1:
        return []

    for row in table.find_all('tr')[1:]: # Skip header
        cells = row.find_all(['td', 'th'])
        if len(cells) > year_col_idx:
            holiday_name = cells[0].get_text(separator=" ").strip()
            # Remove footnotes like ^1, ^2 or just trailing digits
            holiday_name = re.sub(r'\^\d+', '', holiday_name)
            holiday_name = re.sub(r'\d+$', '', holiday_name)
            # Remove "Other show holidays" if it got sucked in
            holiday_name = holiday_name.replace("Other show holidays", "").strip()
            # Remove extra spaces
            holiday_name = re.sub(r'\s+', ' ', holiday_name).strip()

            date_text = cells[year_col_idx].get_text(separator=" ").strip()
            # Date text can be "Monday 26 January" or "Friday 25 December and Monday 27 December"

            # Split by 'and' to handle multiple dates for one holiday
            date_parts = re.split(r'\s+and\s+', date_text)
            for part in date_parts:
                # Part might be "Monday 26 January"
                # Some parts might be just "Monday 27 December"
                # Some might have extra text like "6pm to midnight"

                # Try to extract date
                # Use a more generic parser or reuse parse_date
                dt = parse_holiday_date(part, year)
                if dt:
                    holidays.append({
                        "name": holiday_name,
                        "date": dt.date()
                    })

    return holidays

def parse_holiday_date(text: str, year: int) -> Optional[datetime]:
    # text could be "Thursday 1 January" or "24 December"
    # Clean up
    text = re.sub(r'\(.*?\)', '', text) # remove (24 December)
    text = re.sub(r'\d+pm to midnight', '', text)
    # Remove day of week if present at start
    text = re.sub(r'^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+', '', text, flags=re.IGNORECASE)
    text = text.strip()

    # Try "%d %B" (e.g. "1 January" or "24 December")
    match = re.search(r'(\d+)\s+([a-zA-Z]+)', text)
    if match:
        day = match.group(1)
        month = match.group(2)
        try:
            return datetime.strptime(f"{day} {month} {year}", "%d %B %Y")
        except ValueError:
            pass

    return None
