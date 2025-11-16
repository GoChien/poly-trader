from fastapi import FastAPI, HTTPException
import httpx
import os
import uuid

app = FastAPI()

# Get AGENT_URL from environment variable
AGENT_URL = os.getenv("AGENT_URL", "http://localhost:8000")


@app.get("/")
async def root():
    return {"message": "Hello World"}


@app.post("/run_agent")
async def run_agent():
    """
    Creates a session and sends a message to the agent with hard-coded values.
    
    Returns:
        Response from the agent run endpoint
    """
    app_name = "agents"
    user_id = "tester"
    message_text = "Tell me about the current market status"
    session_id = str(uuid.uuid4())
    
    async with httpx.AsyncClient() as client:
        # First: Create a session
        session_url = f"{AGENT_URL}/apps/{app_name}/users/{user_id}/sessions/{session_id}"
        try:
            session_response = await client.post(session_url)
            session_response.raise_for_status()
        except httpx.HTTPError as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to create session: {str(e)}"
            )
        
        # Second: Send message to run endpoint
        run_url = f"{AGENT_URL}/run"
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
            return run_response.json()
        except httpx.HTTPError as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to run agent: {str(e)}"
            )