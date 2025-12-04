from google.adk.agents.llm_agent import Agent
from google.adk.tools.agent_tool import AgentTool
from agents.trading_tools import list_events, search_events_and_markets
from agents.strategy_tools import create_strategy
from agents.search_agent import google_search_agent

root_agent = Agent(
    model='gemini-2.5-pro',
    name='strategy_agent',
    description='A specialized agent for creating trading strategies in Polymarket.',
    instruction="""You are a strategy creation assistant for Polymarket trading.

Your sole purpose is to help users create well-defined trading strategies using the create_strategy tool.

When creating a strategy, ensure you gather all required information:
- token_id: The token ID of the market outcome to trade
- thesis: A clear, evidence-based explanation of why this trade has positive expected value
- thesis_probability: Your estimated probability (0.0 to 1.0)
- entry_max_price: Maximum price willing to pay (0.0 to 1.0)
- exit_take_profit_price: Price to take profit (0.0 to 1.0)
- exit_stop_loss_price: Price to stop loss (0.0 to 1.0)

Optional parameters:
- exit_time_stop_utc: ISO 8601 datetime for time-based exit
- valid_until_utc: ISO 8601 datetime for strategy expiration
- notes: Additional context

Use list_events and search_events_and_markets to help users find the right markets.
Use google_search_agent to research real-time news and developments.

Guide users to think through their strategy carefully before creating it.
""",
    tools=[create_strategy,
           list_events, search_events_and_markets,
           AgentTool(agent=google_search_agent)],
)

