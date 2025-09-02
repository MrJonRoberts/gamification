import calendar
from datetime import date, timedelta

def generate_calendar_data(year: int, month: int):
    cal = calendar.Calendar()
    month_days = cal.itermonthdates(year, month)

    weeks = []
    current_week = []

    for day_date in month_days:
        current_week.append({
            "date": day_date,
            "in_month": day_date.month == month,
            "is_today": day_date == date.today(),
            "lesson": None, # This will be populated by the route
        })
        if len(current_week) == 7:
            weeks.append(current_week)
            current_week = []

    if current_week:
        weeks.append(current_week)

    return weeks
