import os
import textwrap
from google.adk.agents.llm_agent import Agent
from google.adk.models.lite_llm import LiteLlm
from google.adk.models.anthropic_llm import Claude
from google.adk.models.registry import LLMRegistry
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

LLMRegistry.register(Claude)

KALSHI_AGENT_INSTRUCTION = textwrap.dedent("""\
    You are a Kalshi trading agent for a SIMULATED paper trading account.
    
    ## Your Role
    Research markets, create trading strategies, and manage a prediction market portfolio.
    
    ## Strategy Constraints
    - Maximum 10 active strategies at any time
    - Only 1 strategy per ticker (if a ticker has a strategy, update or remove it first)
    - Risk limits: 5% min edge, $200 max per strategy, 1000 shares max
    
    ## Workflow
    1. Check active strategies with get_active_kalshi_strategies()
    2. Browse markets with list_new_markets()
    3. Research opportunities with google_search_agent
    4. Create strategies with create_kalshi_strategy() (provide ticker, side, thesis, thesis_probability, entry_max_price, exit_take_profit_price, exit_stop_loss_price)
    5. Update or remove strategies as market conditions change
    
    ## Strategy Side
    - side="yes": Betting that the event WILL happen (default)
    - side="no": Betting that the event will NOT happen
    
    ## Guidelines
    - Check portfolio and positions before trading
    - Research thoroughly before creating strategies
    - Each strategy needs a clear thesis with probability estimate
    - Set realistic entry/exit prices based on your analysis
    - Monitor active strategies and adjust as needed
    """)


# Initialize LiteLLM with OpenAI model
# Note: Ensure OPENAI_API_KEY environment variable is set
openai_model = LiteLlm(
    model="openai/gpt-5.2",  # LiteLLM format: provider/model
    api_key=os.getenv("OPENAI_API_KEY")
)

# Gemini via Vertex AI (direct string, no LiteLLM wrapper needed)
# Region: global
gemini_model = 'gemini-3-pro-preview'

# Claude via LiteLLM with Vertex AI as provider
# Requires: GOOGLE_CLOUD_PROJECT and GOOGLE_CLOUD_LOCATION env vars
claude_model = LiteLlm(
    model='vertex_ai/claude-sonnet-4@20250514', 
    vertex_project=os.getenv("GOOGLE_CLOUD_PROJECT"),
    vertex_location="global"
)

# Grok via XAI
# Requires: XAI_API_KEY environment variable is set
grok_model = LiteLlm(
    model='xai/grok-4-1-fast-reasoning',
    api_key=os.getenv("XAI_API_KEY"),
)

# Qwen via Vertex AI Model Garden (MaaS)
# Format for MaaS models: vertex_ai/{model-id}
qwen_model = LiteLlm(
    model='vertex_ai/qwen/qwen3-235b-a22b-instruct-2507-maas',
    vertex_project=os.getenv("GOOGLE_CLOUD_PROJECT"),
    vertex_location='us-south1'
)

# Kimi via Vertex AI
kimi_model = LiteLlm(
    model='vertex_ai/moonshotai/kimi-k2-thinking-maas',
    vertex_project=os.getenv("GOOGLE_CLOUD_PROJECT"),
    vertex_location="global"
)

# Dictionary mapping model names to model instances
AVAILABLE_MODELS = {
    'openai': openai_model,
    'gemini': gemini_model,
    'claude': claude_model,
    'grok': grok_model,
    'qwen': qwen_model,
    'kimi': kimi_model,
}


def create_kalshi_agent(model_name: str = 'gemini') -> Agent:
    """
    Create a Kalshi trading agent with the specified model.
    
    Args:
        model_name: Name of the model to use. Options: 'openai', 'gemini', 'claude', 'grok', 'qwen', 'kimi'
                   Defaults to 'gemini'.
    
    Returns:
        Agent configured with the specified model.
    
    Raises:
        ValueError: If the model_name is not in AVAILABLE_MODELS.
    """
    if model_name not in AVAILABLE_MODELS:
        available = ', '.join(AVAILABLE_MODELS.keys())
        raise ValueError(f"Model '{model_name}' not found. Available models: {available}")
    
    model = AVAILABLE_MODELS[model_name]
    
    return Agent(
        model=model,
        name='kalshi_agent',
        description='Kalshi paper trading agent: research markets, create automated strategies (max 10, one per ticker), and manage portfolio.',
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


# Create default agent with Gemini
root_agent = create_kalshi_agent('openai')