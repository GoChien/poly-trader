import textwrap
from google.adk.agents.llm_agent import Agent
from kalshi_strategy_agent.kalshi_tools import (
    create_kalshi_strategy,
    get_active_kalshi_strategies,
    get_kalshi_balance,
    get_kalshi_positions,
    list_new_markets,
    remove_kalshi_strategy,
    update_kalshi_strategy,
)
from agents.search_agent import google_search_agent
from google.adk.tools.agent_tool import AgentTool


KALSHI_AGENT_INSTRUCTION = textwrap.dedent("""\
    You are a Kalshi trading assistant that helps clients manage their Kalshi prediction market portfolio.
    This is a SIMULATED ACCOUNT for paper trading - all trades and suggestions are for learning purposes.
    
    Your role is to:
    1. Monitor account balance and portfolio value
    2. Review current positions across markets and events
    3. Analyze available markets and identify trading opportunities
    4. Create and manage automated trading strategies
    5. Provide data-driven trading suggestions and insights
    """)


root_agent = Agent(
    model='gemini-2.5-pro',
    name='kalshi_agent',
    description='A Kalshi trading agent that monitors portfolios, analyzes markets, creates and updates automated strategies, and provides data-driven trading suggestions for simulated paper trading.',
    instruction=KALSHI_AGENT_INSTRUCTION,
    tools=[
        # Strategy Management
        get_active_kalshi_strategies,
        create_kalshi_strategy,
        update_kalshi_strategy,
        remove_kalshi_strategy,
        # Portfolio state
        get_kalshi_balance,
        get_kalshi_positions,
        # Market discovery
        list_new_markets,
        # Research
        AgentTool(agent=google_search_agent),
    ],
)

