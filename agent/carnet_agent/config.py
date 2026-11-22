"""Settings for the Carnet IA agent.

Everything you might want to tune lives here: models, limits and the site's topics.
Models can be overridden with environment variables without touching the code.
"""
import os

# --- Models: one per role -----------------------------------------------------
# Change any of them with an environment variable (CARNET_MODEL_<ROLE>), no code change.
# nano for simple, high-volume tasks; mini where quality matters. DeepSeek also works
# ("deepseek:deepseek-flash"), but costs were not lower in our comparison.
MODELS = {
    "read": os.getenv("CARNET_MODEL_READ", "openai:gpt-5.4-nano"),          # read course lessons
    "plan": os.getenv("CARNET_MODEL_PLAN", "openai:gpt-5.4-mini"),          # 1. librarian
    "write": os.getenv("CARNET_MODEL_WRITE", "openai:gpt-5.4-mini"),        # 2. write each part
    "check": os.getenv("CARNET_MODEL_CHECK", "openai:gpt-5.4-nano"),        # 3. check details per part
    "edit": os.getenv("CARNET_MODEL_EDIT", "openai:gpt-5.4-mini"),          # 4. summary, concepts, Remember
    "research": os.getenv("CARNET_MODEL_RESEARCH", "openai:gpt-5.4-nano"),  # 6. propose web facts
}
# 7. the illustrator draws the synthesis visual (SVG). Same model as the editor unless set.
ILLUSTRATOR_MODEL = os.getenv("ILLUSTRATOR_MODEL") or os.getenv("CARNET_MODEL_ILLUSTRATE") or MODELS["edit"]
MODELS["illustrate"] = ILLUSTRATOR_MODEL

# $ per 1M tokens (input, output), to track the cost of each run.
PRICES = {
    "gpt-5.4-nano": (0.20, 1.25),
    "gpt-5.4-mini": (0.75, 4.50),
    "gpt-5.4": (2.50, 15.00),
    "deepseek-flash": (0.30, 1.20),
    "deepseek-v4-pro": (1.32, 3.96),
}
MAX_COST = float(os.getenv("CARNET_MAX_COST", "0.50"))          # $ per run; the run stops above it
MAX_COST_COURSE = float(os.getenv("CARNET_MAX_COST_COURSE", "3.00"))

# Web research proposals (step 6). Set CARNET_RESEARCH=0 to skip it entirely.
RESEARCH = os.getenv("CARNET_RESEARCH", "1") != "0"

# --- Limits -----------------------------------------------------------------
MAX_QUERIES = 3              # web searches per research round
RESULTS_PER_QUERY = 3        # results kept per search
MAX_SOURCE_CHARS = 60_000    # we cut very long pages so prompts stay affordable

# --- Site structure ---------------------------------------------------------
# folder name -> (label shown on the site, CSS class that gives the topic its color)
TOPICS = {
    "llms": ("LLMs", "t-llms"),
    "agents": ("Agents", "t-agents"),
    "evaluation": ("Evaluation & Guardrails", "t-eval"),
    "toolbox": ("Toolbox", "t-tools"),
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
