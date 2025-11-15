# Trading agents

The trading agents is built on `uv` and `google-adk`.

## Setup

Run the command:
```sh
cd ./trading-agents
uv sync
```

Then create a `/trading-agents/agents/.env` based on `/trading-agents/agents/.env.example` and populate required variables in it.

Then activate the virtual environment in `uv` and run `adk web`.