from google.adk.agents.llm_agent import Agent
from google.adk.tools.agent_tool import AgentTool
from agents.trading_tools import list_events, search_events_and_markets
from agents.strategy_tools import create_strategy, get_active_strategies
from agents.user_tools import get_cash_balance, get_user_positions
from agents.search_agent import google_search_agent
from agents import prompts

root_agent = Agent(
    model='gemini-2.5-pro',
    name='strategy_agent',
    description='A specialized strategy analyst for Polymarket that researches markets and drafts comprehensive trading strategies.',
    instruction=prompts.STRATEGY_AGENT_INSTRUCTION,
    tools=[
        # Strategy management
        get_active_strategies,
        create_strategy,
        # Portfolio state
        get_cash_balance,
        get_user_positions,
        # Market exploration
        list_events,
        search_events_and_markets,
        # Research
        AgentTool(agent=google_search_agent),
    ],
)

