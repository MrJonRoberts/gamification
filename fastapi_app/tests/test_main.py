import pytest
from httpx import AsyncClient, ASGITransport
from sqlmodel import Session, SQLModel, create_engine
from app.main import app
from app.db import get_session
from app.models.user import User

DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

@pytest.fixture(name="session")
def session_fixture():
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)

@pytest.fixture(name="client")
def client_fixture(session: Session):
    def get_session_override():
        yield session

    app.dependency_overrides[get_session] = get_session_override
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    yield client
    app.dependency_overrides.clear()

@pytest.mark.asyncio
async def test_read_main(client: AsyncClient):
    response = await client.get("/")
    assert response.status_code == 200

@pytest.mark.asyncio
async def test_profile_unauthenticated(client: AsyncClient):
    response = await client.get("/profile")
    assert response.status_code == 401

@pytest.mark.asyncio
async def test_login_and_profile(session: Session, client: AsyncClient):
    # Create a test user
    user = User(
        first_name="Test",
        last_name="User",
        email="test@example.com",
    )
    user.set_password("password")
    session.add(user)
    session.commit()

    # Test login
    response = await client.post("/auth/login", data={"email": "test@example.com", "password": "password"}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/profile"

    # Follow the redirect to the profile page
    profile_response = await client.get(response.headers["location"])
    assert profile_response.status_code == 200
    assert "Test" in profile_response.text
    assert "User" in profile_response.text
