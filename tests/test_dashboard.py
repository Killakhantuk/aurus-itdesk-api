from fastapi.testclient import TestClient
from main import app, DASHBOARD_PATH

client = TestClient(app)


def test_root_serves_dashboard_html():
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")


def test_dashboard_file_exists():
    assert DASHBOARD_PATH.is_file()


def test_dashboard_targets_the_real_endpoints():
    body = client.get("/").text
    assert '"/tickets"' in body
    assert "/tickets/escalate" in body


def test_dashboard_has_no_external_assets():
    body = client.get("/").text
    assert 'src="http' not in body
    assert 'href="http' not in body
    assert 'src="//' not in body
    assert "@import" not in body
    assert "cdn." not in body
