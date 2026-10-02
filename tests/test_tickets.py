from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from main import app, store

client = TestClient(app)


def _create_ticket(**overrides) -> str:
    payload = {"title": "Escalation test", "description": "desc", "priority": "critical"}
    payload.update(overrides)
    resp = client.post("/tickets", json=payload)
    assert resp.status_code == 201
    return resp.json()["id"]


def _breach_sla(ticket_id: str):
    """Move a ticket's SLA deadline two hours into the past.

    The API has no way to backdate a deadline, so this reaches into the
    in-memory store directly, mirroring how the seed data backdates its
    breached ticket.
    """
    ticket = store.get(ticket_id)
    store._tickets[ticket_id] = ticket.model_copy(update={
        "sla_deadline": datetime.now(timezone.utc) - timedelta(hours=2),
    })


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


def test_escalate_breached_critical_unassigned_ticket():
    ticket_id = _create_ticket()
    _breach_sla(ticket_id)
    before = client.get(f"/tickets/{ticket_id}").json()

    resp = client.post("/tickets/escalate")

    assert resp.status_code == 200
    escalated_ids = [t["id"] for t in resp.json()]
    assert ticket_id in escalated_ids
    returned = next(t for t in resp.json() if t["id"] == ticket_id)
    assert returned["status"] == "escalated"

    after = client.get(f"/tickets/{ticket_id}").json()
    assert after["status"] == "escalated"
    assert after["updated_at"] != before["updated_at"]
    for field in ("title", "description", "priority", "assignee", "created_at", "sla_deadline"):
        assert after[field] == before[field]


def test_escalate_skips_non_critical_ticket():
    ticket_id = _create_ticket(priority="high")
    _breach_sla(ticket_id)

    resp = client.post("/tickets/escalate")

    assert resp.status_code == 200
    assert ticket_id not in [t["id"] for t in resp.json()]
    assert client.get(f"/tickets/{ticket_id}").json()["status"] == "open"


def test_escalate_skips_assigned_ticket():
    ticket_id = _create_ticket(assignee="eng-support@aurus.com")
    _breach_sla(ticket_id)

    resp = client.post("/tickets/escalate")

    assert resp.status_code == 200
    assert ticket_id not in [t["id"] for t in resp.json()]
    assert client.get(f"/tickets/{ticket_id}").json()["status"] == "open"


def test_escalate_skips_non_open_ticket():
    ticket_id = _create_ticket()
    _breach_sla(ticket_id)
    assert client.patch(f"/tickets/{ticket_id}", json={"status": "in_progress"}).status_code == 200

    resp = client.post("/tickets/escalate")

    assert resp.status_code == 200
    assert ticket_id not in [t["id"] for t in resp.json()]
    assert client.get(f"/tickets/{ticket_id}").json()["status"] == "in_progress"


def test_escalate_skips_ticket_within_sla():
    ticket_id = _create_ticket()  # critical tickets get a 4-hour SLA window

    resp = client.post("/tickets/escalate")

    assert resp.status_code == 200
    assert ticket_id not in [t["id"] for t in resp.json()]
    assert client.get(f"/tickets/{ticket_id}").json()["status"] == "open"


def test_escalate_treats_blank_assignee_as_unassigned():
    ticket_id = _create_ticket(assignee="   ")
    _breach_sla(ticket_id)

    resp = client.post("/tickets/escalate")

    assert resp.status_code == 200
    assert ticket_id in [t["id"] for t in resp.json()]
    assert client.get(f"/tickets/{ticket_id}").json()["status"] == "escalated"


def test_escalate_does_not_re_escalate():
    ticket_id = _create_ticket()
    _breach_sla(ticket_id)

    first = client.post("/tickets/escalate")
    assert ticket_id in [t["id"] for t in first.json()]
    after_first = client.get(f"/tickets/{ticket_id}").json()

    second = client.post("/tickets/escalate")

    assert second.status_code == 200
    assert ticket_id not in [t["id"] for t in second.json()]
    after_second = client.get(f"/tickets/{ticket_id}").json()
    assert after_second["status"] == "escalated"
    assert after_second["updated_at"] == after_first["updated_at"]


def test_escalate_returns_newest_first():
    older_id = _create_ticket(title="Older breached ticket")
    newer_id = _create_ticket(title="Newer breached ticket")
    _breach_sla(older_id)
    _breach_sla(newer_id)

    resp = client.post("/tickets/escalate")

    assert resp.status_code == 200
    ids = [t["id"] for t in resp.json()]
    assert older_id in ids
    assert newer_id in ids
    assert ids.index(newer_id) < ids.index(older_id)


def test_escalate_returns_empty_list_when_nothing_is_eligible():
    # Drain anything currently eligible, then add a ticket that is still inside
    # its SLA window: the next run must come back empty.
    client.post("/tickets/escalate")
    _create_ticket(title="Fresh critical ticket")

    resp = client.post("/tickets/escalate")

    assert resp.status_code == 200
    assert resp.json() == []
