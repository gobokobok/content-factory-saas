"""LEGAL-S1 — the privacy notice, the terms, the links to them, the retention job and the erase tool.

The pages are public and filled from ENV; an unset detail shows a visible marker and a banner. A bumped
TERMS_VERSION sends a signed-in user back to the terms. The retention job deletes old prompt-log rows and
expired sessions. The erase tool removes one tenant's files and leaves another's (rows: see
tests/integration/test_erasure_postgres.py, which runs the SQL against a real Postgres).
"""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from cf_platform.core.accounts import OAuthState, SessionRecord
from cf_platform.core.artifact_manager import InMemoryArtifactStorage
from cf_platform.core.erasure import (
    ErasureRefused,
    check_tenant,
    collect_files,
    delete_files,
    file_prefixes,
    pseudonym,
)
from cf_platform.core.moderation import InMemoryPromptLog, PromptLogEntry
from cf_platform.core.retention import retention_loop, run_retention
from tests.test_p_auth_accounts import World, run

FILLED = {
    "LEGAL_CONTROLLER_NAME": "Example <b>Ltd</b>",
    "LEGAL_CONTROLLER_ADDRESS": "1 Example Street, Riga",
    "LEGAL_CONTACT_EMAIL": "privacy@example.com",
    "LEGAL_GOVERNING_LAW": "the laws of Latvia",
    "LEGAL_TRANSFER_BASIS": "standard contractual clauses",
}


@pytest.fixture
def world():
    w = World(**FILLED)
    yield w
    w.close()


@pytest.fixture
def bare_world():
    w = World()
    yield w
    w.close()


class TestPages:
    def test_both_pages_are_public(self, world):
        client = world.client()
        assert client.get("/terms").status_code == 200
        assert client.get("/privacy").status_code == 200

    def test_the_privacy_notice_names_the_controller_data_providers_and_rights(self, world):
        text = world.client().get("/privacy").text
        assert "Example &lt;b&gt;Ltd&lt;/b&gt;" in text and "<b>Ltd</b>" not in text  # escaped, not injected
        assert "1 Example Street, Riga" in text and "privacy@example.com" in text
        for data in ("Google name", "account id", "Prompt log", "Usage ledger", "Session records", "storyboard the AI director"):
            assert data.lower() in text.lower(), data
        for provider in ("Anthropic", "Google", "OpenAI", "kie.ai", "Deepgram", "Cloudflare", "Railway", "Pexels", "payment provider"):
            assert provider in text, provider
        for right in ("access", "correct", "erase", "object", "complain"):
            assert right in text.lower(), right
        assert "standard contractual clauses" in text
        assert "90 days" in text and "14 days" in text  # prompt-log and session retention, from settings

    def test_the_terms_cover_the_required_points(self, world):
        text = world.client().get("/terms").text.lower()
        for point in (
            "what the service is", "at least 16", "not allowed", "own", "ai-generated", "not money",
            "liab", "ending it", "governed by the laws of latvia", "version v1",
        ):
            assert point in text, point
        assert "privacy notice" in text

    def test_an_unset_detail_is_marked_and_a_banner_says_the_notice_is_incomplete(self, bare_world):
        for path in ("/terms", "/privacy"):
            text = bare_world.client().get(path).text
            assert "to be completed by the operator: LEGAL_CONTROLLER_NAME" in text
            assert "Incomplete." in text
        # the e-mail falls back to the abuse contact
        w = World(ABUSE_CONTACT_EMAIL="abuse@example.com", **{k: v for k, v in FILLED.items() if k != "LEGAL_CONTACT_EMAIL"})
        try:
            text = w.client().get("/privacy").text
            assert "abuse@example.com" in text and "Incomplete." not in text
        finally:
            w.close()

    def test_a_filled_in_notice_has_no_banner(self, world):
        assert "Incomplete." not in world.client().get("/privacy").text

    def test_minimum_age_and_retention_follow_settings(self):
        w = World(MINIMUM_AGE=18, PROMPT_LOG_RETENTION_DAYS=30, **FILLED)
        try:
            assert "at least 18" in w.client().get("/terms").text.lower()
            assert "30 days" in w.client().get("/privacy").text
        finally:
            w.close()

    def test_the_accept_button_is_only_shown_to_someone_who_has_to_accept(self, world):
        # the button's box starts hidden; the page script reveals it for terms_accepted === false
        text = world.client().get("/terms").text
        assert 'id="accept-box" class="hidden"' in text and "terms_accepted === false" in text


class TestTermsVersion:
    def test_a_bumped_version_asks_a_signed_in_user_again(self, world):
        cookie, _ = run(world.sign_in("friend@example.com", "sub-a"))  # accepted "v1"
        c = world.client(cookie)
        assert c.get("/create", headers={"accept": "text/html"}).status_code == 200
        world.settings = world.settings.model_copy(update={"TERMS_VERSION": "2026-10-22"})
        r = c.get("/create", headers={"accept": "text/html"})
        assert r.status_code == 302 and r.headers["location"] == "/terms"
        assert c.get("/platform/projects").json()["detail"] == "terms_required"
        assert c.get("/privacy").status_code == 200  # the notice stays readable

    def test_the_shipped_version_is_the_new_one(self):
        from src.config import Settings

        assert Settings.model_fields["TERMS_VERSION"].default == "2026-10-22"
        assert Settings.model_fields["MINIMUM_AGE"].default == 16
        assert Settings.model_fields["PROMPT_LOG_RETENTION_DAYS"].default == 90


class TestLinks:
    def test_the_sign_in_page_links_to_both(self, world):
        text = world.client().get("/login").text
        assert 'href="/terms"' in text and 'href="/privacy"' in text

    def test_the_create_footer_links_to_both(self, world):
        cookie, _ = run(world.sign_in("friend@example.com", "sub-a"))
        text = world.client(cookie).get("/create").text
        assert 'href="/terms"' in text and 'href="/privacy"' in text


class TestRetention:
    NOW = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)

    def _entry(self, days_old: int, tenant: str = "u_a") -> PromptLogEntry:
        return PromptLogEntry(tenant_id=tenant, kind="script", excerpt="x", created_at=self.NOW - timedelta(days=days_old))

    def test_old_prompt_log_rows_are_deleted_and_new_ones_kept(self):
        log = InMemoryPromptLog()
        for days in (1, 89, 91, 400):
            run(log.add(self._entry(days)))
        accounts = World().accounts
        removed = run(run_retention(log, accounts, prompt_log_days=90, now=self.NOW))
        assert removed["prompt_log"] == 2
        assert sorted((self.NOW - r.created_at).days for r in run(log.recent(None))) == [1, 89]

    def test_zero_days_keeps_the_log_for_ever(self):
        log = InMemoryPromptLog()
        run(log.add(self._entry(4000)))
        assert run(run_retention(log, World().accounts, prompt_log_days=0, now=self.NOW))["prompt_log"] == 0
        assert len(run(log.recent(None))) == 1

    def test_expired_and_revoked_sessions_and_stale_sign_in_states_go(self):
        accounts = World().accounts
        mk = lambda h, expires, revoked=None: SessionRecord(  # noqa: E731
            token_hash=h, user_id="u", created_at=self.NOW - timedelta(days=20), expires_at=expires, revoked_at=revoked)
        for record in (
            mk("live", self.NOW + timedelta(days=3)),
            mk("expired", self.NOW - timedelta(days=1)),
            mk("revoked", self.NOW + timedelta(days=3), self.NOW - timedelta(hours=1)),
        ):
            run(accounts.save_session(record))
        run(accounts.save_oauth_state(OAuthState(state_hash="old", code_verifier="v", created_at=self.NOW - timedelta(days=2))))
        run(accounts.save_oauth_state(OAuthState(state_hash="new", code_verifier="v", created_at=self.NOW - timedelta(minutes=5))))
        removed = run(run_retention(InMemoryPromptLog(), accounts, prompt_log_days=90, now=self.NOW))
        assert (removed["sessions"], removed["oauth_states"]) == (2, 1)
        assert run(accounts.get_session("live")) is not None and run(accounts.get_session("expired")) is None
        assert run(accounts.pop_oauth_state("new")) is not None and run(accounts.pop_oauth_state("old")) is None

    def test_the_loop_runs_once_at_start_and_a_failing_pass_does_not_stop_it(self, monkeypatch):
        calls: list[int] = []

        class Boom(InMemoryPromptLog):
            async def purge_older_than(self, cutoff):
                calls.append(1)
                raise RuntimeError("db down")

        async def go():
            settings = World().settings
            task = asyncio.create_task(retention_loop(settings, Boom(), World().accounts))
            await asyncio.sleep(0.05)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        run(go())
        assert calls == [1]

    def test_interval_zero_turns_the_job_off(self):
        settings = World(RETENTION_JOB_INTERVAL_HOURS=0).settings
        run(asyncio.wait_for(retention_loop(settings, InMemoryPromptLog(), World().accounts), timeout=1))


class TestErasureFiles:
    async def _seed(self, storage: InMemoryArtifactStorage) -> None:
        await storage.put_json("users/u_a/runs/r1/storyboard/verified_storyboard@v1.json", {"a": 1})
        await storage.put_bytes("runs/r1/voiceover/generated.wav", b"x")
        await storage.put_bytes("runs/r1/output/final.mp4", b"x")
        await storage.put_bytes("tenant-music/u_a/song.mp3", b"x")
        await storage.put_json("users/u_b/runs/r2/storyboard/verified_storyboard@v1.json", {"b": 1})
        await storage.put_bytes("runs/r2/output/final.mp4", b"x")
        await storage.put_bytes("runs/r10/output/final.mp4", b"x")  # another tenant's run whose id starts with "r1"
        await storage.put_bytes("tenant-music/u_ab/song.mp3", b"x")  # another tenant whose id starts with "u_a"
        await storage.put_bytes("sfx-library/boom.mp3", b"x")

    def test_one_tenants_files_go_and_everyone_elses_stay(self):
        storage = InMemoryArtifactStorage()
        run(self._seed(storage))
        prefixes = file_prefixes("u_a", ["r1"])
        keys = run(collect_files(storage, prefixes))
        assert len(keys) == 4 and all(k.startswith(("users/u_a/", "runs/r1/", "tenant-music/u_a/")) for k in keys)
        assert run(delete_files(storage, keys)) == 4
        left = run(storage.list_keys(""))
        assert sorted(left) == sorted([
            "users/u_b/runs/r2/storyboard/verified_storyboard@v1.json", "runs/r2/output/final.mp4",
            "runs/r10/output/final.mp4", "tenant-music/u_ab/song.mp3", "sfx-library/boom.mp3",
        ])

    def test_collecting_changes_nothing(self):
        storage = InMemoryArtifactStorage()
        run(self._seed(storage))
        before = run(storage.list_keys(""))
        run(collect_files(storage, file_prefixes("u_a", ["r1"])))
        assert run(storage.list_keys("")) == before

    def test_the_owner_and_empty_ids_are_refused(self):
        for bad in ("operator", "", "  "):
            with pytest.raises(ErasureRefused):
                check_tenant(bad)
        assert check_tenant(" u_a ") == "u_a"

    def test_the_ledger_pseudonym_is_stable_and_not_the_tenant_id(self):
        assert pseudonym("u_a") == pseudonym("u_a") != pseudonym("u_b")
        assert "u_a" not in pseudonym("u_a") and pseudonym("u_a").startswith("erased_")

    def test_the_script_is_a_dry_run_unless_told_otherwise(self):
        from scripts.erase_tenant import parse_args

        assert parse_args(["--email", "a@b.c"]).execute is False
        assert parse_args(["--tenant", "u_a", "--execute"]).execute is True
        with pytest.raises(SystemExit):
            parse_args([])  # a target is required
