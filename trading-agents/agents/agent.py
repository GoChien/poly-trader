from google.adk.agents.llm_agent import Agent
from agents.trading_tools import list_events, search_events_and_markets, place_order, cancel_order
from agents.user_tools import get_cash_balance, get_user_positions, get_active_orders
from agents.memory_tools import read_strategy_note, overwrite_strategy_note
from agents.search_agent import google_search_agent
from google.adk.tools.agent_tool import AgentTool
from agents import prompts

root_agent = Agent(
    model='gemini-2.5-pro',
    name='root_agent',
    description='An intelligent Polymarket trading agent that manages portfolios and executes trades in a simulated prediction market.',
    instruction=prompts.TRADING_INSTRUCTION,
    tools=[list_events, search_events_and_markets,
           place_order, cancel_order,
           AgentTool(agent=google_search_agent),
           read_strategy_note, overwrite_strategy_note,
           get_cash_balance, get_user_positions, get_active_orders],
)
