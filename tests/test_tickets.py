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


# ---------- SLA auto-escalation (POST /tickets/escalate) ----------

def force_past_sla(ticket_id: str, hours_past: int = 2) -> None:
    """Push a ticket's SLA deadline into the past to simulate a breach.

    The public API has no way to age a ticket's deadline, so tests reach
    into the in-memory store directly.
    """
    ticket = store._tickets[ticket_id]
    store._tickets[ticket_id] = ticket.model_copy(update={
        "sla_deadline": datetime.now(timezone.utc) - timedelta(hours=hours_past),
    })


def escalated_ids(resp) -> list[str]:
    return [t["id"] for t in resp.json()]


def test_escalate_overdue_critical_unassigned_ticket():
    ticket_id = client.post("/tickets", json={
        "title": "Core banking outage",
        "description": "Critical, open, unassigned, two hours past SLA.",
        "priority": "critical",
    }).json()["id"]
    force_past_sla(ticket_id, hours_past=2)
    before = client.get(f"/tickets/{ticket_id}").json()

    resp = client.post("/tickets/escalate")

    assert resp.status_code == 200
    assert ticket_id in escalated_ids(resp)
    after = client.get(f"/tickets/{ticket_id}").json()
    assert after["status"] == "escalated"
    assert after["updated_at"] != before["updated_at"]
    for field in ("id", "title", "description", "priority", "assignee",
                  "created_at", "sla_deadline"):
        assert after[field] == before[field]


def test_escalate_treats_blank_assignee_as_unassigned():
    ticket_id = client.post("/tickets", json={
        "title": "Payment gateway down",
        "description": "Whitespace-only assignee counts as unowned.",
        "priority": "critical",
        "assignee": "   ",
    }).json()["id"]
    force_past_sla(ticket_id)
    resp = client.post("/tickets/escalate")
    assert resp.status_code == 200
    assert ticket_id in escalated_ids(resp)
    assert client.get(f"/tickets/{ticket_id}").json()["status"] == "escalated"


def test_escalate_skips_non_critical_priority():
    ticket_id = client.post("/tickets", json={
        "title": "High priority, not critical",
        "description": "Overdue, but below the critical threshold.",
        "priority": "high",
    }).json()["id"]
    force_past_sla(ticket_id)
    resp = client.post("/tickets/escalate")
    assert resp.status_code == 200
    assert ticket_id not in escalated_ids(resp)
    assert client.get(f"/tickets/{ticket_id}").json()["status"] == "open"


def test_escalate_skips_assigned_tickets():
    ticket_id = client.post("/tickets", json={
        "title": "Owned critical outage",
        "description": "Someone owns it, so no auto-escalation.",
        "priority": "critical",
        "assignee": "priya.sharma@aurus.com",
    }).json()["id"]
    force_past_sla(ticket_id)
    resp = client.post("/tickets/escalate")
    assert resp.status_code == 200
    assert ticket_id not in escalated_ids(resp)
    assert client.get(f"/tickets/{ticket_id}").json()["status"] == "open"


def test_escalate_skips_tickets_not_open():
    ticket_id = client.post("/tickets", json={
        "title": "Already in progress",
        "description": "Being worked on, so it is not escalated.",
        "priority": "critical",
    }).json()["id"]
    force_past_sla(ticket_id)
    client.patch(f"/tickets/{ticket_id}", json={"status": "in_progress"})
    resp = client.post("/tickets/escalate")
    assert resp.status_code == 200
    assert ticket_id not in escalated_ids(resp)
    assert client.get(f"/tickets/{ticket_id}").json()["status"] == "in_progress"


def test_escalate_skips_tickets_within_sla():
    ticket_id = client.post("/tickets", json={
        "title": "Fresh critical incident",
        "description": "Deadline is still four hours out.",
        "priority": "critical",
    }).json()["id"]
    resp = client.post("/tickets/escalate")
    assert resp.status_code == 200
    assert ticket_id not in escalated_ids(resp)
    assert client.get(f"/tickets/{ticket_id}").json()["status"] == "open"


def test_escalate_does_not_repeat_previous_escalations():
    ticket_id = client.post("/tickets", json={
        "title": "Escalate exactly once",
        "description": "A second call must not return this ticket again.",
        "priority": "critical",
    }).json()["id"]
    force_past_sla(ticket_id)
    first = client.post("/tickets/escalate")
    assert ticket_id in escalated_ids(first)
    second = client.post("/tickets/escalate")
    assert ticket_id not in escalated_ids(second)
    assert client.get(f"/tickets/{ticket_id}").json()["status"] == "escalated"


def test_escalate_returns_newest_first():
    older_id = client.post("/tickets", json={
        "title": "Older eligible outage",
        "description": "Created first.",
        "priority": "critical",
    }).json()["id"]
    newer_id = client.post("/tickets", json={
        "title": "Newer eligible outage",
        "description": "Created second.",
        "priority": "critical",
    }).json()["id"]
    force_past_sla(older_id)
    force_past_sla(newer_id)
    resp = client.post("/tickets/escalate")
    ids = escalated_ids(resp)
    assert set((older_id, newer_id)) <= set(ids)
    assert ids.index(newer_id) < ids.index(older_id)


def test_escalate_returns_empty_list_when_none_eligible():
    # Drain anything still eligible (startup data or earlier tests), then
    # verify a clean queue yields an empty list.
    client.post("/tickets/escalate")
    resp = client.post("/tickets/escalate")
    assert resp.status_code == 200
    assert resp.json() == []
