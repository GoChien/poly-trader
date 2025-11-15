from google.adk.agents.llm_agent import Agent
from agents.trading_tools import list_events, get_market_price, place_order

root_agent = Agent(
    model='gemini-2.5-flash',
    name='root_agent',
    description='A helpful assistant for user questions.',
    instruction='Answer user questions to the best of your knowledge',
    tools=[list_events, get_market_price, place_order],
)
