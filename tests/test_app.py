from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import app as marketing


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(marketing, "_login_attempts", {})
    monkeypatch.setattr(marketing.settings, "data_dir", tmp_path)
    monkeypatch.setattr(marketing.settings, "app_env", "test")
    monkeypatch.setattr(marketing.store, "data_dir", tmp_path)
    monkeypatch.setattr(marketing.store, "path", tmp_path / "operations.json")
    with TestClient(marketing.app, base_url="http://127.0.0.1") as test_client:
        token = (tmp_path / "bootstrap.token").read_text(encoding="utf-8")
        response = test_client.post(
            "/api/auth/login",
            json={"password": token},
            headers={"Origin": "http://127.0.0.1"},
        )
        assert response.status_code == 200
        response = test_client.post(
            "/api/auth/setup",
            json={"password": "local-test-password-long"},
            headers={"Origin": "http://127.0.0.1"},
        )
        assert response.status_code == 200
        yield test_client


def test_dashboard_health_authentication_and_local_host_guard(client):
    assert client.get("/api/health").json()["remote_store_connected"] is False
    dashboard = client.get("/")
    assert dashboard.status_code == 200
    assert "AI content studio" in dashboard.text
    assert 'id="contentLanguage"' in dashboard.text
    assert 'id="contentAngle"' in dashboard.text
    assert client.get("/api/overview").status_code == 200
    assert client.get("/api/health", headers={"host": "attacker.example"}).status_code == 421


def test_product_import_is_unverified_and_change_log_is_idempotent(client):
    initial = {
        "products": [
            {
                "id": "toy-1",
                "name": "Sample toy",
                "price": "499.00",
                "stock": 5,
                "url": "https://nvmtoys.com/products/toy-1",
            }
        ]
    }
    response = client.post(
        "/api/products/import",
        content=json.dumps(initial),
        headers={"Content-Type": "application/json", "Origin": "http://127.0.0.1"},
    )
    assert response.status_code == 200
    assert client.get("/api/products").json()["products"][0]["verified"] is False
    assert client.get("/api/products/monitor").json()["changes"][0]["change_type"] == "new_product"

    initial["products"][0]["stock"] = 3
    client.post(
        "/api/products/import",
        content=json.dumps(initial),
        headers={"Content-Type": "application/json", "Origin": "http://127.0.0.1"},
    )
    changes = client.get("/api/products/monitor").json()["changes"]
    assert len(changes) == 2
    assert changes[0]["fields"] == ["stock"]
    assert changes[0]["notification_sent"] is False


def test_catalog_marketing_plan_covers_products_and_identifies_missing_sales_data(client):
    response = client.post(
        "/api/products/import",
        json=[
            {"id": "toy-1", "name": "Building Blocks", "description": "Colorful blocks", "active": True},
            {"id": "toy-2", "name": "Puzzle", "active": False},
            {"id": "toy-3", "name": "Toy Car"},
        ],
        headers={"Origin": "http://127.0.0.1"},
    )
    assert response.status_code == 200
    event = client.post(
        "/api/events",
        json={
            "event_id": "product-view-toy-1",
            "type": "product_view",
            "occurred_at": datetime.now().astimezone().isoformat(),
            "product_id": "toy-1",
        },
        headers={"Origin": "http://127.0.0.1"},
    )
    assert event.status_code == 200
    plan = client.get("/api/products/marketing-plan").json()
    assert plan["catalog_count"] == 3
    assert plan["active_count"] == 2
    assert plan["verified_active_count"] == 0
    assert plan["sales_data_available"] is False
    assert "not sales" in plan["sales_data_note"]
    assert plan["measured_interest_count"] == 1
    assert next(
        item for item in plan["products"] if item["product_id"] == "toy-1"
    )["interest_events"] == 1
    assert {item["product_id"] for item in plan["products"]} == {"toy-1", "toy-2", "toy-3"}
    unknown = next(item for item in plan["products"] if item["product_id"] == "toy-3")
    assert unknown["active"] == "unknown"
    assert unknown["active_for_draft_planning"] is True
    assert "Verify" in unknown["promotion_status"]


def test_product_marketing_batch_creates_safe_idempotent_drafts_for_active_catalog(client):
    client.post(
        "/api/products/import",
        json=[
            {
                "id": "toy-1",
                "name": "Building Blocks",
                "description": "Colorful blocks for creative play.",
                "url": "https://nvmtoys.com/products/building-blocks",
                "active": True,
            },
            {"id": "toy-2", "name": "Puzzle", "active": False},
            {"id": "toy-3", "name": "Toy Car"},
        ],
        headers={"Origin": "http://127.0.0.1"},
    )
    request = {"channel": "instagram", "objective": "Showcase the catalog"}
    headers = {"Origin": "http://127.0.0.1"}
    first = client.post("/api/products/marketing-drafts", json=request, headers=headers)
    duplicate = client.post("/api/products/marketing-drafts", json=request, headers=headers)
    assert first.status_code == 200
    assert first.json()["created_count"] == 2
    assert first.json()["skipped_inactive_product_ids"] == ["toy-2"]
    assert first.json()["external_action_executed"] is False
    assert first.json()["gemini_requests"] == 0
    assert duplicate.json()["duplicate"] is True
    drafts = client.get("/api/content").json()["content"]
    assert len(drafts) == 2
    assert all(row["status"] == "DRAFT" for row in drafts)
    assert all(row["generation_method"] == "deterministic_template_no_ai" for row in drafts)
    assert all(not row["source_facts"].get("price") for row in drafts)
    assert all("₹" not in row["draft"] and "% off" not in row["draft"] for row in drafts)
    unverified = next(row for row in drafts if row["product_id"] == "toy-3")
    assert any("unverified" in warning for warning in unverified["warnings"])
    reel = client.post(
        "/api/products/marketing-drafts",
        json={"channel": "reel", "objective": "Introduce in short video"},
        headers=headers,
    )
    assert reel.status_code == 200
    reel_draft = next(
        row
        for row in client.get("/api/content").json()["content"]
        if row["channel"] == "reel" and row["product_id"] == "toy-1"
    )
    assert "Hook:" in reel_draft["draft"] and "Visual:" in reel_draft["draft"]


def test_invalid_product_and_external_url_are_rejected(client):
    response = client.post(
        "/api/products/import",
        json=[{"id": "p1", "name": "Bad URL", "url": "http://127.0.0.1/private"}],
        headers={"Origin": "http://127.0.0.1"},
    )
    assert response.status_code == 422


def test_event_timestamp_consent_and_idempotency(client):
    client.post(
        "/api/products/import",
        json=[{"id": "p1", "name": "Toy"}],
        headers={"Origin": "http://127.0.0.1"},
    )
    event = {
        "event_id": "evt-0000001",
        "type": "marketing_consent",
        "occurred_at": datetime.now().astimezone().isoformat(),
        "consent": True,
        "consent_source": "local_test",
        "consent_purpose": "email_marketing",
    }
    first = client.post("/api/events", json=event, headers={"Origin": "http://127.0.0.1"})
    duplicate = client.post("/api/events", json=event, headers={"Origin": "http://127.0.0.1"})
    assert first.status_code == 200 and first.json()["duplicate"] is False
    assert duplicate.status_code == 200 and duplicate.json()["duplicate"] is True
    event["event_id"] = "evt-0000002"
    event["occurred_at"] = "2026-10-09T08:00:00"
    assert client.post("/api/events", json=event, headers={"Origin": "http://127.0.0.1"}).status_code == 422
    assert client.get("/api/segments").json()["marketing_consent_events"] == 1


def test_campaign_approval_never_executes_external_action(client):
    campaign = {
        "name": "Toy launch",
        "objective": "Introduce new toy",
        "channel": "organic",
        "product_ids": [],
        "discount_percent": None,
        "budget_inr": "0",
    }
    created = client.post("/api/campaigns", json=campaign, headers={"Origin": "http://127.0.0.1"})
    assert created.status_code == 200
    campaign_id = created.json()["id"]
    proposal = client.post(
        f"/api/campaigns/{campaign_id}/approval",
        headers={"Origin": "http://127.0.0.1"},
    ).json()
    decision = client.post(
        f"/api/approvals/{proposal['id']}",
        json={"decision": "approve"},
        headers={"Origin": "http://127.0.0.1"},
    )
    assert decision.status_code == 200
    assert decision.json()["external_action_executed"] is False
    assert client.get("/api/campaigns").json()["campaigns"][0]["status"] == "APPROVED"


def test_pending_approval_prevents_stale_content_edits(client):
    created = client.post(
        "/api/content",
        json={"channel": "manual", "objective": "Review", "draft": "Original text"},
        headers={"Origin": "http://127.0.0.1"},
    ).json()
    approval = client.post(
        f"/api/content/{created['id']}/approval",
        headers={"Origin": "http://127.0.0.1"},
    )
    assert approval.status_code == 200
    edited = client.patch(
        f"/api/content/{created['id']}",
        json={"channel": "manual", "objective": "Changed", "draft": "Changed text"},
        headers={"Origin": "http://127.0.0.1"},
    )
    assert edited.status_code == 409


def test_manual_content_export_and_unverified_product_ai_block(client):
    client.post(
        "/api/products/import",
        json=[{"id": "p1", "name": "Toy"}],
        headers={"Origin": "http://127.0.0.1"},
    )
    response = client.post(
        "/api/content",
        json={
            "channel": "instagram",
            "objective": "Introduce toy",
            "draft": "Review this toy.",
            "product_id": "p1",
        },
        headers={"Origin": "http://127.0.0.1"},
    )
    assert response.status_code == 200
    assert client.get("/api/export/content?format=json").json()["items"][0]["status"] == "DRAFT"
    generated = client.post(
        "/api/content/generate",
        json={"channel": "instagram", "objective": "Introduce toy", "product_id": "p1"},
        headers={"Origin": "http://127.0.0.1"},
    )
    assert generated.status_code == 409


def test_csv_export_escapes_spreadsheet_formulas(client):
    client.post(
        "/api/products/import",
        json=[{"id": "p1", "name": "=HYPERLINK(\"https://bad.example\")"}],
        headers={"Origin": "http://127.0.0.1"},
    )
    exported = client.get("/api/export/products?format=csv")
    assert exported.status_code == 200
    assert "'=HYPERLINK" in exported.text


def test_unconfigured_mcp_does_not_call_network(client):
    response = client.post("/api/integrations/mcp/discover", headers={"Origin": "http://127.0.0.1"})
    assert response.status_code == 503
    assert "no request was sent" in response.json()["detail"]


def test_budget_unknown_pricing_fails_closed(client, monkeypatch):
    monkeypatch.setattr(marketing.settings, "gemini_enabled", True)
    monkeypatch.setattr(marketing.settings, "demo_mode", False)
    monkeypatch.setattr(marketing.settings, "gemini_api_key", "test-only-key")
    monkeypatch.setattr(marketing.settings, "gemini_model", "test-model")
    monkeypatch.setattr(marketing.settings, "input_rate", None)
    monkeypatch.setattr(marketing.settings, "output_rate", None)
    monkeypatch.setattr(marketing.settings, "usd_to_inr", None)
    with pytest.raises(HTTPException) as error:
        marketing.budget.reserve("test-model", "safe prompt", 32, "hash")
    assert error.value.status_code == 503
    assert marketing.budget.status()["requests"] == 0


def test_gemini_calls_are_mocked_metered_and_cached(client, monkeypatch):
    monkeypatch.setattr(marketing.settings, "gemini_enabled", True)
    monkeypatch.setattr(marketing.settings, "demo_mode", False)
    monkeypatch.setattr(marketing.settings, "gemini_api_key", "test-only-key")
    monkeypatch.setattr(marketing.settings, "gemini_model", "test-model")
    monkeypatch.setattr(marketing.settings, "input_rate", Decimal(1))
    monkeypatch.setattr(marketing.settings, "output_rate", Decimal(2))
    monkeypatch.setattr(marketing.settings, "usd_to_inr", Decimal(80))
    monkeypatch.setattr(marketing.settings, "total_budget", Decimal(500))
    monkeypatch.setattr(marketing.settings, "daily_budget", Decimal(10))
    monkeypatch.setattr(marketing.settings, "reserve_percent", Decimal(10))
    monkeypatch.setattr(marketing.settings, "max_output_tokens", 64)
    calls = []

    class MockModels:
        def generate_content(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                text="A joyful toy-time idea.",
                usage_metadata=SimpleNamespace(
                    prompt_token_count=12,
                    candidates_token_count=7,
                    total_token_count=19,
                ),
            )

    class MockClient:
        def __init__(self, **kwargs):
            assert kwargs["api_key"] == "test-only-key"
            self.models = MockModels()

    from google import genai

    monkeypatch.setattr(genai, "Client", MockClient)
    request = {
        "channel": "instagram",
        "objective": "Create a cheerful general brand caption",
        "tone": "educational",
        "language": "Hindi",
        "angle": "gift_idea",
        "notes": "Keep the opening concise.",
    }
    headers = {"Origin": "http://127.0.0.1"}
    first = client.post("/api/content/generate", json=request, headers=headers)
    second = client.post("/api/content/generate", json=request, headers=headers)
    assert first.status_code == 200
    assert second.status_code == 200
    assert len(calls) == 1
    ledger = marketing.budget.status()
    assert ledger["requests"] == 1
    assert ledger["successful_requests"] == 1
    assert ledger["input_tokens"] == 12
    assert ledger["output_tokens"] == 7
    assert "Language: Hindi" in calls[0]["contents"]
    assert "Campaign angle: gift_idea" in calls[0]["contents"]
    assert "scroll-stopping opening" in calls[0]["contents"]
    assert first.json()["generation_brief"] == {
        "tone": "educational",
        "language": "Hindi",
        "angle": "gift_idea",
    }


def test_generation_rejects_unsupported_marketing_preferences(client):
    response = client.post(
        "/api/content/generate",
        json={
            "channel": "instagram",
            "objective": "Introduce the brand",
            "tone": "aggressive",
        },
        headers={"Origin": "http://127.0.0.1"},
    )
    assert response.status_code == 422


def test_budget_reserve_blocks_over_budget_and_ai_emergency_stop(client, monkeypatch):
    monkeypatch.setattr(marketing.settings, "gemini_enabled", True)
    monkeypatch.setattr(marketing.settings, "demo_mode", False)
    monkeypatch.setattr(marketing.settings, "gemini_api_key", "test-only-key")
    monkeypatch.setattr(marketing.settings, "gemini_model", "test-model")
    monkeypatch.setattr(marketing.settings, "input_rate", Decimal(100000))
    monkeypatch.setattr(marketing.settings, "output_rate", Decimal(100000))
    monkeypatch.setattr(marketing.settings, "usd_to_inr", Decimal(100))
    monkeypatch.setattr(marketing.settings, "total_budget", Decimal("0.001"))
    monkeypatch.setattr(marketing.settings, "daily_budget", Decimal(10))
    monkeypatch.setattr(marketing.settings, "reserve_percent", Decimal(0))
    with pytest.raises(HTTPException) as error:
        marketing.budget.reserve("test-model", "safe prompt", 32, "hash")
    assert error.value.status_code == 429
    assert marketing.budget.status()["requests"] == 0

    client.post("/api/budget/disable", headers={"Origin": "http://127.0.0.1"})
    monkeypatch.setattr(marketing.settings, "input_rate", Decimal(1))
    monkeypatch.setattr(marketing.settings, "output_rate", Decimal(1))
    with pytest.raises(HTTPException) as disabled:
        marketing.budget.reserve("test-model", "safe prompt", 1, "hash-2")
    assert disabled.value.status_code == 503


def test_reports_do_not_fabricate_sales_and_backup_is_local(client, tmp_path):
    report = client.get("/api/analytics").json()
    assert "revenue" in report["unavailable"]
    assert client.get("/api/events").json()["revenue"] is None
    backup = client.post("/api/backup", headers={"Origin": "http://127.0.0.1"})
    assert backup.status_code == 200
    assert (tmp_path / "backups" / backup.json()["backup"]).exists()


def test_secret_values_are_not_returned(client, monkeypatch):
    monkeypatch.setattr(marketing.settings, "gemini_api_key", "never-return-this")
    response = client.get("/api/settings")
    assert response.status_code == 200
    assert "never-return-this" not in response.text
