from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from main import app, store

client = TestClient(app)


def _breach_sla(ticket_id: str, hours: float = 1.0):
    """Move a ticket's SLA deadline into the past to simulate a breach."""
    ticket = store.get(ticket_id)
    store._tickets[ticket_id] = ticket.model_copy(update={
        "sla_deadline": datetime.now(timezone.utc) - timedelta(hours=hours),
    })


def _create_ticket(**overrides) -> str:
    payload = {"title": "Test", "description": "desc", "priority": "medium"}
    payload.update(overrides)
    return client.post("/tickets", json=payload).json()["id"]


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


def test_escalate_overdue_unassigned_critical_ticket():
    ticket_id = _create_ticket(title="Escalate test", priority="critical")
    _breach_sla(ticket_id)
    resp = client.post("/tickets/escalate")
    assert resp.status_code == 200
    escalated = resp.json()
    assert ticket_id in [t["id"] for t in escalated]
    assert all(t["status"] == "escalated" for t in escalated)
    assert client.get(f"/tickets/{ticket_id}").json()["status"] == "escalated"


def test_escalate_skips_non_critical_priority():
    ticket_id = _create_ticket(title="High priority", priority="high")
    _breach_sla(ticket_id)
    resp = client.post("/tickets/escalate")
    assert ticket_id not in [t["id"] for t in resp.json()]
    assert client.get(f"/tickets/{ticket_id}").json()["status"] == "open"


def test_escalate_skips_assigned_tickets():
    ticket_id = _create_ticket(
        title="Assigned critical", priority="critical", assignee="oncall@aurus.com",
    )
    _breach_sla(ticket_id)
    resp = client.post("/tickets/escalate")
    assert ticket_id not in [t["id"] for t in resp.json()]
    assert client.get(f"/tickets/{ticket_id}").json()["status"] == "open"


def test_escalate_skips_tickets_not_yet_overdue():
    ticket_id = _create_ticket(title="Fresh critical", priority="critical")
    resp = client.post("/tickets/escalate")
    assert ticket_id not in [t["id"] for t in resp.json()]
    assert client.get(f"/tickets/{ticket_id}").json()["status"] == "open"


def test_escalate_skips_tickets_not_open():
    ticket_id = _create_ticket(title="In progress critical", priority="critical")
    _breach_sla(ticket_id)
    client.patch(f"/tickets/{ticket_id}", json={"status": "in_progress"})
    resp = client.post("/tickets/escalate")
    assert ticket_id not in [t["id"] for t in resp.json()]
    assert client.get(f"/tickets/{ticket_id}").json()["status"] == "in_progress"


def test_escalation_is_idempotent():
    ticket_id = _create_ticket(title="Escalate once", priority="critical")
    _breach_sla(ticket_id)
    first = client.post("/tickets/escalate").json()
    assert ticket_id in [t["id"] for t in first]
    second = client.post("/tickets/escalate").json()
    assert ticket_id not in [t["id"] for t in second]
    assert client.get(f"/tickets/{ticket_id}").json()["status"] == "escalated"
