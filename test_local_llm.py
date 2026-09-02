"""Manual smoke test: send one hardcoded prompt to the local model and print the result.

Usage:  python test_local_llm.py
"""

from __future__ import annotations

from local_llm_mcp.server import _endpoint, _model, delegate_to_local

PROMPT = "Write a Python function named add that takes two ints and returns their sum. Code only."


def main() -> None:
    print(f"endpoint: {_endpoint()}")
    print(f"model:    {_model()}\n")
    print(delegate_to_local(PROMPT, system_prompt="You are a terse code generator."))


if __name__ == "__main__":
    main()
