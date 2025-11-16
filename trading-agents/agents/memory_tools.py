from google.adk.tools import ToolContext

# Use the 'user:' prefix for persistence across sessions
NOTEBOOK_KEY = "user:long_term_strategy_note"


def read_strategy_note(tool_context: ToolContext) -> str:
    """
    Reads the agent's persistent long-term polymarket trading strategy note.

    Returns:
        str: The content of the strategy note.
    """
    return tool_context.state.get(NOTEBOOK_KEY, "The notebook is currently empty.")


def overwrite_strategy_note(note_content: str, tool_context: ToolContext) -> None:
    """
    Overwrites the agent's persistent long-term polymarket trading strategy note.

    Args:
        note_content (str): The content to overwrite into the strategy note.
    """
    # Use the 'user:' prefix for persistence across sessions
    NOTEBOOK_KEY = "user:long_term_strategy_note"
    tool_context.state[NOTEBOOK_KEY] = note_content
