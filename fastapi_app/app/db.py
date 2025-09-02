import os
from sqlmodel import create_engine, Session
from .config import settings

# For Windows compatibility, construct an absolute path
# The current working directory is fastapi_app
db_path = os.path.abspath(os.path.join(os.getcwd(), settings.DATABASE_URL.split("///")[-1]))
DATABASE_URL = f"sqlite:///{db_path}"

engine = create_engine(DATABASE_URL, echo=True)

def get_session():
    with Session(engine) as session:
        yield session
