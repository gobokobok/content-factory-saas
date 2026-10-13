"""P-HARD1-S4 — split / merge / re-cut are refused while a bulk image job runs for the run."""

from cf_platform.workers.scene_images import claim_job, release_job
from tests.cf_platform.p13_helpers import RUN_ID, p13_env

_BASE = f"/platform/studio/runs/{RUN_ID}/storyboard"


class TestBulkJobGuard:
    """Boundary edits answer 409 with a readable reason during a bulk image job."""

    def test_split_is_refused_while_job_runs(self):
        with p13_env() as env:
            before = env.versions("storyboard", "verified_storyboard")
            assert claim_job(RUN_ID)
            try:
                r = env.client.post(f"{_BASE}/scenes/2/split", json={"at_word": 6})
            finally:
                release_job(RUN_ID)
            assert r.status_code == 409
            assert "Images are being generated" in r.json()["detail"]
            assert env.versions("storyboard", "verified_storyboard") == before

    def test_merge_is_refused_while_job_runs(self):
        with p13_env() as env:
            before = env.versions("storyboard", "verified_storyboard")
            assert claim_job(RUN_ID)
            try:
                r = env.client.post(f"{_BASE}/scenes/1/merge")
            finally:
                release_job(RUN_ID)
            assert r.status_code == 409
            assert env.versions("storyboard", "verified_storyboard") == before

    def test_boundaries_replace_is_refused_while_job_runs(self):
        with p13_env() as env:
            assert claim_job(RUN_ID)
            try:
                r = env.client.put(f"{_BASE}/boundaries", json={"start_words": [0, 6]})
            finally:
                release_job(RUN_ID)
            assert r.status_code == 409

    def test_boundaries_preview_is_allowed_while_job_runs(self):
        with p13_env() as env:
            assert claim_job(RUN_ID)
            try:
                r = env.client.put(f"{_BASE}/boundaries", json={"start_words": [0, 6], "dry_run": True})
            finally:
                release_job(RUN_ID)
            assert r.status_code == 200
            assert r.json()["dry_run"] is True

    def test_split_works_again_once_the_job_is_released(self):
        with p13_env() as env:
            assert claim_job(RUN_ID)
            release_job(RUN_ID)
            r = env.client.post(f"{_BASE}/scenes/2/split", json={"at_word": 6})
            assert r.status_code == 200
