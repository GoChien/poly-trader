# Agent Operator

## Running the Server Locally

Follow these steps to run the server locally:

### 1. Install Dependencies

```bash
uv sync
```

### 2. Start the Trading Agents API Server

Navigate to the `trading-agents` directory and start the API server:

```bash
cd trading-agents
uv run fastapi dev main.py
```

### 3. Start the Agent Operator Server

In a separate terminal, navigate to the `agent-operator` directory and start the FastAPI server:

```bash
cd agent-operator
uv run fastapi dev main.py --host 0.0.0.0 --port 8001
```

The agent operator server will be available at `http://0.0.0.0:8001`

