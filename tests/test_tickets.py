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


def _reset_store():
    """Empty the shared store so each escalation test starts from a known state."""
    for ticket in store.list():
        store.delete(ticket.id)


def _override_ticket(ticket_id, **fields):
    """Set fields the public API cannot express, such as a past SLA deadline."""
    ticket = store.get(ticket_id)
    store._tickets[ticket_id] = ticket.model_copy(update=fields)


def _create_ticket(**overrides):
    payload = {
        "title": "Escalation test ticket",
        "description": "Escalation scenario ticket",
        "priority": "critical",
    }
    payload.update(overrides)
    return client.post("/tickets", json=payload).json()["id"]


def _parse_utc(value):
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def test_escalate_breached_unassigned_critical():
    _reset_store()
    ticket_id = _create_ticket()
    _override_ticket(ticket_id, sla_deadline=datetime.now(timezone.utc) - timedelta(hours=2))
    before = client.get(f"/tickets/{ticket_id}").json()

    resp = client.post("/tickets/escalate")

    assert resp.status_code == 200
    escalated = resp.json()
    assert [t["id"] for t in escalated] == [ticket_id]
    assert escalated[0]["status"] == "escalated"
    after = client.get(f"/tickets/{ticket_id}").json()
    assert after["status"] == "escalated"
    assert _parse_utc(after["updated_at"]) > _parse_utc(before["updated_at"])
    for field in ("title", "description", "priority", "assignee", "created_at", "sla_deadline"):
        assert after[field] == before[field]


def test_escalate_skips_non_critical_priority():
    _reset_store()
    ticket_id = _create_ticket(priority="high")
    _override_ticket(ticket_id, sla_deadline=datetime.now(timezone.utc) - timedelta(hours=2))

    resp = client.post("/tickets/escalate")

    assert resp.status_code == 200
    assert resp.json() == []
    assert client.get(f"/tickets/{ticket_id}").json()["status"] == "open"


def test_escalate_skips_assigned_tickets():
    _reset_store()
    ticket_id = _create_ticket(assignee="eng-support@aurus.com")
    _override_ticket(ticket_id, sla_deadline=datetime.now(timezone.utc) - timedelta(hours=2))

    resp = client.post("/tickets/escalate")

    assert resp.json() == []
    assert client.get(f"/tickets/{ticket_id}").json()["status"] == "open"


def test_escalate_treats_blank_assignee_as_unassigned():
    _reset_store()
    empty_id = _create_ticket(assignee="")
    spaces_id = _create_ticket(title="Blank assignee ticket", assignee="   ")
    past = datetime.now(timezone.utc) - timedelta(hours=2)
    _override_ticket(empty_id, sla_deadline=past)
    _override_ticket(spaces_id, sla_deadline=past)

    resp = client.post("/tickets/escalate")

    assert set(t["id"] for t in resp.json()) == {empty_id, spaces_id}
    assert all(t["status"] == "escalated" for t in resp.json())


def test_escalate_skips_tickets_not_open():
    _reset_store()
    ticket_id = _create_ticket()
    _override_ticket(ticket_id, sla_deadline=datetime.now(timezone.utc) - timedelta(hours=2))
    client.patch(f"/tickets/{ticket_id}", json={"status": "in_progress"})

    resp = client.post("/tickets/escalate")

    assert resp.json() == []
    assert client.get(f"/tickets/{ticket_id}").json()["status"] == "in_progress"


def test_escalate_skips_tickets_within_sla():
    _reset_store()
    # critical priority sets the SLA deadline 4 hours into the future
    ticket_id = _create_ticket()

    resp = client.post("/tickets/escalate")

    assert resp.json() == []
    assert client.get(f"/tickets/{ticket_id}").json()["status"] == "open"


def test_escalate_skips_tickets_without_deadline():
    _reset_store()
    ticket_id = _create_ticket()
    _override_ticket(ticket_id, sla_deadline=None)

    resp = client.post("/tickets/escalate")

    assert resp.json() == []
    assert client.get(f"/tickets/{ticket_id}").json()["status"] == "open"


def test_escalate_applies_immediately_after_deadline():
    _reset_store()
    ticket_id = _create_ticket()
    _override_ticket(ticket_id, sla_deadline=datetime.now(timezone.utc) - timedelta(seconds=5))

    resp = client.post("/tickets/escalate")

    assert [t["id"] for t in resp.json()] == [ticket_id]


def test_escalate_does_not_reescalate():
    _reset_store()
    ticket_id = _create_ticket()
    _override_ticket(ticket_id, sla_deadline=datetime.now(timezone.utc) - timedelta(hours=2))
    first = client.post("/tickets/escalate").json()
    assert [t["id"] for t in first] == [ticket_id]

    second = client.post("/tickets/escalate")

    assert second.status_code == 200
    assert second.json() == []
    after = client.get(f"/tickets/{ticket_id}").json()
    assert after["status"] == "escalated"
    assert after["updated_at"] == first[0]["updated_at"]


def test_escalate_returns_newest_first():
    _reset_store()
    base = datetime.now(timezone.utc)
    older_id = _create_ticket(title="Older breached ticket")
    newer_id = _create_ticket(title="Newer breached ticket")
    _override_ticket(older_id, created_at=base - timedelta(hours=5), sla_deadline=base - timedelta(hours=3))
    _override_ticket(newer_id, created_at=base, sla_deadline=base - timedelta(hours=1))

    resp = client.post("/tickets/escalate")

    assert [t["id"] for t in resp.json()] == [newer_id, older_id]


def test_escalate_handles_naive_deadlines():
    _reset_store()
    ticket_id = _create_ticket()
    naive_past = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=2)
    _override_ticket(ticket_id, sla_deadline=naive_past)

    resp = client.post("/tickets/escalate")

    assert [t["id"] for t in resp.json()] == [ticket_id]
    assert client.get(f"/tickets/{ticket_id}").json()["status"] == "escalated"
