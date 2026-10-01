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


def _drain_eligible_tickets():
    """Escalate any pending eligible tickets so a test starts from a clean slate."""
    return client.post("/tickets/escalate")


def _create_escalation_candidate(**overrides):
    payload = {
        "title": "Escalation candidate",
        "description": "desc",
        "priority": "critical",
    }
    payload.update(overrides)
    resp = client.post("/tickets", json=payload)
    assert resp.status_code == 201
    return resp.json()


def _force_deadline(ticket_id, deadline):
    ticket = store.get(ticket_id)
    store._tickets[ticket_id] = ticket.model_copy(update={"sla_deadline": deadline})


def _overdue():
    return datetime.now(timezone.utc) - timedelta(hours=2)


def test_escalate_escalates_overdue_unassigned_critical_ticket():
    _drain_eligible_tickets()
    created = _create_escalation_candidate(priority="critical", assignee=None)
    _force_deadline(created["id"], _overdue())

    resp = client.post("/tickets/escalate")

    assert resp.status_code == 200
    assert created["id"] in [t["id"] for t in resp.json()]
    updated = client.get(f"/tickets/{created['id']}").json()
    assert updated["status"] == "escalated"
    assert updated["updated_at"] != created["updated_at"]
    # Nothing else on the ticket changes.
    assert updated["priority"] == created["priority"]
    assert updated["title"] == created["title"]
    assert updated["description"] == created["description"]
    assert updated["assignee"] is None
    assert updated["created_at"] == created["created_at"]


def test_escalate_treats_blank_assignee_as_unassigned():
    _drain_eligible_tickets()
    created = _create_escalation_candidate(priority="critical", assignee="   ")
    _force_deadline(created["id"], _overdue())

    assert created["id"] in [t["id"] for t in client.post("/tickets/escalate").json()]
    assert client.get(f"/tickets/{created['id']}").json()["status"] == "escalated"


def test_escalate_ignores_non_critical_overdue_ticket():
    _drain_eligible_tickets()
    created = _create_escalation_candidate(priority="high")
    _force_deadline(created["id"], _overdue())

    assert created["id"] not in [t["id"] for t in client.post("/tickets/escalate").json()]
    assert client.get(f"/tickets/{created['id']}").json()["status"] == "open"


def test_escalate_ignores_assigned_critical_overdue_ticket():
    _drain_eligible_tickets()
    created = _create_escalation_candidate(priority="critical", assignee="eng@aurus.com")
    _force_deadline(created["id"], _overdue())

    assert created["id"] not in [t["id"] for t in client.post("/tickets/escalate").json()]
    assert client.get(f"/tickets/{created['id']}").json()["status"] == "open"


def test_escalate_ignores_critical_overdue_ticket_that_is_not_open():
    _drain_eligible_tickets()
    created = _create_escalation_candidate(priority="critical")
    client.patch(f"/tickets/{created['id']}", json={"status": "in_progress"})
    _force_deadline(created["id"], _overdue())

    assert created["id"] not in [t["id"] for t in client.post("/tickets/escalate").json()]
    assert client.get(f"/tickets/{created['id']}").json()["status"] == "in_progress"


def test_escalate_ignores_critical_unassigned_ticket_within_sla():
    _drain_eligible_tickets()
    created = _create_escalation_candidate(priority="critical")
    _force_deadline(created["id"], datetime.now(timezone.utc) + timedelta(hours=1))

    assert created["id"] not in [t["id"] for t in client.post("/tickets/escalate").json()]
    assert client.get(f"/tickets/{created['id']}").json()["status"] == "open"


def test_escalate_ignores_ticket_without_a_deadline():
    _drain_eligible_tickets()
    created = _create_escalation_candidate(priority="critical")
    _force_deadline(created["id"], None)

    assert created["id"] not in [t["id"] for t in client.post("/tickets/escalate").json()]
    assert client.get(f"/tickets/{created['id']}").json()["status"] == "open"


def test_escalate_does_not_re_escalate_already_escalated_tickets():
    _drain_eligible_tickets()
    created = _create_escalation_candidate(priority="critical")
    _force_deadline(created["id"], _overdue())

    first = client.post("/tickets/escalate").json()
    assert created["id"] in [t["id"] for t in first]

    second = client.post("/tickets/escalate").json()
    assert created["id"] not in [t["id"] for t in second]


def test_escalate_returns_empty_list_when_nothing_is_eligible():
    assert client.post("/tickets/escalate").json() == []
    assert client.post("/tickets/escalate").json() == []


def test_escalate_returns_newest_first():
    _drain_eligible_tickets()
    older = _create_escalation_candidate(priority="critical")
    _force_deadline(older["id"], _overdue())
    newer = _create_escalation_candidate(priority="critical")
    _force_deadline(newer["id"], _overdue())

    ids = [t["id"] for t in client.post("/tickets/escalate").json()]

    assert ids.index(newer["id"]) < ids.index(older["id"])
