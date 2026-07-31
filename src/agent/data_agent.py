"""Data-correction agent — diagnoses and repairs the stored record.

The other five agents read the database and reason about it. This one is the
only agent that changes it, so its skills are built on a preview/apply gate:
the model proposes a diff, the human approves, and only then does anything land
on disk. The system prompt below exists mostly to keep the model on the correct
side of that line.
"""

import anthropic

from src.database import Database
from src.reporting import ReportingEngine
from src.agent.data_skills import create_data_skills

SYSTEM_PROMPT = """\
You are a meticulous investment-data steward. You help the user find and correct
bad data in their portfolio database: positions, the security master, price
history, and fund holdings.

You are the only agent that can modify stored records, so accuracy matters more
than speed. Work in this order:

1. **Diagnose before proposing.** Run scan_data, show_trades, or list_price_gaps
   and look at the real values first. Never infer what is wrong from the user's
   description alone — they may be describing a symptom rather than the cause.
2. **Propose a specific change.** The fix tools return a diff and a change id and
   write nothing. Show the user the diff, in full, including every warning,
   before asking whether to apply it.
3. **Apply only on explicit approval.** Call apply_change strictly after the user
   has said yes to that particular change. If they approved one change, that is
   not approval for others you have staged.

Rules that matter:

- **cost_basis is PER SHARE, never a total.** Storing a total causes
  double-counting everywhere downstream. If a proposed cost basis is suspiciously
  close to quantity x price, stop and check with the user before continuing.
- **Positions are derived from the trade ledger.** To correct a position
  retroactively, correct the underlying trade (correct_trade / insert_trade /
  delete_trade) and let the replay recompute it. Reach for seed_opening_balance
  when a position has no trades at all — typically an imported opening balance.
- **Never claim a change was applied until apply_change has returned success.**
  A returned diff means nothing has been written yet. Be precise about this;
  the user is relying on you to know the difference.
- **Fill-forward is a last resort for prices.** Carrying a stale price across a
  long gap flatters volatility and drawdown. Prefer collecting real prices; if
  you do fill, say how many days were synthesised.
- Report what the tools actually returned. If a tool returns an error, relay it
  rather than trying a different tool until something succeeds.

Be concise and concrete. Quote tickers, dates, and numbers.
"""


class DataAgent:
    """Conversational data-correction agent with an approval gate on writes."""

    def __init__(self, data_dir: str = "data"):
        self.client = anthropic.Anthropic()
        self.db = Database(data_dir)
        self.engine = ReportingEngine(self.db)
        self.tools = create_data_skills(self.db, self.engine)
        self.messages: list = []

    def chat(self, user_input: str) -> str:
        """Send a user message and return the agent's text response."""
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
            "Done (no text output).",
        )

        # Only the final text goes into history — thinking blocks would be
        # rejected by the tool runner on the next turn.
        self.messages.append({"role": "assistant", "content": response_text})

        return response_text

    def run_query(self, query: str) -> str:
        """Run a single query and return the result (history still retained)."""
        return self.chat(query)

    def run_interactive(self, initial_scan: bool = False) -> None:
        """Start an interactive REPL, optionally opening with a full scan."""
        print("Investment Data Agent  (type 'exit' to quit)\n")

        if initial_scan:
            opening = "Scan the database for data-integrity issues and summarise what you find."
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
