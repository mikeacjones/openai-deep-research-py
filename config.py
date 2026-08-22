"""Runtime configuration shared by the worker and workflow starter."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from temporalio.client import Client, TLSConfig
from temporalio.contrib.pydantic import pydantic_data_converter

DEFAULT_TASK_QUEUE = "deep-research"


def _is_true(value: str | None) -> bool:
    return value is not None and value.strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


@dataclass(frozen=True)
class TemporalSettings:
    """Temporal connection settings loaded from environment variables."""

    address: str = "localhost:7233"
    namespace: str = "default"
    task_queue: str = DEFAULT_TASK_QUEUE
    api_key: str | None = None
    tls_enabled: bool = False
    tls_cert_path: str | None = None
    tls_key_path: str | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> TemporalSettings:
        values = os.environ if env is None else env
        cert_path = values.get("TEMPORAL_TLS_CERT")
        key_path = values.get("TEMPORAL_TLS_KEY")

        if bool(cert_path) != bool(key_path):
            raise ValueError(
                "TEMPORAL_TLS_CERT and TEMPORAL_TLS_KEY must be set together"
            )

        return cls(
            address=values.get("TEMPORAL_ADDRESS", "localhost:7233"),
            namespace=values.get("TEMPORAL_NAMESPACE", "default"),
            task_queue=values.get("TEMPORAL_TASK_QUEUE")
            or values.get("TASK_QUEUE", DEFAULT_TASK_QUEUE),
            api_key=values.get("TEMPORAL_API_KEY") or None,
            tls_enabled=_is_true(values.get("TEMPORAL_TLS")),
            tls_cert_path=cert_path,
            tls_key_path=key_path,
        )


async def temporal_client(settings: TemporalSettings | None = None) -> Client:
    """Connect to local Temporal or Temporal Cloud using env-driven auth."""

    current = settings or TemporalSettings.from_env()
    common = {
        "namespace": current.namespace,
        "data_converter": pydantic_data_converter,
    }

    if current.api_key:
        return await Client.connect(
            current.address,
            api_key=current.api_key,
            tls=True,
            **common,
        )

    if current.tls_cert_path and current.tls_key_path:
        tls = TLSConfig(
            client_cert=Path(current.tls_cert_path).read_bytes(),
            client_private_key=Path(current.tls_key_path).read_bytes(),
        )
        return await Client.connect(current.address, tls=tls, **common)

    if current.tls_enabled:
        return await Client.connect(current.address, tls=True, **common)

    return await Client.connect(current.address, **common)
