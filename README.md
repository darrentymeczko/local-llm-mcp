# local-llm-mcp

An MCP server that gives Claude Code a single tool, `delegate_to_local`, for handing
small, rote coding subtasks to an LLM running on your own machine.

## Why this exists

Claude Pro/Max subscriptions have usage limits, and a fair share of any coding session
is low-judgment busywork: writing docstrings, generating boilerplate, mechanical
renames, test stubs, reformatting a block of JSON. That work doesn't need a frontier
model. This server lets Claude hand those subtasks to a local model you already run,
so your subscription usage goes to the work that actually needs the reasoning.

## Prerequisites

- Python 3.10+
- The `mcp` Python SDK v2 (installed automatically). This uses `MCPServer`, which is
  what v1's `FastMCP` was renamed to in SDK 2.0.
- A running **OpenAI-compatible** local LLM server. Anything that exposes
  `POST /v1/chat/completions` works - llama.cpp (`llama-server`), Ollama, LM Studio,
  vLLM, text-generation-webui, etc.

## Install

From a checkout, pick whichever tool installer you have:

```bash
pipx install .
```

```bash
uv tool install .
```

Or into the current environment:

```bash
pip install .
```

All three give you a `local-llm-mcp` command on your PATH, which is what Claude Code
launches over stdio. The isolated installers (`pipx`, `uv tool`) are preferable - they
keep the server's dependencies out of whatever environment you happen to be in, and
put the shim somewhere stable that Claude Code can find regardless of which venv or
conda environment is active.

## Configuration

All machine-specific details are environment variables:

| Variable | Default | Meaning |
| --- | --- | --- |
| `LOCAL_LLM_ENDPOINT` | `http://localhost:8081/v1/chat/completions` | Full chat-completions URL of your local server |
| `LOCAL_LLM_MODEL` | `lmstudio-community/gpt-oss-20b-GGUF:MXFP4` | Model id sent in the request body |
| `LOCAL_LLM_TIMEOUT` | `60` | Request timeout in seconds |
| `LOCAL_LLM_START_HINT` | unset | Command that starts your local server, shown to Claude when the server is down |

Common endpoints: llama.cpp `http://localhost:8080/v1/chat/completions`,
Ollama `http://localhost:11434/v1/chat/completions`,
LM Studio `http://localhost:1234/v1/chat/completions`.

Many local servers ignore the `model` field and serve whatever is loaded; set it
anyway if your server routes on it.

### Letting Claude start your server

Forgetting to start the local server is the most common way delegation fails. Set
`LOCAL_LLM_START_HINT` to the command that starts yours, and the "server is not
running" error will carry it:

```
Local model server is not running at http://localhost:8081/v1/chat/completions.
Start it before delegating tasks.
The user configured this command to start it:
    llama-server -m models/gpt-oss-20b.gguf --port 8081
Offer to run it for them -- do not run it silently.
```

Claude can then offer to run it with its own shell tool, which prompts you for
permission first. This server never spawns processes itself - deliberately. Doing so
would mean owning a multi-gigabyte child process across session restarts, racing other
sessions for the port, and swallowing model load times that far exceed the request
timeout. Handing Claude a suggestion you approve keeps the utility small and leaves
the decision with you.

The hint is only ever text in an error message. Treat it as a suggestion requiring
your approval, not something to execute automatically.

## Register with Claude Code

User scope, so it's available in every session.

**macOS / Linux / Git Bash:**

```bash
claude mcp add-json --scope user local-llm '{"type":"stdio","command":"local-llm-mcp","args":[],"env":{"LOCAL_LLM_ENDPOINT":"http://localhost:8081/v1/chat/completions","LOCAL_LLM_MODEL":"your-model-id"}}'
```

**Windows PowerShell** - escape every inner quote with a backslash:

```powershell
claude mcp add-json --scope user local-llm '{\"type\":\"stdio\",\"command\":\"local-llm-mcp\",\"args\":[],\"env\":{\"LOCAL_LLM_ENDPOINT\":\"http://localhost:8081/v1/chat/completions\",\"LOCAL_LLM_MODEL\":\"your-model-id\"}}'
```

PowerShell re-parses arguments before handing them to a native command and strips
the inner `"` characters, so the unescaped form fails with `Invalid configuration:
: Invalid input`. The `--%` stop-parsing token does not save you either, because
`claude` is a `.cmd` shim and cmd.exe re-parses after PowerShell is done. Backslash
escaping is the form that survives both.

`add-json` is more reliable than the plain `claude mcp add ... -- <cmd>` form, whose
`--` separator and `-e` env flags are even more fragile under Windows shells.

Verify with `claude mcp list`, then in a session ask Claude to use `delegate_to_local`.

## Standalone test

With your local server running:

```bash
python test_local_llm.py
```

It sends one hardcoded prompt and prints the model's reply - no MCP client involved.
Useful for confirming the endpoint and model id are right before you blame Claude Code.

## The tool

`delegate_to_local(prompt: str, system_prompt: str = "", output_path: str = "") -> str`

`prompt` is sent as the user message; `system_prompt`, if given, precedes it as a
system message. The tool returns the generated text only. Failures come back as
readable messages rather than exceptions: server not running, timeout, non-200
response body, or an unexpected response shape.

### output_path, and why it is the only real saving

With `output_path`, the reply is written to that file and Claude gets back a one-line
summary instead of the text.

This is not a convenience - it is the difference between the tool saving anything and
not. Without it, generated content still has to pass through Claude's *output* tokens
to reach disk, and output is the expensive direction. Delegation then removes only the
thinking, which for rote work was never the costly part. Measured on a three-function
docstring task, delegating cost about the same as Claude simply doing it. With
`output_path`, the generated text never enters Claude's context at all.

The tradeoff is real: nobody has read the output. Only use it where verification is
cheap and mechanical - a test suite, a type checker, a linter, or a spot-check of a
few files out of many. If the only way to verify is to read every line, delegation
saves nothing, because reading costs about what writing does.

Guard rails:

- **It never overwrites.** An existing path is refused, since the content is
  unreviewed. Delete the file yourself first if replacing it is what you mean.
- **It never creates directories.** A missing parent is an error.
- **Failures write nothing.** A server that is down or times out leaves no file behind.
- Writes are UTF-8. Run the non-ASCII scan below before committing generated files;
  local models slip typographic punctuation into code comments.

## Known limitations

- **Review the output.** The local model is materially weaker than Claude. Treat what
  comes back as a first draft to be checked, not a result to be pasted. The tool
  description tells Claude this, but the responsibility ultimately lands on you.
- **Reasoning effort and verbosity matter a lot.** Reasoning models (gpt-oss and
  friends) can burn the whole output budget on hidden reasoning tokens and return an
  empty or truncated answer, or blow past the 60s timeout on a task that should take
  three seconds. If delegation feels slow or returns nothing, lower the reasoning
  effort on the *server* side (e.g. llama.cpp's `--chat-template-kwargs`
  `{"reasoning_effort":"low"}`) rather than raising the timeout here.
- **No streaming, no conversation state.** Each call is a single independent
  request/response. There is no session, no file access, no tool use on the local side -
  the local model sees only the prompt text Claude sends it.
- **Watch for non-ASCII characters.** Local models like to reach for typographic
  punctuation - non-breaking hyphens (U+2011), en dashes (U+2013), curly quotes -
  especially in prose like docstrings and comments. Python does not care, but they
  break `grep`, produce confusing diffs, and can blow up on tools that assume ASCII.
  Scan delegated output before you commit it:

  ```bash
  python -c "import sys,unicodedata; [print(f'U+{ord(c):04X} {unicodedata.name(c,chr(63))}') for c in open(sys.argv[1],encoding='utf-8').read() if ord(c)>127]" FILE
  ```

- **No retries.** A failed call returns an error string; Claude decides whether to
  retry or just do the task itself.

## License

MIT
