import os
import uuid

import httpx
from dotenv import load_dotenv
import uvicorn
from fastapi import FastAPI, HTTPException
from google.adk.cli.fast_api import get_fast_api_app
from google.adk.runners import Runner
from google.adk.sessions.vertex_ai_session_service import VertexAiSessionService
from google.genai.types import Content, Part
from agents.agent import root_agent

# Load environment variables from .env file
load_dotenv()

# Get the directory where main.py is located
AGENT_DIR = os.path.dirname(os.path.abspath(__file__))

# Get GCP configuration from environment variables
GCP_PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT")
GCP_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION")
REASONING_ENGINE_ID = os.getenv("REASONING_ENGINE_ID")

# Use Vertex AI session service for persistent sessions.
VERTEXAI_SESSION_SERVICE_URI = f"agentengine://projects/{GCP_PROJECT_ID}/locations/{GCP_LOCATION}/reasoningEngines/{REASONING_ENGINE_ID}"
# Example allowed origins for CORS
ALLOWED_ORIGINS = ["http://localhost", "http://localhost:8080", "*"]
# Add CLIENT_URL from environment variable if set
if os.environ.get("CLIENT_URL"):
    ALLOWED_ORIGINS.append(os.environ.get("CLIENT_URL"))
# Set web=True if you intend to serve a web interface, False otherwise
SERVE_WEB_INTERFACE = True

# Call the function to get the FastAPI app instance
# Ensure the agent directory name ('capital_agent') matches your agent folder
app: FastAPI = get_fast_api_app(
    agents_dir=AGENT_DIR,
    session_service_uri=VERTEXAI_SESSION_SERVICE_URI,
    allow_origins=ALLOWED_ORIGINS,
    web=SERVE_WEB_INTERFACE,
)


# Additional endpoint: run_agent
# This endpoint creates a session and sends a message to the agent with hard-coded values
@app.post("/run_agent", include_in_schema=False)
async def run_agent():
    """
    Creates a session and sends a message to the agent with hard-coded values.
    
    Returns:
        Response from the agent run endpoint
    """
    app_name = "agents"
    user_id = "tester"
    message_text = "Help me to manage my portfolio."

    # Initialize Vertex AI Session Service
    session_service = VertexAiSessionService(
        GCP_PROJECT_ID,
        GCP_LOCATION,
        REASONING_ENGINE_ID
    )

    # Initialize Runner
    runner = Runner(
        agent=root_agent,
        session_service=session_service,
        app_name=app_name
    )

    # Create session
    session = await session_service.create_session(
        app_name=app_name,
        user_id=user_id,
    )

    # Create Content object
    user_content = Content(
        role="user",
        parts=[Part(text=message_text)]
    )

    try:
        # Run the agent asynchronously
        # We need to collect the response text from the events
        response_text = ""
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session.id,
            new_message=user_content
        ):
            # Check if the event has content and parts with text
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.text:
                        response_text += part.text

        return {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": response_text
                            }
                        ],
                        "role": "model"
                    }
                }
            ]
        }

    except Exception as e:
        print(f"Error running agent: {type(e).__name__}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to run agent: {type(e).__name__}: {str(e)}"
        )

if __name__ == "__main__":
    # Use the PORT environment variable provided by Cloud Run, defaulting to 8080
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
