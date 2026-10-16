"""Global render gate: the server runs RENDER_MAX_CONCURRENT renders, the rest wait (hardening for the friends beta)."""

import asyncio

from cf_platform.core import limits
from cf_platform.core.config import PlatformSettings


def _settings(n: int) -> PlatformSettings:
    return PlatformSettings(RENDER_MAX_CONCURRENT=n)


def test_third_render_waits_for_a_free_place():
    cfg = _settings(2)
    running = 0
    peak = 0

    async def render():
        nonlocal running, peak
        async with limits.render_gate(cfg):
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.02)
            running -= 1

    async def main():
        await asyncio.gather(*(render() for _ in range(5)))

    asyncio.run(main())
    assert peak == 2


def test_gate_reports_full_only_when_every_place_is_taken():
    cfg = _settings(1)

    async def main():
        assert limits.render_gate_full(cfg) is False
        async with limits.render_gate(cfg):
            assert limits.render_gate_full(cfg) is True
        assert limits.render_gate_full(cfg) is False

    asyncio.run(main())


def test_a_failing_render_gives_its_place_back():
    cfg = _settings(1)

    async def main():
        try:
            async with limits.render_gate(cfg):
                raise RuntimeError("ffmpeg failed")
        except RuntimeError:
            pass
        assert limits.render_gate_full(cfg) is False

    asyncio.run(main())
