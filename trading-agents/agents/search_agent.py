from google.adk.agents import Agent
from google.adk.tools import google_search


# The google_search is a special built-in tools that it has to be operated by a dedicated agent (otherwise will raise error).
google_search_agent = Agent(
    model='gemini-2.5-flash',
    name='google_search_agent',
    description='A search agent that uses google search to get latest information about events and markets.',
    instruction='Use google search to answer user questions about real-time information of any events or markets.',
    tools=[google_search],
)
