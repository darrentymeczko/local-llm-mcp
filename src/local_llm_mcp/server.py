"""A one-tool MCP server that forwards prompts to a local OpenAI-compatible LLM."""

from __future__ import annotations

import os
import pathlib
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer

DEFAULT_ENDPOINT = "http://localhost:8081/v1/chat/completions"
DEFAULT_MODEL = "lmstudio-community/gpt-oss-20b-GGUF:MXFP4"
DEFAULT_TIMEOUT = 60.0

TOOL_DESCRIPTION = (
    "Delegate a small, well-defined, low-judgment coding subtask to a fast local LLM "
    "instead of doing it yourself. Best for: boilerplate generation, straightforward "
    "formatting/refactors, docstring/comment generation, simple repetitive "
    "transformations across files, extracting function signatures, writing simple test "
    "stubs. NOT suitable for: anything requiring deep reasoning about this specific "
    "codebase, multi-step planning, ambiguous requirements, or tasks where correctness "
    "is hard to verify quickly. The local model has less capability than you do -- "
    "always be prepared to review and correct its output rather than trusting it blindly. "
    "Pass output_path to have the generated text written straight to a new file instead "
    "of returned to you; this keeps large output out of your context, but you then have "
    "not seen it, so read or test the file before relying on it."
)

mcp = MCPServer("local-llm")


def _endpoint() -> str:
    return os.environ.get("LOCAL_LLM_ENDPOINT", DEFAULT_ENDPOINT)


def _model() -> str:
    return os.environ.get("LOCAL_LLM_MODEL", DEFAULT_MODEL)


def _start_hint() -> str:
    """Command the user configured for starting their local server, if any."""
    return os.environ.get("LOCAL_LLM_START_HINT", "").strip()


def _timeout() -> float:
    try:
        return float(os.environ.get("LOCAL_LLM_TIMEOUT", DEFAULT_TIMEOUT))
    except ValueError:
        return DEFAULT_TIMEOUT


def _write_output(output_path: str, content: str) -> str:
    """Write generated text to a new file, returning a summary instead of the text."""
    path = pathlib.Path(output_path).expanduser()
    if path.exists():
        return (
            f"Refusing to overwrite the existing file {path}. Delegated output is "
            "unreviewed, so this tool only creates new files. Choose another path, or "
            "delete the file yourself first if replacing it is what you intend."
        )
    if not path.parent.is_dir():
        return f"Cannot write to {path}: the directory {path.parent} does not exist."
    try:
        path.write_text(content, encoding="utf-8")
    except OSError as exc:
        return f"Cannot write to {path}: {exc}"
    return (
        f"Wrote {len(content)} characters ({content.count(chr(10)) + 1} lines) to {path}. "
        "The content was not returned, so you have not seen it. Read the file, or run "
        "its tests, before relying on it."
    )


@mcp.tool(name="delegate_to_local", description=TOOL_DESCRIPTION)
def delegate_to_local(
    prompt: str, system_prompt: str = "", output_path: str = ""
) -> str:
    """Send `prompt` (optionally preceded by `system_prompt`) to the local model.

    With `output_path`, the reply is written to that new file and only a summary
    is returned, keeping large generated output out of the caller's context.
    """
    endpoint = _endpoint()
    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload: dict[str, Any] = {"model": _model(), "messages": messages}

    try:
        response = httpx.post(endpoint, json=payload, timeout=_timeout())
    except httpx.ConnectError:
        message = (
            f"Local model server is not running at {endpoint}. "
            "Start it before delegating tasks."
        )
        hint = _start_hint()
        if hint:
            message += (
                f"\nThe user configured this command to start it:\n    {hint}\n"
                "Offer to run it for them -- do not run it silently."
            )
        return message
    except httpx.TimeoutException:
        return (
            f"Local model request timed out after {_timeout():g}s at {endpoint}. "
            "The task may be too large, or the model's reasoning effort is set too high."
        )
    except httpx.HTTPError as exc:
        return f"Local model request failed: {type(exc).__name__}: {exc}"

    if response.status_code != 200:
        return (
            f"Local model server returned HTTP {response.status_code} from {endpoint}:\n"
            f"{response.text.strip()}"
        )

    try:
        content = response.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError):
        return f"Unexpected response shape from {endpoint}:\n{response.text.strip()}"

    if not content:
        return (
            "Local model returned an empty response. It may have spent its output "
            "budget on reasoning tokens -- try lowering its reasoning effort."
        )

    text = str(content)
    if output_path:
        return _write_output(output_path, text)
    return text


def main() -> None:
    """Console-script entry point: serve over stdio."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
