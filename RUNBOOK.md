# Runbook: OpenAI deep research demo (Python)

This runbook is for presenting the demo. The [README](README.md) explains what it is and how it's built.

## What it shows

You ask a research question, and four model calls plan the research, write search queries, search the web in parallel, and write a cited report. Temporal runs the whole pipeline as one Workflow, so a crash, a restart, or a failed model call picks up at the step that was running instead of starting over.

The demo makes three problems visible:

- **A long agent run loses its work when the process dies.** A deep research run makes several slow, paid model calls in sequence. Beat 3 stops the process in the middle of a run, and the run carries on from the step it was on when the process comes back.
- **Model calls fail and time out.** Each call is an Activity with a timeout, and Temporal retries it. The OpenAI client's own retries are off, so each retry shows in the Temporal UI as a new attempt on the Activity.
- **One failed search shouldn't sink the report.** Beat 2 shows the searches running side by side. A search that fails for good is dropped and the report uses the rest; only when every search fails does the run fail.

## Before you start

- Install [uv](https://docs.astral.sh/uv/) and the [Temporal CLI](https://docs.temporal.io/cli).
- You need an OpenAI API key with access to `gpt-4o`, `gpt-4o-mini` and the Responses API's web search tool. Every run makes paid OpenAI calls.
- From the repository root, install the locked dependencies and set up the environment:

  ```bash
  uv sync --frozen
  cp .env.example .env
  # Set OPENAI_API_KEY in .env, then load it into this shell:
  set -a; source .env; set +a
  ```

  The programs read environment variables directly; they don't load `.env` themselves.

### On Temporal Cloud

- To run your own copy against Temporal Cloud, set `TEMPORAL_ADDRESS`, `TEMPORAL_NAMESPACE`, `TEMPORAL_API_KEY` and `TEMPORAL_TASK_QUEUE` before `uv run app.py`. An API key turns on TLS. The README's [Temporal Cloud](README.md#temporal-cloud) section has the values.
- The hosted copy runs at https://openai-deep-research-py.tmprl-demo.cloud behind Temporal sign-in. The platform supplies the Temporal credentials and the OpenAI key, and runs the Worker for you. You can't stop or restart that Worker, so beat 3 works only on a local copy.
- The **View workflow** link opens the run in Temporal Cloud. You need access to the demo's Namespace to follow it.
- Each signed-in user can start 5 runs an hour (`RESEARCH_STARTS_PER_HOUR`). Plan rehearsals around it.

## Start it

In two terminals, from the repository root:

1. `temporal server start-dev` (skip this on Temporal Cloud)
2. `uv run app.py`, in a shell where you loaded `.env`

`app.py` runs the browser UI, the API and the Worker in one process. A healthy start prints `Deep Research app listening on http://0.0.0.0:8234; polling 'deep-research' in 'default'`, and http://localhost:8234/api/ready returns `{"status": "ready", "temporal": "connected"}`.

Open http://localhost:8234. The page shows **Durable Deep Research** and the message "Hey there — what would you like me to research?" The Temporal UI is at http://localhost:8233.

## The walkthrough

### 1. Ask a research question

1. Type a question in **What would you like to research?** and press Enter, or click the arrow button. A narrow question keeps the run short and cheap.
2. The page says "Starting durable research…", then "Thanks — I have what I need. I'm researching your topic now." A spinner reads "Searching, analyzing, and writing your report…". A **View workflow deep-research-…** link appears under the title.
3. Say: "That question just started one Temporal Workflow. Four agents work on it in turn, and each model call is a step that Temporal records."

### 2. Watch the agents in the Temporal UI

1. Click **View workflow deep-research-…**. It opens the run in the Temporal UI in a new tab.
2. In the event history, each model call is an `invoke_model` Activity labelled with what it does: "Planning research", "Generating search queries", one "Searching web for information" per query, then "Generating research report synthesis". The searches start together.
3. Say: "The planning agent breaks the question into aspects, the query agent writes three to five searches, and those searches run in parallel. Each one is an Activity with its own timeout and retries."
4. For proof, open a completed Activity's events. Its input shows the model, the instructions and the prompt; its result shows the structured output that the next agent receives.

### 3. Stop the process in the middle of a run

Do this on a local copy only. Start a new run if the last one finished.

1. While the searches are running, press `Ctrl-C` in the `uv run app.py` terminal. The browser shows "Connection interrupted. Retrying…".
2. In the Temporal UI, the run is still **Running**. Nothing in Temporal depends on the process you stopped.
3. Run `uv run app.py` again. The browser reconnects and the spinner continues. In the Temporal UI, the Activities that were cut off run again with a new attempt number, and the steps that had finished don't run again.
4. Say: "The process that ran the agents is gone, and so is everything it held in memory. Temporal kept each finished step, so the new process starts with the searches that were cut off, not with planning."

Use `Ctrl-C`. A hard kill (`kill -9`) also works, but the cut-off Activities wait for their 5-minute timeout before they run again, which is too long to wait on stage.

You can show the browser half without stopping anything: close the tab mid-run and open http://localhost:8234 again. The page says "Welcome back — resuming your research session." and keeps polling the same run.

### 4. Read the report

1. When the run completes, the page moves to **Research complete**. It shows the **Executive summary**, the full report (toggle it with **Hide full report** / **View full report**), **Questions to explore next**, and **Download Markdown report**.
2. The page also says "No generated image is available. No PDF report is available." This Python version writes neither. Skip past it.
3. Say: "The report is the Workflow's result. It's stored in Temporal, so this page can fetch it again later, from any process."
4. For proof, open the run's **Result** in the Temporal UI. It's the same Markdown the page renders.

### 5. Optional: cancel a run

1. Start a run and click **Cancel research**, then confirm "Cancel this research workflow?".
2. The page shows **Research cancelled** with "This workflow has stopped. Start a new session whenever you are ready." In the Temporal UI, the run's status is **Canceled**.
3. Say: "Cancel is a request to the Workflow. Temporal cancels the Activities it was waiting on and closes the run."

## Show it in code

All links point at commit [`6943f76`](https://github.com/temporal-sa/openai-deep-research-py/commit/6943f764a424c90037d4d40af6f036bd50cf9e9b). Open a file locally with `code -g <path>:<line>`.

### The whole research run is one Workflow

**When to use it:** after beat 2, or when someone asks what the orchestration code looks like.

**Where it is:** [`workflows/deep_research_workflow.py` lines 14–40](https://github.com/temporal-sa/openai-deep-research-py/blob/6943f764a424c90037d4d40af6f036bd50cf9e9b/workflows/deep_research_workflow.py#L14-L40) (`code -g workflows/deep_research_workflow.py:14`)

```python
@workflow.defn
class DeepResearchWorkflow:
    @workflow.run
    async def run(self, query: str) -> str:
        # Step 1: Research Planning
        research_plan = await plan_research(query)

        # Step 2: Query Generation
        query_plan = await generate_queries(research_plan)

        # Step 3: Web Search (parallel execution with resilience)
        search_results = await self._execute_searches(query_plan.queries)

        # Ensure we have at least one successful search result
        if not search_results:
            raise ApplicationError(
                "All web searches failed - cannot generate report",
                "NO_SEARCH_RESULTS",
                non_retryable=True,
            )

        # Step 4: Report Synthesis
        final_report = await generate_synthesis(query, research_plan, search_results)

        # Format the final output
        formatted_report = self._format_final_report(query, final_report)
        return formatted_report
```

**What you need to understand:**

- This is ordinary async Python. Each `await` on an agent is a model call that runs as an Activity, and Temporal records its result in the Workflow's history before the next line runs.
- When a Worker picks up a run that another process started, it replays this function against the history. Finished agents return their recorded results instead of calling OpenAI again, which is why beat 3 resumes at the searches.
- The customer doesn't write checkpointing, a job table, or resume logic. The history is the checkpoint.
- The `ApplicationError` with `non_retryable=True` fails the run when there's nothing to write a report from. Workflows don't retry by default, so a failed run stays failed.

**Docs:** [Workflows](https://docs.temporal.io/workflows), [Python: Workflow basics](https://docs.temporal.io/develop/python/workflows/basics)

### Each agent is one model call with a timeout

**When to use it:** during beat 2, or when someone asks what an "agent" is in this demo.

**Where it is:** [`agents/research_planning.py` lines 32–44](https://github.com/temporal-sa/openai-deep-research-py/blob/6943f764a424c90037d4d40af6f036bd50cf9e9b/agents/research_planning.py#L32-L44) (`code -g agents/research_planning.py:32`). The other three agents in `agents/` follow the same shape.

```python
async def plan_research(query: str) -> ResearchPlan:
    result = await workflow.execute_activity(
        invoke_model,
        InvokeModelRequest(
            model=COMPLEX_REASONING_MODEL,
            instructions=with_today(RESEARCH_PLANNING_INSTRUCTIONS),
            input=f"Research query: {query}",
            response_format=ResearchPlan,
        ),
        start_to_close_timeout=timedelta(seconds=300),
        summary="Planning research",
    )
    return result.response
```

**What you need to understand:**

- An agent here is a prompt, a model and an output type, run as one call to the `invoke_model` Activity. The agent function itself runs in the Workflow; only the call to OpenAI runs in the Activity.
- `response_format=ResearchPlan` asks OpenAI's Structured Outputs for that Pydantic model, so the next agent receives typed data, not text to parse.
- `start_to_close_timeout` of 300 seconds is the limit for one attempt. It has to cover a slow model or a long web search; if it's too short, every attempt times out and the step never finishes. It's also how long Temporal waits before retrying an attempt whose Worker died without reporting back.
- No `retry_policy` is set, so the default applies: retry after 1 second, doubling each time up to 100 seconds, with no limit on attempts. A customer would usually cap the total time with `schedule_to_close_timeout` or limit attempts.
- `summary` is the label the Temporal UI shows for each Activity, which is how beat 2 tells the four agents apart even though they're all `invoke_model`.
- The models are set in [`agents/config.py`](https://github.com/temporal-sa/openai-deep-research-py/blob/6943f764a424c90037d4d40af6f036bd50cf9e9b/agents/config.py#L5-L6): `gpt-4o` for planning and the report, `gpt-4o-mini` for queries and searches.

**Docs:** [Activity timeouts](https://docs.temporal.io/encyclopedia/detecting-activity-failures), [Retry Policies](https://docs.temporal.io/encyclopedia/retry-policies), [Enriching the UI](https://docs.temporal.io/develop/python/platform/enriching-ui)

### Let Temporal retry the model call, not the OpenAI client

**When to use it:** when someone asks what happens on a rate limit or an OpenAI outage.

**Where it is:** [`activities/invoke_model.py` lines 66–83](https://github.com/temporal-sa/openai-deep-research-py/blob/6943f764a424c90037d4d40af6f036bd50cf9e9b/activities/invoke_model.py#L66-L83) (`code -g activities/invoke_model.py:66`)

```python
@activity.defn
async def invoke_model(request: InvokeModelRequest[T]) -> InvokeModelResponse[T]:
    client = AsyncOpenAI(max_retries=0)

    kwargs: dict[str, Any] = {
        "model": request.model,
        "instructions": request.instructions,
        "input": request.input,
    }

    if request.response_format:
        kwargs["text_format"] = request.response_format

    if request.tools:
        kwargs["tools"] = request.tools

    # Use responses API consistently
    resp = await client.responses.parse(**kwargs)
```

**What you need to understand:**

- `max_retries=0` turns off the OpenAI client's built-in retries. Any error ends the attempt, and Temporal schedules the next one with backoff. While it retries, the Temporal UI shows the pending Activity's attempt count and last error, instead of the retries being hidden inside one long call.
- One Activity serves all four agents. The web search agent passes `tools=[{"type": "web_search"}]`, so OpenAI runs the search inside the same call.
- A retry repeats the whole call, including its cost. That's the trade-off for not losing the run.
- The Activity doesn't heartbeat, so a cancelled run stops waiting for it, but a call already in flight runs to completion in the Worker.

**Docs:** [Activities](https://docs.temporal.io/activities), [Python: Activity basics](https://docs.temporal.io/develop/python/activities/basics)

### Run the searches in parallel and keep the ones that succeed

**When to use it:** during beat 2, when the searches start together, or when someone asks what happens if one search breaks.

**Where it is:** [`workflows/deep_research_workflow.py` lines 42–60](https://github.com/temporal-sa/openai-deep-research-py/blob/6943f764a424c90037d4d40af6f036bd50cf9e9b/workflows/deep_research_workflow.py#L42-L60) (`code -g workflows/deep_research_workflow.py:42`)

```python
async def _execute_searches(self, search_queries) -> List[SearchResult]:
    """Execute web searches in parallel with resilience to individual failures"""

    # Create individual search coroutines
    async def execute_single_search(search_query):
        try:
            return await search_web(search_query)
        except Exception as e:
            workflow.logger.exception(
                f"Search failed for query '{search_query.query}': {e}"
            )
            return None

    # Execute all searches in parallel
    search_tasks = [execute_single_search(query) for query in search_queries]
    results = await asyncio.gather(*search_tasks)

    # Filter out None results
    return [result for result in results if result is not None]
```

**What you need to understand:**

- `asyncio.gather` in a Workflow schedules all the search Activities at once, and Workers run them in parallel. The fan-out is plain Python, with no queue or thread pool to manage.
- A search that raises returns `None`, and the report uses the rest. The run fails only when the list comes back empty.
- The `except` sees a search only after Temporal stops retrying it. With the default policy and no overall timeout, a failing search keeps retrying, so this branch runs for errors marked non-retryable, not for a passing outage. To make a broken search drop out after a while, give the search Activity a `schedule_to_close_timeout` or a `maximum_attempts`.

**Docs:** [Parallel Execution pattern](https://docs.temporal.io/design-patterns/parallel-execution), [Error handling](https://docs.temporal.io/develop/python/best-practices/error-handling)

### Keep Workflow code deterministic: the date and the imports

**When to use it:** when someone asks what's different about writing code that runs in a Workflow.

**Where it is:** [`agents/shared.py` lines 49–64](https://github.com/temporal-sa/openai-deep-research-py/blob/6943f764a424c90037d4d40af6f036bd50cf9e9b/agents/shared.py#L49-L64) (`code -g agents/shared.py:49`) and [`agents/research_planning.py` lines 8–9](https://github.com/temporal-sa/openai-deep-research-py/blob/6943f764a424c90037d4d40af6f036bd50cf9e9b/agents/research_planning.py#L8-L9)

```python
def today_str() -> str:
    # Use Temporal workflow time when running inside a workflow.
    # Fall back to the system clock when outside a workflow context.
    try:
        from temporalio import workflow  # type: ignore

        now = workflow.now()
    except Exception:
        now = datetime.now()
    return f"{now:%a} {now:%b} {now.day}, {now:%Y}"


def with_today(instructions: str) -> str:
    # Must be called from workflow code rather than at module import time, so the
    # date comes from the workflow clock and stays consistent across replays.
    return f"{instructions}\nTODAY'S DATE: {today_str()}\n"
```

```python
with workflow.unsafe.imports_passed_through():
    from activities.invoke_model import InvokeModelRequest, invoke_model
```

**What you need to understand:**

- Workflow code has to make the same decisions when it replays. `workflow.now()` returns the time recorded in the history, so the date in each prompt is the same on replay as it was the first time.
- The Python SDK runs Workflow code in a sandbox that restricts non-deterministic modules. `imports_passed_through()` lets the Activity module, and the OpenAI client it imports, load outside the sandbox. The agent code itself stays sandboxed.
- The OpenAI call never runs in the Workflow. It runs in the Activity, where anything goes.

**Docs:** [Python: Workflow sandbox](https://docs.temporal.io/develop/python/best-practices/python-sdk-sandbox), [How Workflow replay works](https://docs.temporal.io/workflows#how-workflow-replay-works)

### Pass Pydantic models between the Workflow and its Activities

**When to use it:** when someone asks how the typed outputs travel from one agent to the next.

**Where it is:** [`config.py` lines 64–67](https://github.com/temporal-sa/openai-deep-research-py/blob/6943f764a424c90037d4d40af6f036bd50cf9e9b/config.py#L64-L67) (`code -g config.py:64`)

```python
common = {
    "namespace": current.namespace,
    "data_converter": pydantic_data_converter,
}
```

**What you need to understand:**

- The client, and the Worker built from it, use the Pydantic data converter, so `ResearchPlan`, `QueryPlan`, `SearchResult` and `ResearchReport` go into and out of Activities as JSON and come back as models.
- `InvokeModelRequest` also carries the output type itself, stored as an import path string, so one generic Activity can return four different models.

**Docs:** [Python: Pydantic data converter](https://docs.temporal.io/develop/python/data-handling/data-conversion#use-pydantic-models)

### Start a run and follow it from the browser

**When to use it:** when someone asks how the web app talks to Temporal.

**Where it is:** [`app.py` lines 233–240](https://github.com/temporal-sa/openai-deep-research-py/blob/6943f764a424c90037d4d40af6f036bd50cf9e9b/app.py#L233-L240) and [lines 254–261](https://github.com/temporal-sa/openai-deep-research-py/blob/6943f764a424c90037d4d40af6f036bd50cf9e9b/app.py#L254-L261) (`code -g app.py:233`)

```python
workflow_id = f"deep-research-{uuid.uuid4().hex[:12]}"
await client.start_workflow(
    DeepResearchWorkflow.run,
    query,
    id=workflow_id,
    task_queue=settings.task_queue,
    memo={"original_query": query},
)
```

```python
async def research_status(request: web.Request) -> web.StreamResponse:
    workflow_id = _workflow_id(request)
    handle = client.get_workflow_handle(workflow_id, result_type=str)
    description = await handle.describe()
    original_query = await description.memo_value(
        "original_query", None, type_hint=str
    )
    status = _status_name(description.status)
```

**What you need to understand:**

- The API starts the Workflow and returns at once. The browser keeps only the Workflow ID, in local storage, which is why a reload or a new tab finds the same run.
- The browser polls every 1.5 seconds. The API answers with Describe, which reads the run's status and the query saved in its memo. The Workflow has no Query handler, so polling never runs Workflow code.
- When the status is completed, the API reads the result from Temporal. Any process with the Workflow ID can do the same.

**Docs:** [Python: Temporal Client](https://docs.temporal.io/develop/python/temporal-client)

### What's demo-only

When someone asks what they'd change for their own system, these are the parts to leave out:

- **The start limit.** [`app.py` lines 38–53](https://github.com/temporal-sa/openai-deep-research-py/blob/6943f764a424c90037d4d40af6f036bd50cf9e9b/app.py#L38-L53) keeps 5 starts per user per hour in memory, to cap OpenAI spend on a shared demo.
- **The shape of the status responses.** [`app.py` lines 91–117](https://github.com/temporal-sa/openai-deep-research-py/blob/6943f764a424c90037d4d40af6f036bd50cf9e9b/app.py#L91-L117) fills in empty clarification fields because the browser UI is shared with the TypeScript version, which asks clarifying questions. This version doesn't.
- **One process for everything.** [`app.py` lines 315–319](https://github.com/temporal-sa/openai-deep-research-py/blob/6943f764a424c90037d4d40af6f036bd50cf9e9b/app.py#L315-L319) runs the API and the Worker together so the demo is one container. A customer would usually scale Workers separately; `uv run worker.py` runs the Worker alone.

## Reset and tear down

- **Between runs:** on the report page, click **Start new research**. After a cancelled or failed run, click **Start new research** in the panel.
- **To drop a run that's still going:** click **Cancel research**, or run `temporal workflow cancel --workflow-id <id>`. The page otherwise resumes the last run each time it loads.
- **To stop:** cancel any run that's still going, then stop `uv run app.py` and the dev server with `Ctrl-C`.
- **On Temporal Cloud:** runs have no overall timeout, and a model call that keeps failing (a bad key, no quota) retries without limit, up to every 100 seconds. Cancel any run you leave behind.

## When something goes wrong

| What you see | Likely cause | Fix |
|---|---|---|
| The spinner never ends, and in the Temporal UI an `invoke_model` Activity's attempt count keeps rising | The OpenAI key is missing or invalid, or out of quota or rate limited | Check the error on the Activity. Fix `OPENAI_API_KEY`, reload `.env`, and restart `uv run app.py`; the run continues at the next attempt |
| "Too many research requests. Try again later." | 5 starts in the last hour for this user (or this IP, locally) | Wait, or set `RESEARCH_STARTS_PER_HOUR` higher and restart the app. A restart also clears the count |
| "Temporal is temporarily unavailable", or `/api/ready` returns 503 | The app can't reach Temporal | Start `temporal server start-dev`, or check the `TEMPORAL_*` variables |
| "Connection interrupted. Retrying…" | `uv run app.py` stopped | Start it again; the page reconnects |
| After a crash, a step sits for up to 5 minutes before it runs again | The process was killed without shutting down, so Temporal waits for the 300-second Start-To-Close timeout | Wait, or use `Ctrl-C` instead of a hard kill next time |
| The report page says no image or PDF is available | Expected; this version produces neither | Skip past it |
| The page opens on "Welcome back — resuming your research session." | The browser remembered the last run | Let it finish, click **Cancel research**, or clear the site's storage |
| **View workflow** opens Temporal Cloud and you can't see the run | You don't have access to the demo's Namespace | Ask for access, or present the history from a local copy |

## Keeping this runbook current

The code links point at a fixed commit. When a linked file changes, update its link, line numbers, and snippet together. Before an event, list the linked files that have changed:

```sh
grep -oE 'blob/[0-9a-f]{40}/[^#)]+' RUNBOOK.md | sort -u | while IFS=/ read -r _ sha file; do
  git diff --quiet "$sha" HEAD -- "$file" || echo "changed since ${sha:0:7}: $file"
done
```
