import store as store_module
from fastapi.testclient import TestClient

from main import app, store

client = TestClient(app)


def test_create_ticket():
    resp = client.post("/tickets", json={
        "title": "Test ticket",
        "description": "A test description",
        "priority": "medium",
    })
    assert resp.status_code == 201
    assert resp.json()["status"] == "open"


def test_list_tickets():
    resp = client.get("/tickets")
    assert resp.status_code == 200
    assert len(resp.json()) > 0


def test_get_ticket():
    ticket_id = client.post("/tickets", json={
        "title": "Get test", "description": "desc", "priority": "low"
    }).json()["id"]
    resp = client.get(f"/tickets/{ticket_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == ticket_id


def test_get_ticket_not_found():
    assert client.get("/tickets/doesnotexist").status_code == 404


def test_update_ticket_status():
    ticket_id = client.post("/tickets", json={
        "title": "Update test", "description": "desc", "priority": "high"
    }).json()["id"]
    resp = client.patch(f"/tickets/{ticket_id}", json={"status": "in_progress"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "in_progress"


def test_delete_ticket():
    ticket_id = client.post("/tickets", json={
        "title": "Delete test", "description": "desc", "priority": "low"
    }).json()["id"]
    assert client.delete(f"/tickets/{ticket_id}").status_code == 204
    assert client.get(f"/tickets/{ticket_id}").status_code == 404


def test_filter_by_status():
    resp = client.get("/tickets?status=open")
    assert resp.status_code == 200
    assert all(t["status"] == "open" for t in resp.json())


# --- POST /tickets/escalate ---


def _drain_eligible_tickets():
    """Escalate everything currently eligible to keep assertions isolated."""
    client.post("/tickets/escalate")


def _create_escalation_ticket(monkeypatch, priority="critical", **overrides):
    """Create an open ticket whose SLA deadline passed about two hours ago."""
    monkeypatch.setitem(store_module._SLA_HOURS, priority, -2)
    payload = {"title": "Escalation test", "description": "desc", "priority": priority}
    payload.update(overrides)
    return client.post("/tickets", json=payload).json()


def test_escalate_overdue_critical_unassigned_ticket(monkeypatch):
    _drain_eligible_tickets()
    created = _create_escalation_ticket(monkeypatch)

    resp = client.post("/tickets/escalate")

    assert resp.status_code == 200
    escalated = resp.json()
    assert [t["id"] for t in escalated] == [created["id"]]
    ticket = escalated[0]
    assert ticket["status"] == "escalated"
    # Only status and updated_at change; every other field stays untouched.
    for field in ("title", "description", "priority", "assignee",
                  "created_at", "sla_deadline"):
        assert ticket[field] == created[field]
    assert ticket["updated_at"] != created["updated_at"]


def test_escalate_returns_tickets_newest_first(monkeypatch):
    _drain_eligible_tickets()
    older = _create_escalation_ticket(monkeypatch, title="Older breached ticket")
    newer = _create_escalation_ticket(monkeypatch, title="Newer breached ticket")

    resp = client.post("/tickets/escalate")

    assert resp.status_code == 200
    assert [t["id"] for t in resp.json()] == [newer["id"], older["id"]]


def test_escalate_skips_non_critical_ticket(monkeypatch):
    _drain_eligible_tickets()
    ticket = _create_escalation_ticket(monkeypatch, priority="high")

    resp = client.post("/tickets/escalate")

    assert resp.status_code == 200
    assert ticket["id"] not in [t["id"] for t in resp.json()]
    assert client.get(f"/tickets/{ticket['id']}").json()["status"] == "open"


def test_escalate_skips_assigned_ticket(monkeypatch):
    _drain_eligible_tickets()
    ticket = _create_escalation_ticket(monkeypatch, assignee="eng-support@aurus.com")

    resp = client.post("/tickets/escalate")

    assert resp.status_code == 200
    assert ticket["id"] not in [t["id"] for t in resp.json()]
    assert client.get(f"/tickets/{ticket['id']}").json()["status"] == "open"


def test_escalate_treats_blank_assignee_as_unassigned(monkeypatch):
    _drain_eligible_tickets()
    created = _create_escalation_ticket(monkeypatch, assignee="   ")

    resp = client.post("/tickets/escalate")

    assert resp.status_code == 200
    escalated = {t["id"]: t for t in resp.json()}
    assert created["id"] in escalated
    assert escalated[created["id"]]["status"] == "escalated"


def test_escalate_skips_ticket_not_in_open_status(monkeypatch):
    _drain_eligible_tickets()
    created = _create_escalation_ticket(monkeypatch)
    client.patch(f"/tickets/{created['id']}", json={"status": "in_progress"})

    resp = client.post("/tickets/escalate")

    assert resp.status_code == 200
    assert created["id"] not in [t["id"] for t in resp.json()]
    assert client.get(f"/tickets/{created['id']}").json()["status"] == "in_progress"


def test_escalate_skips_ticket_still_within_sla():
    _drain_eligible_tickets()
    created = client.post("/tickets", json={
        "title": "Within SLA", "description": "desc", "priority": "critical",
    }).json()

    resp = client.post("/tickets/escalate")

    assert resp.status_code == 200
    assert created["id"] not in [t["id"] for t in resp.json()]
    assert client.get(f"/tickets/{created['id']}").json()["status"] == "open"


def test_escalate_does_not_return_already_escalated_tickets(monkeypatch):
    _drain_eligible_tickets()
    created = _create_escalation_ticket(monkeypatch)

    first = client.post("/tickets/escalate")
    second = client.post("/tickets/escalate")

    assert first.status_code == 200
    assert [t["id"] for t in first.json()] == [created["id"]]
    assert second.status_code == 200
    assert second.json() == []
