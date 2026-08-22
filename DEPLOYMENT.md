# Demo Cloud deployment

This repository is prepared for deployment through the private
`temporal-sa/tmprl-demo-cloud-registry`. The application repository owns the
worker image and its runtime contract. The registry operator owns image
publication, Kubernetes resources, Temporal Cloud credentials, and rollout.

## Application contract

The deployment is a single worker component built from the root `Dockerfile`.
It requires platform-managed Temporal access and polls the task queue in
`TEMPORAL_TASK_QUEUE` (default: `deep-research`).

The worker also requires `OPENAI_API_KEY`. Store it in the AWS Secrets Manager
JSON secret `tmprl-dem-cld/deep-research-python/openai-credentials`; do not
commit it here.

The supported runtime variables are:

| Variable | Required in Demo Cloud | Purpose |
| --- | --- | --- |
| `OPENAI_API_KEY` | yes | OpenAI Responses API and web search |
| `TEMPORAL_ADDRESS` | injected | Temporal frontend endpoint |
| `TEMPORAL_NAMESPACE` | injected | Temporal Cloud namespace |
| `TEMPORAL_API_KEY` | injected | API-key authentication; enables TLS |
| `TEMPORAL_TASK_QUEUE` | recommended | Worker task queue |

For local and non-registry deployment, `TEMPORAL_TLS`, `TEMPORAL_TLS_CERT`, and
`TEMPORAL_TLS_KEY` are also supported.

## Registry onboarding

1. Publish this repository as
   `https://github.com/temporal-sa/deep-research-python-refactor`.
2. Create `tmprl-dem-cld/deep-research-python/openai-credentials` as a JSON
   secret with an `OPENAI_API_KEY` property.
3. Add `projects/demo/deep-research-python.yaml` to the registry.
4. Run the registry validator:

   ```bash
   uv run --isolated --with jsonschema --with pyyaml \
     python scripts/validate_projects.py
   ```

5. Open and merge the registry pull request. The operator will build the image,
   inject Temporal Cloud access, and deploy the worker.
6. Start `DeepResearchWorkflow` on the configured task queue with a string
   research question and inspect the result in the Temporal UI.
