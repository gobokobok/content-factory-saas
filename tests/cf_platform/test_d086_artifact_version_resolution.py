"""Regression tests for D086: artifact versions must be resolved numerically.

The operator hit this as three separate-looking bugs in one run — motion effects
not applying, pans doing nothing, and on-screen text on the last scene neither
appearing nor clearing. All three were the same cause: `sorted(keys)[-1]` is a
LEXICOGRAPHIC sort, and "@v9.json" sorts after "@v10.json".."@v16.json". Once an
artifact passed nine versions, every reader — the Studio GET, the scene PATCH
endpoint, and the render worker — silently pinned itself to v9 forever.
"""

import pytest

from cf_platform.core.artifact_manager import latest_version_key


def _keys(*versions: int, name: str = "verified_storyboard") -> list[str]:
    """Build artifact keys for the given version numbers."""
    return [f"users/operator/runs/run-x/storyboard/{name}@v{v}.json" for v in versions]


class TestLatestVersionKey:
    def test_picks_the_highest_version_past_nine(self) -> None:
        # The exact shape of the reported bug: 16 versions, v9 wins a string sort.
        keys = _keys(*range(1, 17))
        assert latest_version_key(keys) == keys[15]
        assert latest_version_key(keys).endswith("@v16.json")

    def test_lexicographic_sort_would_have_been_wrong(self) -> None:
        # Pins the actual defect so nobody "simplifies" this back to sorted()[-1].
        keys = _keys(*range(1, 17))
        assert sorted(keys)[-1].endswith("@v9.json")
        assert latest_version_key(keys) != sorted(keys)[-1]

    def test_order_of_input_does_not_matter(self) -> None:
        assert latest_version_key(_keys(3, 16, 1, 9, 12)).endswith("@v16.json")
        assert latest_version_key(_keys(16, 12, 9, 3, 1)).endswith("@v16.json")

    def test_single_version(self) -> None:
        assert latest_version_key(_keys(1)).endswith("@v1.json")

    def test_below_ten_still_correct(self) -> None:
        # The bug was invisible until v10, so guard the easy case too.
        assert latest_version_key(_keys(*range(1, 10))).endswith("@v9.json")

    def test_empty_returns_none(self) -> None:
        assert latest_version_key([]) is None

    def test_unversioned_keys_are_ignored_not_fatal(self) -> None:
        keys = _keys(1, 2) + ["users/operator/runs/run-x/storyboard/notes.txt"]
        assert latest_version_key(keys).endswith("@v2.json")

    def test_only_unversioned_returns_none(self) -> None:
        assert latest_version_key(["users/operator/runs/run-x/storyboard/junk.json"]) is None

    def test_three_digit_versions(self) -> None:
        assert latest_version_key(_keys(9, 99, 100)).endswith("@v100.json")


class TestCallSitesUseNumericResolution:
    """Every reader must go through the shared helper, not its own sort."""

    @pytest.mark.parametrize(
        "module",
        [
            "cf_platform.interfaces.routes._helpers",
            "cf_platform.interfaces.routes.workers",
        ],
    )
    def test_no_lexicographic_key_sort_remains(self, module: str) -> None:
        import importlib
        import inspect

        src = inspect.getsource(importlib.import_module(module))
        assert "sorted(keys)[-1]" not in src
        assert "sorted(storyboard_keys)[-1]" not in src

    @pytest.mark.asyncio
    async def test_helper_resolves_latest_past_nine(self) -> None:
        from cf_platform.interfaces.routes._helpers import latest_artifact_key

        class FakeStorage:
            async def list_keys(self, prefix: str) -> list[str]:
                return _keys(*range(1, 17))

        key = await latest_artifact_key(FakeStorage(), "run-x", "storyboard", "verified_storyboard")
        assert key.endswith("@v16.json")
