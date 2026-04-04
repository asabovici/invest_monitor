"""Skills-based risk management agent using Claude Opus 4.6 with adaptive thinking.

The agent exposes a set of risk analysis skills as tools and uses the Anthropic
tool runner to automatically handle multi-step analysis loops. Multi-turn
conversation history is maintained across calls so users can ask follow-up
questions without repeating context.
"""

import sys
import anthropic

from src.database import Database
from src.reporting import ReportingEngine
from src.agent.skills import create_risk_skills

SYSTEM_PROMPT = """\
You are an expert investment risk management analyst. Your job is to help users
understand and manage risk in their investment portfolios.

You have tools to query portfolio data, compute risk metrics, check concentration,
analyse correlations, and measure drawdowns. Use them proactively — always pull
the actual numbers before drawing conclusions.

Guidelines:
- Quantify risk with specific figures wherever possible.
- Flag concentration risk (single position >20% of portfolio), high correlations
  (>0.7 between any pair), and tail risk (large VaR or drawdown).
- Suggest concrete, actionable steps to reduce identified risks.
- Be direct about downside scenarios — investors need honest assessments.
- When price data is unavailable, tell the user to run:
    invest-monitor collect --portfolio <name>
"""


class RiskAgent:
    """Conversational risk management agent.

    Maintains multi-turn message history so users can ask follow-up questions.
    """

    def __init__(self, data_dir: str = "data"):
        self.client = anthropic.Anthropic()
        self.db = Database(data_dir)
        self.engine = ReportingEngine(self.db)
        self.tools = create_risk_skills(self.db, self.engine)
        self.messages: list = []

    def chat(self, user_input: str) -> str:
        """Send a user message and return the agent's text response.

        The tool runner automatically handles any tool calls Claude makes,
        looping until the model returns a final text answer.
        """
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

        # Store only the text in history to avoid thinking-block issues on
        # subsequent turns while still preserving conversational context.
        self.messages.append({"role": "assistant", "content": response_text})

        return response_text

    def run_query(self, query: str) -> str:
        """Run a single query and return the result (no history retained)."""
        return self.chat(query)

    def run_interactive(self, initial_portfolio: str | None = None) -> None:
        """Start an interactive REPL session with optional opening context."""
        print("Investment Risk Management Agent  (type 'exit' to quit)\n")

        if initial_portfolio:
            opening = (
                f"I'd like a comprehensive risk assessment for the "
                f"'{initial_portfolio}' portfolio."
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
