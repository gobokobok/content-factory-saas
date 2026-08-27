"""Tests for cf_platform/core/sfx_library.py (D076)."""

from cf_platform.core.sfx_library import SFX_LIBRARY, sfx_vocab_prompt_line, sfx_vocab_reviewer_line


class TestSfxLibraryManifest:
    def test_manifest_has_eight_curated_entries(self):
        assert len(SFX_LIBRARY) == 8

    def test_keys_are_unique(self):
        keys = [e.key for e in SFX_LIBRARY]
        assert len(keys) == len(set(keys))

    def test_expected_keys_present(self):
        keys = {e.key for e in SFX_LIBRARY}
        assert keys == {
            "cash_register", "checkmark", "error", "whoosh",
            "pop", "notification", "drumroll", "impact",
        }

    def test_every_entry_has_all_fields_populated(self):
        for entry in SFX_LIBRARY:
            assert entry.key
            assert entry.display_name
            assert entry.prompt_hint
            assert entry.search_query


class TestSfxVocabPromptLine:
    def test_includes_every_key_and_hint(self):
        line = sfx_vocab_prompt_line()
        for entry in SFX_LIBRARY:
            assert entry.key in line
            assert entry.prompt_hint in line

    def test_includes_silence_option(self):
        line = sfx_vocab_prompt_line()
        assert '"silence"' in line

    def test_majority_should_be_silence_note_present(self):
        assert "MAJORITY" in sfx_vocab_prompt_line()


class TestSfxVocabReviewerLine:
    def test_includes_every_key(self):
        line = sfx_vocab_reviewer_line()
        for entry in SFX_LIBRARY:
            assert entry.key in line

    def test_includes_silence_option(self):
        assert '"silence"' in sfx_vocab_reviewer_line()

    def test_is_compact_single_line(self):
        # Unlike the prompt-generation version, the reviewer line has no
        # per-entry hint text — just the pipe-separated key list.
        assert "\n" not in sfx_vocab_reviewer_line()
