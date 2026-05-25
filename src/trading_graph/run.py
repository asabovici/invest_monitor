"""CLI smoke test entrypoint.

Full prompt-wired version lands in Section 9 step 9; this stub-driven runner
exists now so the graph is executable end to end during development.
"""

from __future__ import annotations

from pprint import pprint

from .config import Settings
from .graph import build_graph
from .state import initial_state


def main(human_in_the_loop: bool = False) -> None:
    settings = Settings(human_in_the_loop=human_in_the_loop)
    app = build_graph(settings)
    config = {"configurable": {"thread_id": "smoke-1"}}

    final = app.invoke(initial_state(), config=config)
    if human_in_the_loop:
        # First invocation pauses before CIO; resume by invoking with None.
        final = app.invoke(None, config=config)

    print("=== final state ===")
    pprint({k: v for k, v in final.items() if k != "messages"})
    print("\n=== messages ===")
    for m in final["messages"]:
        print(f"- {m.content}")


if __name__ == "__main__":
    main()
