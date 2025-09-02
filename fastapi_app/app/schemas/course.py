from pydantic import BaseModel

class CourseForm(BaseModel):
    name: str
    semester: str
    year: int
