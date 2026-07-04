from fastapi.testclient import TestClient

from app.core.database import get_db
from app.main import app


def auth_headers(client: TestClient, username: str = "xiaxin") -> dict[str, str]:
    response = client.post(
        "/api/auth/register",
        json={"username": username, "password": "123456"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_system_status_endpoint():
    client = TestClient(app)

    response = client.get("/api/system/status")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["app"] == "Tomato Case Agent"


def test_workbench_flow_creates_case_submits_followup_and_reads_detail(db_session):
    def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    try:
        headers = auth_headers(client)
        created = client.post(
            "/api/conversation/messages",
            headers=headers,
            json={
                "message": "下部老叶有褐色斑点，有同心轮纹，最近连续阴雨，现在结果期，距离采收大概 10 天。",
                "image_urls": ["data:image/png;base64,abc123"],
            },
        )

        assert created.status_code == 200
        created_body = created.json()
        assert created_body["created_case"] is True
        assert created_body["response"]["status"] == "FOLLOWUP_PENDING"

        case_id = created_body["case_id"]
        followup = client.post(
            f"/api/cases/{case_id}/followup",
            headers=headers,
            json={
                "description": "病斑没有增加，新叶正常，整体比前两天稳定。",
                "has_new_spots": False,
                "spots_expanded": False,
                "spread_to_new_parts": False,
                "fruit_affected": False,
            },
        )

        assert followup.status_code == 200
        assert followup.json()["status"] in {"IMPROVING", "FOLLOWUP_REVIEW"}

        detail = client.get(f"/api/cases/{case_id}", headers=headers)
        assert detail.status_code == 200
        detail_body = detail.json()
        assert detail_body["events"]
        assert detail_body["followups"]
        event_types = {event["event_type"] for event in detail_body["events"]}
        assert "VISION_ANALYZED" in event_types
        assert "WEATHER_OBSERVED" in event_types
        assert "REMINDER_CREATED" in event_types
        assert "REMINDER_CANCELLED" in event_types

        events = client.get(f"/api/cases/{case_id}/events", headers=headers)
        assert events.status_code == 200
        assert any(event["event_type"] == "STATE_CHANGED" for event in events.json())

        report = client.get(f"/api/cases/{case_id}/report", headers=headers)
        assert report.status_code == 200
        assert f"Tomato Case #{case_id}" in report.text
        assert "事件时间线" in report.text
    finally:
        app.dependency_overrides.clear()


def test_cases_are_scoped_to_authenticated_user(db_session):
    def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    try:
        first_headers = auth_headers(client, "user-a")
        second_headers = auth_headers(client, "user-b")
        created = client.post(
            "/api/conversation/messages",
            headers=first_headers,
            json={"message": "下部老叶有褐色斑点，有同心轮纹，现在结果期，距离采收大概 10 天。"},
        )
        assert created.status_code == 200
        case_id = created.json()["case_id"]

        assert client.get(f"/api/cases/{case_id}", headers=first_headers).status_code == 200
        assert client.get(f"/api/cases/{case_id}", headers=second_headers).status_code == 404
        assert client.get("/api/cases", headers=second_headers).json() == []
    finally:
        app.dependency_overrides.clear()


def test_case_api_requires_authentication(db_session):
    def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    try:
        response = client.get("/api/cases")
        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()
