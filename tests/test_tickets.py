from datetime import datetime, timedelta, timezone

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


def _age_sla_deadline(ticket_id, hours=2, naive=False):
    # No API mutates SLA deadlines directly, so scenario setup goes through
    # the store. `naive=True` mimics a deadline that naturally expired.
    deadline = datetime.now(timezone.utc) - timedelta(hours=hours)
    if naive:
        deadline = deadline.replace(tzinfo=None)
    ticket = store._tickets[ticket_id]
    store._tickets[ticket_id] = ticket.model_copy(update={"sla_deadline": deadline})


def _escalated_ids(payload):
    return [t["id"] for t in payload]


def test_escalate_overdue_critical_ticket():
    ticket_id = client.post("/tickets", json={
        "title": "Escalate overdue critical",
        "description": "Critical, open, unassigned ticket with a breached SLA deadline",
        "priority": "critical",
    }).json()["id"]
    _age_sla_deadline(ticket_id, hours=2)
    before = client.get(f"/tickets/{ticket_id}").json()

    resp = client.post("/tickets/escalate")
    assert resp.status_code == 200
    escalated = [t for t in resp.json() if t["id"] == ticket_id]
    assert len(escalated) == 1
    ticket = escalated[0]
    assert ticket["status"] == "escalated"
    assert ticket["title"] == before["title"]
    assert ticket["description"] == before["description"]
    assert ticket["priority"] == before["priority"]
    assert ticket["assignee"] == before["assignee"]
    assert ticket["created_at"] == before["created_at"]
    assert ticket["sla_deadline"] == before["sla_deadline"]
    before_ts = datetime.fromisoformat(before["updated_at"])
    after_ts = datetime.fromisoformat(ticket["updated_at"])
    if before_ts.tzinfo is None:
        before_ts = before_ts.replace(tzinfo=timezone.utc)
    assert after_ts >= before_ts
    assert ticket["updated_at"] != before["updated_at"]


def test_escalate_skips_non_critical_priority():
    ticket_id = client.post("/tickets", json={
        "title": "Overdue but high", "description": "desc", "priority": "high",
    }).json()["id"]
    _age_sla_deadline(ticket_id)

    resp = client.post("/tickets/escalate")
    assert resp.status_code == 200
    assert ticket_id not in _escalated_ids(resp.json())
    assert client.get(f"/tickets/{ticket_id}").json()["status"] == "open"


def test_escalate_skips_assigned_tickets():
    ticket_id = client.post("/tickets", json={
        "title": "Overdue but owned", "description": "desc",
        "priority": "critical", "assignee": "eng-support@aurus.com",
    }).json()["id"]
    _age_sla_deadline(ticket_id)

    resp = client.post("/tickets/escalate")
    assert ticket_id not in _escalated_ids(resp.json())
    assert client.get(f"/tickets/{ticket_id}").json()["status"] == "open"


def test_escalate_treats_blank_assignee_as_unassigned():
    ticket_id = client.post("/tickets", json={
        "title": "Blank assignee", "description": "desc",
        "priority": "critical", "assignee": "   ",
    }).json()["id"]
    _age_sla_deadline(ticket_id, naive=True)

    resp = client.post("/tickets/escalate")
    escalated = [t for t in resp.json() if t["id"] == ticket_id]
    assert len(escalated) == 1
    assert escalated[0]["status"] == "escalated"


def test_escalate_skips_non_open_tickets():
    ticket_id = client.post("/tickets", json={
        "title": "Already in progress", "description": "desc", "priority": "critical",
    }).json()["id"]
    _age_sla_deadline(ticket_id)
    client.patch(f"/tickets/{ticket_id}", json={"status": "in_progress"})

    resp = client.post("/tickets/escalate")
    assert ticket_id not in _escalated_ids(resp.json())
    assert client.get(f"/tickets/{ticket_id}").json()["status"] == "in_progress"


def test_escalate_skips_tickets_within_sla():
    ticket_id = client.post("/tickets", json={
        "title": "Fresh critical ticket", "description": "desc", "priority": "critical",
    }).json()["id"]

    resp = client.post("/tickets/escalate")
    assert ticket_id not in _escalated_ids(resp.json())
    assert client.get(f"/tickets/{ticket_id}").json()["status"] == "open"


def test_escalate_returns_newest_first():
    older_id = client.post("/tickets", json={
        "title": "Older eligible ticket", "description": "desc", "priority": "critical",
    }).json()["id"]
    newer_id = client.post("/tickets", json={
        "title": "Newer eligible ticket", "description": "desc", "priority": "critical",
    }).json()["id"]
    _age_sla_deadline(older_id)
    _age_sla_deadline(newer_id)

    ids = _escalated_ids(client.post("/tickets/escalate").json())
    assert ids.index(newer_id) < ids.index(older_id)


def test_escalate_does_not_reescalate():
    ticket_id = client.post("/tickets", json={
        "title": "Escalate only once", "description": "desc", "priority": "critical",
    }).json()["id"]
    _age_sla_deadline(ticket_id)

    first = client.post("/tickets/escalate")
    assert ticket_id in _escalated_ids(first.json())
    second = client.post("/tickets/escalate")
    assert ticket_id not in _escalated_ids(second.json())
    assert client.get(f"/tickets/{ticket_id}").json()["status"] == "escalated"
