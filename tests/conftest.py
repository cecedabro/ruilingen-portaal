import os
import tempfile

# Must be set before the app is imported: the engine is created at import time.
_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["BASE_URL"] = "http://testserver"
os.environ["MAIL_BACKEND"] = "console"
os.environ["DEV_MODE"] = "true"  # console mail only counts as enabled in dev mode
os.environ["PLANNING_EMAIL"] = "planning@voorbeeld.nl"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import mail  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    mail.outbox.clear()
    yield


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


def make_user(name: str, **kw) -> User:
    with SessionLocal() as s:
        email = name.lower().replace(" ", ".") + "@voorbeeld.nl"
        user = User(name=name, email=email, **kw)
        s.add(user)
        s.commit()
        return user


def login(client: TestClient, user: User) -> TestClient:
    """Log a browser in as `user` with a one-time link (the way an admin would)."""
    from app.config import get_settings
    from app.services import logins

    with SessionLocal() as s:
        link = logins.make_link(s, get_settings(), s.get(User, user.id))
    path = link.removeprefix("http://testserver")
    r = client.post(path, data={"next": ""}, follow_redirects=False)
    assert r.status_code == 303
    mail.outbox.clear()
    return client


def join(client: TestClient, name: str) -> TestClient:
    from app.services import invites

    with SessionLocal() as s:
        code = invites.main_link(s).code
    r = client.post(f"/join/{code}", data={"name": name}, follow_redirects=False)
    assert r.status_code == 303, r.text
    return client


@pytest.fixture
def people():
    """Three logged-in colleagues, each with their own browser."""
    out = {}
    for name in ["Sanne de Vries", "Daan Bakker", "Noor Smit"]:
        user = make_user(name)
        out[name.split()[0].lower()] = (user, login(TestClient(app), user))
    return out
