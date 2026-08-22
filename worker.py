import asyncio

from temporalio.client import Client
from temporalio.worker import Worker

from activities import invoke_model
from config import TemporalSettings, temporal_client
from workflows.deep_research_workflow import DeepResearchWorkflow


def create_worker(client: Client, settings: TemporalSettings) -> Worker:
    """Create the worker shared by the CLI and web application runtimes."""

    return Worker(
        client,
        task_queue=settings.task_queue,
        workflows=[DeepResearchWorkflow],
        activities=[invoke_model.invoke_model],
    )


async def main():
    settings = TemporalSettings.from_env()
    client = await temporal_client(settings)
    worker = create_worker(client, settings)

    print(
        f"Starting Deep Research Worker on {settings.address} "
        f"in namespace '{settings.namespace}', polling '{settings.task_queue}'..."
    )

    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
