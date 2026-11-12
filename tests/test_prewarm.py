"""First-frame preparation is bounded and prioritizes real player graphics."""

from vantage.prewarm import first_sprite_jobs


def test_first_frame_jobs_include_cpu_gpu_and_split_layers_without_duplicates() -> None:
    row = [1, 1, 109, 0, 0, 1, 1, 2, [[100, 0, 0, 0]], 0]
    jobs = first_sprite_jobs({"entities": [row, row]}, {1: {"color_id": 3}})
    assert len(jobs) == 6
    assert {job[2:4] for job in jobs} == {(3, False), (-1, True)}
    assert {job[5] for job in jobs} == {"all", "main", "shadow"}
    assert all(not job[4] for job in jobs)  # building facet, not a unit heading


def test_neutral_map_objects_cannot_exhaust_the_starting_units_budget() -> None:
    neutral = [[i, 0, 1, 0, 0, 1, 32, 0, [[i + 1000, 0, 0, 0]], 0] for i in range(100)]
    unit = [1000, 1, 83, 0, 0, 1, 4, 0, [[42, 0, 0, 0]], 0]
    jobs = first_sprite_jobs({"entities": [*neutral, unit]}, {1: {"color_id": 0}}, limit=12)
    assert len(jobs) == 12
    assert len([job for job in jobs if job[0] == 42]) == 6


def test_optional_missing_art_does_not_fail_a_valid_analysis(tmp_path, monkeypatch) -> None:
    from types import SimpleNamespace

    from vantage.prewarm import warm_assets

    data = SimpleNamespace(
        game_dir=tmp_path,
        cache_dir=tmp_path,
        mode=None,
        player_colors=[(0, 0, 255)] * 8,
        mod_roots=lambda _: [],
    )
    row = [1, 1, 83, 0, 0, 1, 4, 0, [[42, 0, 0, 0]], 0]
    timeline = SimpleNamespace(
        data=data,
        start=0,
        sprites={42: ("missing", 1, 1, 0)},
        catalog=SimpleNamespace(masters={}),
        match={"players": {}},
        keyframe_at=lambda _: {"entities": [row]},
    )
    monkeypatch.setattr(
        "vantage.prewarm.SpriteStore", lambda *a, **k: SimpleNamespace(strip=lambda *a, **k: None)
    )
    result = warm_assets(timeline, workers=1)
    assert result["prepared"] == 0 and result["missing"] == 6
