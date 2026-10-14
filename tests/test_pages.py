"""Page-level behaviour: theme switch, prefetching."""

from datetime import timedelta

from tests.helpers import (
    TODAY,
)


def test_theme_switch_without_js(people):
    _, client = people["sanne"]
    assert 'data-theme="light"' in client.get("/aangeboden").text
    r = client.post("/theme", data={"next": "/gezocht"}, follow_redirects=False)
    assert r.headers["location"] == "/gezocht"
    assert 'data-theme="dark"' in client.get("/aangeboden").text
    client.post("/theme", data={"next": "/"})
    assert 'data-theme="light"' in client.get("/aangeboden").text


def test_prefetch_does_not_eat_flash_messages(people):
    _, d = people["daan"]
    day = (TODAY + timedelta(days=2)).isoformat()
    data = {"kind": "offer", "day": day, "code": "H", "start": "18:00", "end": "23:00"}
    d.post("/plaatsen", data=data, follow_redirects=False)  # flash set, not shown yet
    d.get("/gezocht", headers={"X-Prefetch": "1"})
    assert "Geplaatst." in d.get("/aangeboden").text
