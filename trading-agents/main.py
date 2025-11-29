import os
import uuid

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from google.adk.cli.fast_api import get_fast_api_app

# Get the directory where main.py is located
AGENT_DIR = os.path.dirname(os.path.abspath(__file__))
# Example session service URI (e.g., SQLite)
SESSION_SERVICE_URI = "sqlite:///./sessions.db"
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
    session_service_uri=SESSION_SERVICE_URI,
    allow_origins=ALLOWED_ORIGINS,
    web=SERVE_WEB_INTERFACE,
)


# Additional endpoint: run_agent
# This endpoint creates a session and sends a message to the agent with hard-coded values
@app.post("/run_agent", include_in_schema=False)
async def run_agent(request: Request):
    """
    Creates a session and sends a message to the agent with hard-coded values.
    
    Returns:
        Response from the agent run endpoint
    """
    # Automatically detect the server's URL from the incoming request
    # This works in dev (port 8000), production (port from $PORT), or any configuration
    agent_url = f"{request.url.scheme}://{request.url.netloc}"

    app_name = "agents"
    user_id = "tester"
    message_text = "Help me to manage my portfolio."
    session_id = str(uuid.uuid4())

    # Set a longer timeout for agent operations (default is 5 seconds)
    timeout = httpx.Timeout(
        connect=10.0,  # Connection timeout
        read=300.0,    # Read timeout (5 minutes for long-running agents)
        write=10.0,    # Write timeout
        pool=10.0      # Pool timeout
    )

    async with httpx.AsyncClient(timeout=timeout) as client:
        # First: Create a session
        session_url = f"{agent_url}/apps/{app_name}/users/{user_id}/sessions/{session_id}"
        try:
            session_response = await client.post(session_url)
            session_response.raise_for_status()
        except httpx.HTTPError as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to create session: {str(e)}"
            )

        # Second: Send message to run endpoint
        run_url = f"{agent_url}/run"
        payload = {
            "appName": app_name,
            "userId": user_id,
            "sessionId": session_id,
            "newMessage": {
                "role": "user",
                "parts": [
                    {
                        "text": message_text
                    }
                ]
            }
        }

        try:
            run_response = await client.post(
                run_url,
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            run_response.raise_for_status()

            # Log response details for debugging
            print(f"Run response status: {run_response.status_code}")
            print(f"Run response headers: {run_response.headers}")
            print(
                f"Run response content-type: {run_response.headers.get('content-type', 'unknown')}")

            # Try to parse JSON response
            try:
                return run_response.json()
            except Exception as json_error:
                print(f"Failed to parse JSON response: {json_error}")
                # First 500 chars
                print(f"Response text: {run_response.text[:500]}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to parse agent response: {str(json_error)}"
                )

        except httpx.HTTPError as e:
            print(f"HTTP Error occurred: {type(e).__name__}: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to run agent: {type(e).__name__}: {str(e)}"
            )

if __name__ == "__main__":
    # Use the PORT environment variable provided by Cloud Run, defaulting to 8080
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
