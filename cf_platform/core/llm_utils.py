"""Shared utilities for processing raw LLM text responses."""


def strip_markdown_fences(text: str) -> str:
    """Strip leading ```json / ``` fences that Claude occasionally wraps around JSON output.

    Claude sometimes wraps JSON in code fences despite being instructed not to,
    particularly when adaptive thinking is enabled. Strip them defensively so
    json.loads() receives valid JSON regardless.
    """
    text = text.strip()
    if text.startswith("```"):
        text = text[text.index("\n") + 1:] if "\n" in text else text
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


def extract_json_object(text: str) -> str:
    """Extract the outermost JSON object `{...}` from `text`, ignoring surrounding prose.

    Claude occasionally adds a preamble sentence or a closing comment around the JSON
    object it was asked to produce. `json.loads()` rejects this with "Extra data" or
    "Expecting value". This function finds the first `{` and the matching last `}` and
    returns only that slice so the caller gets valid JSON regardless of wrapping text.

    Raises ValueError if no `{...}` pair is found.
    """
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or start >= end:
        raise ValueError(f"No JSON object found in LLM response: {text!r}")
    return text[start : end + 1]
