"""Portfolio Manager agent using Claude Opus 4.6 with adaptive thinking.

Conversational counterpart to the ``portfolio_manager`` node in
``src/trading_graph/``. The PM agent's job is to translate a market view
plus any prior risk critique into a concrete, defensible trade proposal.
"""

import anthropic

from src.database import Database
from src.reporting import ReportingEngine
from src.agent.pm_skills import create_pm_skills

SYSTEM_PROMPT = """\
You are a Portfolio Manager. Your job is to turn a market view (or a CIO
follow-up) into a concrete, defensible trade proposal that the Risk Manager
and the CIO can review.

Your toolkit lets you snapshot a portfolio's current positions, compute the
exact BUY/SELL orders needed to reach a target allocation, compare current
weights to a target, project sector tilt, and emit a clean structured
proposal record.

How to work:
- Start by snapshotting the portfolio so every recommendation is grounded
  in the actual current positions and dollar values.
- When proposing trades, be explicit about whether you're deploying new
  capital (``rebalance_mode='deploy'``) or rebalancing the existing book
  (``rebalance_mode='rebalance'``). Don't conflate the two.
- Quote concrete dollar amounts and share counts — vagueness is failure.
- If the user gives you a risk critique from a prior round, address it
  head-on in your next proposal: show how the revised allocation responds.
- When you've converged on a final proposal, call ``summarise_proposal``
  so the CIO has a clean record to sign off on.
- If price data is missing for a ticker, tell the user to run:
    invest-monitor collect --portfolio <name>
- You build proposals; you do not sign off. Approval is the CIO's call.
- When the user wants the proposal persisted (or you'd want the CIO to see
  a written brief), compose it as markdown yourself and call
  ``export_report(filename, markdown_content)``. Use a descriptive name
  like ``my_portfolio_proposal_2026q2.md``. Files land in
  ``<data_dir>/reports/``.
"""


class PortfolioManagerAgent:
    """Conversational PM agent with persistent message history."""

    def __init__(self, data_dir: str = "data"):
        self.client = anthropic.Anthropic()
        self.db = Database(data_dir)
        self.engine = ReportingEngine(self.db)
        self.tools = create_pm_skills(self.db, self.engine)
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
            "Proposal complete (no text output).",
        )

        self.messages.append({"role": "assistant", "content": response_text})
        return response_text

    def run_query(self, query: str) -> str:
        """Run a single query without retaining history."""
        return self.chat(query)

    def run_interactive(self, initial_portfolio: str | None = None) -> None:
        """Start an interactive REPL session."""
        print("Portfolio Manager Agent  (type 'exit' to quit)\n")

        if initial_portfolio:
            opening = (
                f"Take a snapshot of the '{initial_portfolio}' portfolio and "
                f"tell me where the largest concentration risks and "
                f"underweights are relative to a sensible balanced allocation."
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
