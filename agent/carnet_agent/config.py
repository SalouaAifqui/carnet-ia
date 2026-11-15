"""Settings for the Carnet IA agent.

Everything you might want to tune lives here: models, limits and the site's topics.
Models can be overridden with environment variables without touching the code.
"""
import os

# --- Models: one per role -----------------------------------------------------
# Each role can use a different model; change them with environment variables, no code change.
# DeepSeek models are 3 to 5 times cheaper than gpt-5.4-mini; the writer stays on OpenAI until
# a comparison shows DeepSeek writes as well.
MODELS = {
    "read": os.getenv("CARNET_MODEL_READ", "deepseek:deepseek-flash"),          # read sources and lessons
    "plan": os.getenv("CARNET_MODEL_PLAN", "deepseek:deepseek-flash"),          # librarian: where things go, outlines
    "research": os.getenv("CARNET_MODEL_RESEARCH", "deepseek:deepseek-flash"),  # find gaps, pick findings
    "write": os.getenv("CARNET_MODEL_WRITE", "openai:gpt-5.4-mini"),            # write the pages
    "review": os.getenv("CARNET_MODEL_REVIEW", "openai:gpt-5.4-mini"),          # check details against the source
}

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
    "evaluation": ("Evaluation & Guardrails", "t-eval"),
}

# The site never cites itself: these URLs are dropped from search results and sources.
SELF_URLS = ["salouaaifqui.github.io/carnet-ia", "github.com/SalouaAifqui/carnet-ia"]

# Sources we trust more when the agent searches the web.
PREFERRED_DOMAINS = [
    "docs.langchain.com", "langchain-ai.github.io", "python.langchain.com",
    "platform.openai.com", "openai.com", "docs.anthropic.com", "anthropic.com",
    "ai.google.dev", "huggingface.co", "arxiv.org", "deeplearning.ai",
    "docs.tavily.com", "github.com", "docs.python.org", "pydantic.dev",
]
