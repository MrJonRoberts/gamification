from datetime import date
from typing import Optional
from pydantic import BaseModel

class TermForm(BaseModel):
    start_date: Optional[date] = None
    end_date: Optional[date] = None

class AcademicYearForm(BaseModel):
    year: int
    term1: TermForm
    term2: TermForm
    term3: TermForm
    term4: TermForm
