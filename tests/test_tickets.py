from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from main import app, store

client = TestClient(app)


def _create_ticket(title, priority, assignee=None):
    payload = {"title": title, "description": "SLA escalation test", "priority": priority}
    if assignee is not None:
        payload["assignee"] = assignee
    resp = client.post("/tickets", json=payload)
    assert resp.status_code == 201
    return resp.json()


def _backdate_sla(ticket_id, hours=2):
    ticket = store._tickets[ticket_id]
    store._tickets[ticket_id] = ticket.model_copy(update={
        "sla_deadline": datetime.now(timezone.utc) - timedelta(hours=hours),
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
    ticket = _create_ticket("Breached critical", "critical")
    _backdate_sla(ticket["id"], hours=2)
    before = client.get(f"/tickets/{ticket['id']}").json()

    resp = client.post("/tickets/escalate")
    assert resp.status_code == 200
    assert ticket["id"] in [t["id"] for t in resp.json()]

    updated = client.get(f"/tickets/{ticket['id']}").json()
    assert updated["status"] == "escalated"
    assert updated["updated_at"] != before["updated_at"]
    for field in ("title", "description", "priority", "assignee", "created_at", "sla_deadline"):
        assert updated[field] == before[field]


def test_escalate_treats_blank_assignee_as_unassigned():
    ticket = _create_ticket("Blank owner critical", "critical", assignee="   ")
    _backdate_sla(ticket["id"])

    resp = client.post("/tickets/escalate")
    assert resp.status_code == 200
    assert ticket["id"] in [t["id"] for t in resp.json()]


def test_escalate_skips_ineligible_tickets():
    not_critical = _create_ticket("High priority overdue", "high")
    assigned = _create_ticket("Assigned critical", "critical", assignee="eng@aurus.com")
    not_open = _create_ticket("Resolved critical", "critical")
    within_sla = _create_ticket("Critical within SLA", "critical")

    _backdate_sla(not_critical["id"])
    _backdate_sla(assigned["id"])
    _backdate_sla(not_open["id"])
    assert client.patch(
        f"/tickets/{not_open['id']}", json={"status": "resolved"}
    ).status_code == 200

    resp = client.post("/tickets/escalate")
    assert resp.status_code == 200
    escalated_ids = [t["id"] for t in resp.json()]

    assert not_critical["id"] not in escalated_ids
    assert assigned["id"] not in escalated_ids
    assert not_open["id"] not in escalated_ids
    assert within_sla["id"] not in escalated_ids

    assert client.get(f"/tickets/{not_critical['id']}").json()["status"] == "open"
    assert client.get(f"/tickets/{assigned['id']}").json()["status"] == "open"
    assert client.get(f"/tickets/{not_open['id']}").json()["status"] == "resolved"
    assert client.get(f"/tickets/{within_sla['id']}").json()["status"] == "open"


def test_escalate_is_idempotent():
    ticket = _create_ticket("Idempotent critical", "critical")
    _backdate_sla(ticket["id"])

    first = client.post("/tickets/escalate").json()
    assert ticket["id"] in [t["id"] for t in first]

    second = client.post("/tickets/escalate").json()
    assert ticket["id"] not in [t["id"] for t in second]

    assert client.get(f"/tickets/{ticket['id']}").json()["status"] == "escalated"


def test_escalate_returns_newest_first():
    older = _create_ticket("Older breached critical", "critical")
    _backdate_sla(older["id"])
    newer = _create_ticket("Newer breached critical", "critical")
    _backdate_sla(newer["id"])

    resp = client.post("/tickets/escalate")
    assert resp.status_code == 200
    body = resp.json()

    created_at = [t["created_at"] for t in body]
    assert created_at == sorted(created_at, reverse=True)
    ids = [t["id"] for t in body]
    assert ids.index(newer["id"]) < ids.index(older["id"])
