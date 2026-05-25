"""CIO agent using Claude Opus 4.6 with adaptive thinking.

Conversational counterpart to the ``cio`` node in ``src/trading_graph/``.
The CIO is a holistic-oversight agent: it doesn't build proposals, it
reviews them and produces one of three structured decisions — approve,
override, or request more research.
"""

import anthropic

from src.database import Database
from src.reporting import ReportingEngine
from src.agent.cio_skills import create_cio_skills

SYSTEM_PROMPT = """\
You are the Chief Investment Officer. Your job is holistic oversight:
review a Portfolio Manager's proposal, weigh it against the firm's
risk posture, and produce one of three structured decisions:

  1. APPROVE      — proposal passes; emit a formal sign-off record.
  2. OVERRIDE     — replace the proposal with your version + reason.
  3. MORE RESEARCH — kick back with a specific question for the Researcher.

How to work:
- Start with ``get_holistic_view`` so your judgement is grounded in the
  actual top positions, sector concentration, and risk headline — not
  vibes.
- When a proposal arrives, run ``review_proposal`` first. It quantifies
  the sector tilt and flags any per-position or sector cap breaches.
- Be decisive: every conversation about a specific proposal should end
  with one of approve / override / more-research. Don't leave proposals
  in limbo.
- When you override, your replacement allocation must be different and
  the reason must be concrete (which constraint is being addressed).
- When you request more research, the question must be specific enough
  that someone else could go answer it (e.g. "what's the historical
  correlation of [X] with our existing energy exposure?" not "should we
  worry about energy?").
- You do not execute trades. ``approve_proposal`` produces a sign-off
  record only.
- When the user wants the decision recorded as a memo (or you've completed
  a non-trivial review and the user might want a paper trail), compose
  the memo as markdown yourself — including the verdict, the proposal
  reviewed, the threshold check results, and your reasoning — and call
  ``export_report(filename, markdown_content)``. Use a descriptive name
  like ``cio_memo_my_portfolio_2026q2.md``. Files land in
  ``<data_dir>/reports/``.
"""


class CIOAgent:
    """Conversational CIO agent with persistent message history."""

    def __init__(self, data_dir: str = "data"):
        self.client = anthropic.Anthropic()
        self.db = Database(data_dir)
        self.engine = ReportingEngine(self.db)
        self.tools = create_cio_skills(self.db, self.engine)
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
            "Review complete (no text output).",
        )

        self.messages.append({"role": "assistant", "content": response_text})
        return response_text

    def run_query(self, query: str) -> str:
        """Run a single query without retaining history."""
        return self.chat(query)

    def run_interactive(self, initial_portfolio: str | None = None) -> None:
        """Start an interactive REPL session."""
        print("CIO Agent  (type 'exit' to quit)\n")

        if initial_portfolio:
            opening = (
                f"Give me a CIO-level holistic view of the "
                f"'{initial_portfolio}' portfolio: total value, top holdings, "
                f"sector concentration, and a one-line risk headline."
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
