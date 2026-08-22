from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from aiohttp.test_utils import TestClient, TestServer
from temporalio.client import WorkflowExecutionStatus

from app import create_web_app
from config import TemporalSettings


def fake_temporal_client(*, status=WorkflowExecutionStatus.COMPLETED):
    report = """# Deep Research Report

## Executive Summary
Evidence-backed result.

## Detailed Analysis
Durable execution preserves application progress.

## Recommended Follow-up Questions
• How do retries work?
• How is workflow state recovered?
"""
    handle = SimpleNamespace(
        cancel=AsyncMock(),
        describe=AsyncMock(
            return_value=SimpleNamespace(
                status=status,
                memo_value=AsyncMock(return_value="durable AI research"),
            )
        ),
        result=AsyncMock(return_value=report),
    )
    client = SimpleNamespace(
        get_workflow_handle=Mock(return_value=handle),
        service_client=SimpleNamespace(check_health=AsyncMock(return_value=True)),
        start_workflow=AsyncMock(return_value=handle),
    )
    return client, handle


async def app_client(client) -> TestClient:
    settings = TemporalSettings(
        address="namespace.account.tmprl.cloud:7233",
        namespace="namespace.account",
        task_queue="deep-research",
        api_key="secret",
    )
    test_client = TestClient(
        TestServer(create_web_app(client, settings, starts_per_hour=10))
    )
    await test_client.start_server()
    return test_client


@pytest.mark.asyncio
async def test_root_health_and_readiness():
    temporal, _ = fake_temporal_client()
    client = await app_client(temporal)
    try:
        root = await client.get("/")
        assert root.status == 200
        assert "Durable Deep Research" in await root.text()

        success = await client.get("/success")
        assert success.status == 200
        assert "Research Report · Durable Deep Research" in await success.text()

        stylesheet = await client.get("/static/src/css/styles.css")
        assert stylesheet.status == 200
        assert ".research-card" in await stylesheet.text()

        health = await client.get("/api/health")
        assert health.status == 200
        assert (await health.json())["status"] == "healthy"

        ready = await client.get("/api/ready")
        assert ready.status == 200
        assert await ready.json() == {
            "status": "ready",
            "temporal": "connected",
        }
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_research_lifecycle():
    temporal, handle = fake_temporal_client()
    client = await app_client(temporal)
    try:
        started = await client.post(
            "/api/start-research", json={"query": "  durable AI research  "}
        )
        assert started.status == 201
        started_body = await started.json()
        workflow_id = started_body["workflow_id"]
        assert started_body["status"] == "started"
        assert started_body["interaction"]["status"] == "researching"
        assert started_body["interaction"]["original_query"] == "durable AI research"
        assert started_body["temporal_ui_url"].endswith(workflow_id)
        temporal.start_workflow.assert_awaited_once()
        assert temporal.start_workflow.await_args.args[1] == "durable AI research"
        assert temporal.start_workflow.await_args.kwargs["memo"] == {
            "original_query": "durable AI research"
        }

        status = await client.get(f"/api/status/{workflow_id}")
        assert status.status == 200
        status_body = await status.json()
        assert status_body["status"] == "completed"
        assert status_body["research_completed"] is True
        assert status_body["original_query"] == "durable AI research"

        result = await client.get(f"/api/result/{workflow_id}")
        assert result.status == 200
        result_body = await result.json()
        assert result_body["markdown_report"].startswith("# Deep Research Report")
        assert result_body["short_summary"] == "Evidence-backed result."
        assert result_body["follow_up_questions"] == [
            "How do retries work?",
            "How is workflow state recovered?",
        ]
        assert result_body["image_file_path"] is None
        assert result_body["pdf_file_path"] is None

        cancelled = await client.post(f"/api/cancel/{workflow_id}")
        assert cancelled.status == 202
        handle.cancel.assert_awaited_once()
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_invalid_research_query_is_rejected():
    temporal, _ = fake_temporal_client()
    client = await app_client(temporal)
    try:
        response = await client.post("/api/start-research", json={"query": " "})
        assert response.status == 400
        assert (await response.json())["detail"] == "query must be a non-empty string"
        temporal.start_workflow.assert_not_awaited()
    finally:
        await client.close()
