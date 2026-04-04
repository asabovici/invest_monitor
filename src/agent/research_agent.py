"""Investment research agent using Claude Opus 4.6 with adaptive thinking and web search.

Helps users find the best way to deploy capital given constraints such as
sector exposure limits, VaR budgets, and drawdown ceilings.  Combines
live web search (Anthropic-hosted) with portfolio simulation tools to
research candidates and stress-test proposed allocations before committing.
"""

import anthropic

from src.database import Database
from src.reporting import ReportingEngine
from src.agent.research_skills import create_research_skills

# Server-side web search tool — resolved by Anthropic's infrastructure before
# the response reaches the tool runner, so it composes cleanly with @beta_tool skills.
_WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search"}

SYSTEM_PROMPT = """\
You are an expert investment research analyst.  Your job is to help clients
deploy capital in a way that meets specific portfolio constraints.

You have two categories of tools:

1. Web search — use this to discover candidate investments, read analyst
   commentary, check sector classifications, and find ETFs or funds that
   give targeted exposure.

2. Portfolio tools — use these to baseline the existing portfolio, look up
   asset details, fetch price history, and simulate how proposed allocations
   would change risk and exposure metrics.

Typical research workflow
─────────────────────────
1. get_portfolio_baseline  — understand current VaR, drawdown, sector weights.
2. web search              — find candidates that fit the stated constraints.
3. lookup_asset_info       — verify sector, type, beta, and price for each candidate.
4. fetch_asset_prices      — pull price history for candidates not yet in the DB.
5. simulate_allocation     — model the combined portfolio and inspect the deltas.
6. Iterate                 — refine the allocation until all constraints are satisfied.
7. Present a ranked shortlist with reasoning and concrete position sizes.

Guidelines
──────────
- Always quantify constraints: translate "don't increase VaR" into a specific
  numerical comparison between baseline and simulated values.
- Prefer candidates with low correlation to the existing portfolio (below 0.5
  with the current holdings) — diversification is often the real goal.
- When a constraint cannot be fully satisfied, explain the trade-off clearly
  and suggest the closest feasible alternative.
- Cite sources (URLs or publication names) for any external research claims.
- State that recommendations are for informational purposes only and not
  financial advice.
"""


class ResearchAgent:
    """Conversational investment research agent with web search and portfolio simulation."""

    def __init__(self, data_dir: str = "data"):
        self.client = anthropic.Anthropic()
        self.db = Database(data_dir)
        self.engine = ReportingEngine(self.db)
        self.skills = create_research_skills(self.db, self.engine)
        # Mix server-side web search with user-defined @beta_tool skills
        self.tools = [_WEB_SEARCH_TOOL, *self.skills]
        self.messages: list = []

    def chat(self, user_input: str) -> str:
        """Send a message and return the agent's response."""
        self.messages.append({"role": "user", "content": user_input})

        runner = self.client.beta.messages.tool_runner(
            model="claude-opus-4-6",
            max_tokens=16000,
            thinking={"type": "adaptive"},
            system=SYSTEM_PROMPT,
            tools=self.tools,
            messages=self.messages,
        )

        last_message = None
        for message in runner:
            last_message = message

        if last_message is None:
            return "No response received from the model."

        response_text = next(
            (block.text for block in last_message.content if block.type == "text"),
            "Research complete (no text output).",
        )

        self.messages.append({"role": "assistant", "content": response_text})
        return response_text

    def run_query(self, query: str) -> str:
        """Run a single query without retaining history."""
        return self.chat(query)

    def run_interactive(self, initial_portfolio: str | None = None) -> None:
        """Start an interactive REPL session."""
        print("Investment Research Agent  (type 'exit' to quit)\n")

        if initial_portfolio:
            opening = (
                f"Please baseline the '{initial_portfolio}' portfolio — show me "
                f"its current VaR, max drawdown, and sector exposure so we have "
                f"a reference point before researching new investments."
            )
            print(f"You: {opening}")
            print(f"\nAgent: {self.chat(opening)}\n")

        while True:
            try:
                user_input = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nSession ended.")
                break

            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit", "q"):
                print("Session ended.")
                break

            print(f"\nAgent: {self.chat(user_input)}\n")
