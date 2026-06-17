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
