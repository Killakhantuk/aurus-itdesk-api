from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from main import app, store

client = TestClient(app)


def _set_sla_deadline(ticket_id: str, deadline: datetime):
    ticket = store.get(ticket_id)
    assert ticket is not None
    store._tickets[ticket_id] = ticket.model_copy(update={"sla_deadline": deadline})


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


def test_escalate_overdue_critical_unassigned_ticket():
    ticket_id = client.post("/tickets", json={
        "title": "Critical outage",
        "description": "Production service is unavailable.",
        "priority": "critical",
    }).json()["id"]
    _set_sla_deadline(
        ticket_id,
        datetime.now(timezone.utc) - timedelta(minutes=1),
    )

    resp = client.post("/tickets/escalate")

    assert resp.status_code == 200
    assert [ticket["id"] for ticket in resp.json()] == [ticket_id]
    assert resp.json()[0]["status"] == "escalated"


def test_escalate_skips_non_qualifying_tickets():
    wrong_priority_id = client.post("/tickets", json={
        "title": "High priority issue",
        "description": "This is not critical.",
        "priority": "high",
    }).json()["id"]
    assigned_id = client.post("/tickets", json={
        "title": "Assigned critical issue",
        "description": "An engineer owns this ticket.",
        "priority": "critical",
        "assignee": "engineer@aurus.com",
    }).json()["id"]
    not_overdue_id = client.post("/tickets", json={
        "title": "New critical issue",
        "description": "This ticket is still within SLA.",
        "priority": "critical",
    }).json()["id"]
    overdue_deadline = datetime.now(timezone.utc) - timedelta(minutes=1)
    _set_sla_deadline(wrong_priority_id, overdue_deadline)
    _set_sla_deadline(assigned_id, overdue_deadline)
    _set_sla_deadline(
        not_overdue_id,
        datetime.now(timezone.utc) + timedelta(hours=1),
    )

    resp = client.post("/tickets/escalate")

    assert resp.status_code == 200
    escalated_ids = [ticket["id"] for ticket in resp.json()]
    assert wrong_priority_id not in escalated_ids
    assert assigned_id not in escalated_ids
    assert not_overdue_id not in escalated_ids