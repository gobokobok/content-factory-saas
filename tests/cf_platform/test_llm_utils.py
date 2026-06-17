"""Tests for cf_platform/core/llm_utils.py.

Covers:
- strip_markdown_fences: strips ```json ... ``` fences
- strip_markdown_fences: strips plain ``` fences
- strip_markdown_fences: no-op on plain text
- strip_markdown_fences: no-op on bare JSON
- extract_json_object: extracts JSON from surrounding prose
- extract_json_object: no-op on bare JSON
- extract_json_object: handles preamble only
- extract_json_object: handles trailing text only
- extract_json_object: raises ValueError when no JSON object found
"""

import pytest

from cf_platform.core.llm_utils import extract_json_object, strip_markdown_fences


class TestStripMarkdownFences:
    def test_strips_json_fences(self):
        text = '```json\n{"key": "value"}\n```'
        assert strip_markdown_fences(text) == '{"key": "value"}'

    def test_strips_plain_fences(self):
        text = '```\n{"key": "value"}\n```'
        assert strip_markdown_fences(text) == '{"key": "value"}'

    def test_noop_on_plain_text(self):
        text = "some plain text"
        assert strip_markdown_fences(text) == "some plain text"

    def test_noop_on_bare_json(self):
        text = '{"claims": []}'
        assert strip_markdown_fences(text) == '{"claims": []}'


class TestExtractJsonObject:
    def test_extracts_from_preamble_and_trailing_text(self):
        """Regression: Claude adds prose before and after the JSON object."""
        text = (
            'Here is the analysis:\n\n'
            '{"claims": [{"claim": "X", "verdict": "supported", "source": "", "note": "OK"}]}\n\n'
            'I have verified each claim.'
        )
        result = extract_json_object(text)
        assert result.startswith('{"claims"')
        assert result.endswith(']}')
        assert 'I have verified each claim.' not in result

    def test_bare_json_unchanged(self):
        """A bare JSON object with no surrounding text passes through."""
        text = '{"key": "value"}'
        assert extract_json_object(text) == '{"key": "value"}'

    def test_preamble_only(self):
        """Text before the JSON object is stripped."""
        text = 'Here is the result: {"ok": true}'
        assert extract_json_object(text) == '{"ok": true}'

    def test_trailing_text_only(self):
        """Trailing text after the JSON object is stripped."""
        text = '{"ok": true}\n\nNote: all good.'
        # rfind('}') finds the last }, which is the one in the object
        result = extract_json_object(text)
        assert result == '{"ok": true}'

    def test_raises_when_no_json_found(self):
        """ValueError is raised when there is no JSON object in the text."""
        with pytest.raises(ValueError, match="No JSON object found"):
            extract_json_object("All claims check out — no JSON here.")

    def test_raises_on_empty_string(self):
        """ValueError is raised on empty input."""
        with pytest.raises(ValueError, match="No JSON object found"):
            extract_json_object("")
