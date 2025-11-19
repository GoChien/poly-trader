from google.adk.agents.llm_agent import Agent
from agents.trading_tools import list_events, search_events_and_markets, place_order_at_market_price
from agents.user_tools import get_cash_balance, get_user_positions
from agents.memory_tools import read_strategy_note, overwrite_strategy_note
from agents.search_agent import google_search_agent
from google.adk.tools.agent_tool import AgentTool

root_agent = Agent(
    model='gemini-2.5-flash',
    name='root_agent',
    description='A helpful assistant for user questions.',
    instruction='Answer user questions to the best of your knowledge',
    tools=[list_events, search_events_and_markets,
           place_order_at_market_price, AgentTool(agent=google_search_agent), read_strategy_note, overwrite_strategy_note, get_cash_balance, get_user_positions],
)
