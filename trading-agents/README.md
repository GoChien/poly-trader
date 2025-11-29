# Trading agents

The trading agents is built on `uv` and `google-adk`.

## Permisions setup

The ADK uses the Vertex AI session service to store the session state (created by https://docs.cloud.google.com/agent-builder/agent-engine/sessions/manage-sessions-adk#create-agent-engine). Therefore the CloudRun service needs at least `roles/aiplatform.user` to access the service. If running locally, your GCP account needs the same level of permission.

## Dev/test setup

Run the command:

```sh
cd ./trading-agents
uv sync
```

Then create a `/trading-agents/.env` based on `/trading-agents/.env.example` and populate required variables in it.

Then run

```sh
uv run fastapi dev main.py
```

## Available Endpoints

The server exposes all standard ADK endpoints (which can be accessed at http://localhost:8000 in dev mode, not 8080 port), plus:

- **POST `/run_agent`** - Automated agent execution endpoint that creates a session and runs the agent with a predefined message. This is the production endpoint.

To trigger an automated agent run with hard-coded values for testing:

```bash
curl -X POST http://localhost:8000/run_agent
```
