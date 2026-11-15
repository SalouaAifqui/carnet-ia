"""Settings for the Carnet IA agent.

Everything you might want to tune lives here: models, limits and the site's topics.
Models can be overridden with environment variables without touching the code.
"""
import os

# --- Models -----------------------------------------------------------------
# One model does the everyday work (reading, routing, writing).
# The reviewer can be a stronger model: it is the last check before a human.
MODEL = os.getenv("CARNET_MODEL", "openai:gpt-5.4-mini")
REVIEW_MODEL = os.getenv("CARNET_REVIEW_MODEL", "openai:gpt-5.4-mini")

# --- Limits -----------------------------------------------------------------
MAX_REVISIONS = 2            # write → review loops before we stop and open the PR anyway
MAX_QUERIES = 3              # web searches per research round
RESULTS_PER_QUERY = 3        # results kept per search
MAX_TOOL_CALLS = 4           # tool calls allowed inside the write / review nodes
MAX_SOURCE_CHARS = 60_000    # we cut very long pages so prompts stay affordable

# --- Site structure ---------------------------------------------------------
# folder name -> (label shown on the site, CSS class that gives the topic its color)
TOPICS = {
    "llms": ("LLMs", "t-llms"),
    "agents": ("Agents", "t-agents"),
    "guardrails": ("Guardrails", "t-guardrails"),
    "daily-use": ("Daily Use", "t-daily"),
}

# Sources we trust more when the agent searches the web.
PREFERRED_DOMAINS = [
    "docs.langchain.com", "langchain-ai.github.io", "python.langchain.com",
    "platform.openai.com", "openai.com", "docs.anthropic.com", "anthropic.com",
    "ai.google.dev", "huggingface.co", "arxiv.org", "deeplearning.ai",
    "docs.tavily.com", "github.com", "docs.python.org", "pydantic.dev",
]
