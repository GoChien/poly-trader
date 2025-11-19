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
            
            # Log response details for debugging
            print(f"Run response status: {run_response.status_code}")
            print(f"Run response headers: {run_response.headers}")
            print(f"Run response content-type: {run_response.headers.get('content-type', 'unknown')}")
            
            # Try to parse JSON response
            try:
                return run_response.json()
            except Exception as json_error:
                print(f"Failed to parse JSON response: {json_error}")
                print(f"Response text: {run_response.text[:500]}")  # First 500 chars
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