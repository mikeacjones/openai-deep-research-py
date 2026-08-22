from unittest.mock import AsyncMock

import pytest

import config
from config import DEFAULT_TASK_QUEUE, TemporalSettings


def test_local_defaults():
    settings = TemporalSettings.from_env({})

    assert settings.address == "localhost:7233"
    assert settings.namespace == "default"
    assert settings.task_queue == DEFAULT_TASK_QUEUE
    assert settings.api_key is None
    assert settings.tls_enabled is False


def test_registry_environment():
    settings = TemporalSettings.from_env(
        {
            "TEMPORAL_ADDRESS": "namespace.account.tmprl.cloud:7233",
            "TEMPORAL_NAMESPACE": "namespace.account",
            "TEMPORAL_TASK_QUEUE": "deep-research-workspace-123",
            "TEMPORAL_API_KEY": "secret",
        }
    )

    assert settings.address == "namespace.account.tmprl.cloud:7233"
    assert settings.namespace == "namespace.account"
    assert settings.task_queue == "deep-research-workspace-123"
    assert settings.api_key == "secret"


def test_partial_mtls_configuration_is_rejected():
    with pytest.raises(ValueError, match="must be set together"):
        TemporalSettings.from_env({"TEMPORAL_TLS_CERT": "/tmp/client.pem"})


@pytest.mark.asyncio
async def test_api_key_enables_tls(monkeypatch):
    connect = AsyncMock(return_value="client")
    monkeypatch.setattr(config.Client, "connect", connect)
    settings = TemporalSettings(
        address="namespace.account.tmprl.cloud:7233",
        namespace="namespace.account",
        api_key="secret",
    )

    client = await config.temporal_client(settings)

    assert client == "client"
    connect.assert_awaited_once_with(
        settings.address,
        api_key="secret",
        tls=True,
        namespace=settings.namespace,
        data_converter=config.pydantic_data_converter,
    )
