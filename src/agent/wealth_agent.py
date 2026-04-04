"""Wealth management agent using Claude Opus 4.6 with adaptive thinking.

Focused on financial goal planning, returns, rebalancing, portfolio
optimisation, and tax efficiency — areas not covered by the risk agent.
"""

import anthropic

from src.database import Database
from src.reporting import ReportingEngine
from src.agent.wealth_skills import create_wealth_skills

SYSTEM_PROMPT = """\
You are a personal wealth management advisor. Your role is to help clients
grow and preserve their wealth through sound portfolio management, goal
planning, and tax-efficient investing.

You have tools to assess current portfolio value and returns, score
diversification, suggest rebalancing trades, project goal achievement
probability, find tax-loss harvesting opportunities, and optimise allocation
using mean-variance analysis.

How to approach conversations:
- Always fetch real data with tools before making specific recommendations.
- Frame advice in terms of the client's goals and time horizon.
- Be concrete: quote specific dollar amounts, percentages, and trade sizes.
- When suggesting rebalancing or optimisation, explain the trade-off clearly.
- Always attach the disclaimer that this is not financial or tax advice when
  discussing tax matters or specific investment recommendations.
- If price data is missing, direct the user to:
    invest-monitor collect --portfolio <name>
"""


class WealthAgent:
    """Conversational wealth management agent with persistent message history."""

    def __init__(self, data_dir: str = "data"):
        self.client = anthropic.Anthropic()
        self.db = Database(data_dir)
        self.engine = ReportingEngine(self.db)
        self.tools = create_wealth_skills(self.db, self.engine)
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
            "Analysis complete (no text output).",
        )

        self.messages.append({"role": "assistant", "content": response_text})
        return response_text

    def run_query(self, query: str) -> str:
        """Run a single query without retaining history."""
        return self.chat(query)

    def run_interactive(self, initial_portfolio: str | None = None) -> None:
        """Start an interactive REPL session."""
        print("Wealth Management Agent  (type 'exit' to quit)\n")

        if initial_portfolio:
            opening = (
                f"Please give me a full wealth management overview of the "
                f"'{initial_portfolio}' portfolio — current value, returns, "
                f"diversification, and any actionable recommendations."
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
