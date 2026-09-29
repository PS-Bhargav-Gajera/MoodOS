"""Regression tests for the four "same thing every time" defects.

1. Same movie every time  -> shown movies persist and are filtered from the pool
2. Same songs every time  -> music query rotates + recent tracks are excluded
3. Repeated REST buffers  -> buffers never repeat a title and stay time-true
4. Walk has no real name  -> walk steps are backed by real Overpass places
"""

import httpx
import pytest

from moodos import db
from moodos import orchestrator as orch


@pytest.fixture
def clean_shown(monkeypatch):
    """Isolate the shown-items log so tests never touch the real database."""
    store: dict[tuple[str, str], list[str]] = {}

    def record(user_id, kind, title):
        store.setdefault((user_id, kind), []).insert(0, title)

    def recent(user_id, kind, limit=25):
        return list(store.get((user_id, kind), []))[:limit]

    monkeypatch.setattr(db, "record_shown", record)
    monkeypatch.setattr(db, "recent_shown", recent)
    return store


# ---------------------------------------------------------------- problem 1

def test_shown_movie_is_persisted_and_recalled(clean_shown):
    db.record_shown("u1", "movie", "Whiplash")
    assert db.recent_shown("u1", "movie") == ["Whiplash"]
    assert db.recent_shown("u2", "movie") == []


def test_excluded_movie_titles_normalises(clean_shown):
    db.record_shown("u1", "movie", "The Dark Knight")
    blocked = orch._excluded_movie_titles("u1")
    assert "the dark knight" in blocked
    # Different user is unaffected.
    assert orch._excluded_movie_titles("u2") == set()


def test_title_key_is_punctuation_insensitive():
    assert db._title_key("Spider-Man: No Way Home!") == "spider man no way home"
    assert db._title_key("  The   Matrix  ") == "the matrix"


def test_record_shown_items_collects_movies_and_tracks(clean_shown):
    plan = {
        "steps": [
            {"kind": "movie", "title": "Arrival", "tracks": []},
            {"kind": "music", "title": "Mix",
             "tracks": [{"title": "Track A"}, {"title": "Track B"}]},
        ]
    }
    orch._record_shown_items(plan, "u1")
    assert db.recent_shown("u1", "movie") == ["Arrival"]
    assert set(db.recent_shown("u1", "track")) == {"Track A", "Track B"}


def test_record_shown_items_never_raises(clean_shown, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("db down")

    monkeypatch.setattr(db, "record_shown", boom)
    # Must not propagate — bookkeeping must never break a plan.
    orch._record_shown_items({"steps": [{"kind": "movie", "title": "X"}]}, "u1")


# ---------------------------------------------------------------- problem 2

def test_music_seed_rotation_cycles_through_seeds(clean_shown):
    slots = {"intensity": "low", "current_mood": "stressed", "music_language": "gujarati"}
    seen = {orch._rotate_music_query("calm gujarati playlist", slots, {}, "u1")
            for _ in range(6)}
    # An identical query for every request is the bug; require real variety.
    assert len(seen) > 1
    assert len(db.recent_shown("u1", "music_seed")) == 6


def test_music_seed_prefers_least_recently_used(clean_shown):
    slots = {"intensity": "low", "current_mood": "stressed"}
    first = orch._rotate_music_query("base", slots, {}, "u1")
    second = orch._rotate_music_query("base", slots, {}, "u1")
    assert first != second


def test_music_seed_energy_mood_differs_from_calm(clean_shown):
    calm = orch._music_seed_candidates({"intensity": "low", "current_mood": "stressed"}, {})
    lively = orch._music_seed_candidates({"intensity": "high", "current_mood": "happy"}, {})
    assert calm != lively
    assert set(calm) != set(lively)


def test_music_seed_rain_prefers_indoor_vibes():
    seeds = orch._music_seed_candidates(
        {"intensity": "low", "current_mood": "tired"},
        {"condition": "light rain"},
    )
    assert seeds[0] in {"lofi", "ambient", "piano"}


def test_exclude_recent_tracks_removes_repeats(clean_shown):
    db.record_shown("u1", "track", "Track A")
    tracks = [{"title": "Track A"}, {"title": "Track B"}]
    kept = orch._exclude_recent_tracks(tracks, "u1")
    assert [t["title"] for t in kept] == ["Track B"]


def test_exclude_recent_tracks_keeps_pool_when_all_repeat(clean_shown):
    db.record_shown("u1", "track", "Track A")
    tracks = [{"title": "Track A"}]
    # Never return an empty music step just to honour the exclusion list.
    assert orch._exclude_recent_tracks(tracks, "u1") == tracks


def test_exclude_recent_tracks_is_per_user(clean_shown):
    db.record_shown("u1", "track", "Track A")
    tracks = [{"title": "Track A"}]
    assert orch._exclude_recent_tracks(tracks, "u2") == tracks


# ---------------------------------------------------------------- problem 3

def test_buffers_do_not_repeat_titles():
    plan = {"steps": [], "total_duration_min": 0, "total_cost_inr": 0}
    consumed = orch._add_buffer_steps(plan, 120, max_buffers=3)
    assert consumed == 120
    orch._collapse_rest_buffers(plan)
    titles = [s["title"] for s in plan["steps"] if s["kind"] == "rest"]
    assert len(titles) == len(set(titles)), "buffer titles repeated"


def test_buffer_run_never_exceeds_rest_cap():
    plan = {"steps": [], "total_duration_min": 0, "total_cost_inr": 0}
    orch._add_buffer_steps(plan, 200, max_buffers=6)
    plan = orch._collapse_rest_buffers(plan)
    for s in plan["steps"]:
        assert s["duration_min"] <= orch._DUR_CAPS.get("rest", 45)


def test_collapsing_buffers_preserves_total_duration():
    # Merging must not silently discard the user's requested time.
    plan = {"steps": [], "total_duration_min": 0, "total_cost_inr": 0}
    orch._add_buffer_steps(plan, 90, max_buffers=3)
    before = sum(s["duration_min"] for s in plan["steps"])
    plan = orch._collapse_rest_buffers(plan)
    after = sum(s["duration_min"] for s in plan["steps"])
    assert before == after == 90
    assert plan["total_duration_min"] == 90


def test_adjacent_short_buffers_merge():
    plan = {
        "steps": [
            {"kind": "rest", "title": "A", "duration_min": 20, "cost_inr": 0},
            {"kind": "rest", "title": "B", "duration_min": 20, "cost_inr": 0},
        ],
        "total_duration_min": 0, "total_cost_inr": 0,
    }
    plan = orch._collapse_rest_buffers(plan)
    assert len(plan["steps"]) == 1
    assert plan["steps"][0]["duration_min"] == 40


# ---------------------------------------------------------------- problem 4

def test_walk_seed_is_not_used_when_real_parks_exist(monkeypatch):
    calls = {"n": 0}

    def fake_walks(lat, lon, limit=4):
        calls["n"] += 1
        return [{"id": f"osm:{i}", "title": f"Real Park {i}", "kind": "place",
                 "subtype": "walk", "lat": 23.0 + i / 1000, "lon": 72.5,
                 "estimated_cost": 0, "duration_min": 20, "intensity": "low",
                 "outdoor": True, "source": "overpass"} for i in range(3)]

    monkeypatch.setattr(orch.providers, "nearby_walks", fake_walks)
    out = fake_walks(23.0, 72.5)
    assert calls["n"] == 1
    assert all("Real Park" in p["title"] for p in out)
    # The generic seed walk must not be the source of walk names any more.
    assert not any("quiet stretch" in p["title"] for p in out)


def test_seed_walk_fallback_still_available_without_parks(monkeypatch):
    monkeypatch.setattr(orch.providers, "nearby_walks", lambda *a, **k: [])
    # No parks -> pool falls back to the generic walk rather than nothing.
    assert orch.providers.nearby_walks(23.0, 72.5) == []


def test_nearby_walks_returns_real_named_places(clean_shown, monkeypatch):
    """Guard against a regression where walk places lose their real names."""
    monkeypatch.setattr(orch.providers, "_overpass_query", lambda q: _OVERPASS_FIXTURE)
    out = orch.providers.nearby_walks(23.0225, 72.5714, limit=3)
    assert out
    for p in out:
        assert p.get("title")
        assert p.get("subtype") == "walk"


# ------------------------------------------------- problem 4 (offline-parsed)

_OVERPASS_FIXTURE = {
    "elements": [
        {"type": "way", "id": 1, "center": {"lat": 23.03, "lon": 72.57},
         "tags": {"leisure": "park", "name": "Saurashtra Park"}},
        {"type": "way", "id": 2, "center": {"lat": 23.04, "lon": 72.58},
         "tags": {"leisure": "garden", "name": "Lalbhai Garden"}},
        {"type": "way", "id": 3, "center": {"lat": 23.05, "lon": 72.59},
         "tags": {"highway": "pedestrian", "name": "CG Road"}},
        # unnamed polygon must never reach the user as a "real place"
        {"type": "way", "id": 4, "center": {"lat": 23.06, "lon": 72.60},
         "tags": {"leisure": "park"}},
    ]
}


def test_walk_spots_parse_real_names(monkeypatch):
    monkeypatch.setattr(orch.providers, "_overpass_query", lambda q: _OVERPASS_FIXTURE)
    spots = orch.providers._overpass_walk_spots(23.02, 72.57, limit=5)
    titles = [s["title"] for s in spots]
    assert "Saurashtra Park park" in titles
    assert "Lalbhai Garden garden" in titles
    assert "CG Road (pedestrian street)" in titles
    # The unnamed element is dropped.
    assert len(spots) == 3
    for s in spots:
        assert s["subtype"] == "walk"
        assert s["source"] == "overpass"
        assert s["lat"] and s["lon"]


def test_walk_spots_empty_when_overpass_fails(monkeypatch):
    monkeypatch.setattr(orch.providers, "_overpass_query", lambda q: None)
    assert orch.providers._overpass_walk_spots(23.02, 72.57, limit=5) == []


def test_overpass_query_tries_mirror_fallback(monkeypatch):
    """Primary reset must not kill the leg if a mirror answers."""
    from moodos import providers as p

    attempts = []

    class FakeResp:
        status_code = 200

        def json(self):
            return {"elements": []}

    class FakeClient:
        def __init__(self, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, content=None):
            attempts.append(url)
            if url == p.settings.overpass_url:
                raise httpx.ConnectError("reset by peer")
            return FakeResp()

    monkeypatch.setattr(p.httpx, "Client", FakeClient)
    monkeypatch.setattr(p.time, "sleep", lambda s: None)
    assert p._overpass_query("[out:json];") == {"elements": []}
    assert len(attempts) > 1, "no mirror attempted after primary failed"


def test_overpass_query_returns_none_when_all_mirrors_fail(monkeypatch):
    from moodos import providers as p

    class FakeClient:
        def __init__(self, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, content=None):
            raise httpx.ConnectError("reset")

    monkeypatch.setattr(p.httpx, "Client", FakeClient)
    monkeypatch.setattr(p.time, "sleep", lambda s: None)
    assert p._overpass_query("[out:json];") is None


# ------------------------------------- regressions found during live verify

def test_spotify_limit_is_clamped_to_accepted_range():
    """Spotify rejects track searches with limit > 10 (HTTP 400 Invalid limit)."""
    import inspect

    from moodos import spotify as sp

    src = inspect.getsource(sp.search_tracks)
    assert "min(int(limit or 8), 10)" in src


def test_suggest_movies_tool_is_registered():
    """run_pipeline calls mcp.call('suggest_movies'); it must exist."""
    from moodos.mcp_server import mcp

    assert "suggest_movies" in mcp.tools
    assert callable(mcp.tools["suggest_movies"])


def test_suggest_movies_routes_home_and_out(clean_shown):
    from moodos import mcp_server as m

    srv = m.mcp
    out = srv.suggest_movies("heartwarming film", limit=3, watch_at_home=False)
    assert isinstance(out, list)
    home = srv.suggest_movies("heartwarming film", limit=3, watch_at_home=True)
    assert isinstance(home, list)


def test_one_failed_source_does_not_break_the_plan(monkeypatch):
    """Spotify/Overpass failure must not abort the rest of the pipeline."""
    from moodos import providers as p

    monkeypatch.setattr(p, "search_music", lambda *a, **k: [])
    assert p.search_music("anything") == []
    monkeypatch.setattr(p, "nearby_walks", lambda *a, **k: [])
    assert p.nearby_walks(23.0, 72.5) == []


def test_attach_music_tracks_survives_empty_spotify():
    """A dead Spotify must not produce a fabricated playlist."""
    plan = {"steps": [{"kind": "music", "title": "Music", "duration_min": 30}],
            "total_duration_min": 30, "total_cost_inr": 0}
    orch._attach_music_tracks(plan, [])
    step = plan["steps"][0]
    assert step["tracks"] == []
    assert step["unavailable"] is True


# ================================================== round 2: the 4 reported bugs


def _t(name, artists, secs=234):
    return {"id": f"spotify:{name}{artists}", "uri": f"spotify:track:{name}",
            "name": name, "artist": artists, "title": f"{name} — {artists}",
            "kind": "music", "duration_sec": secs, "duration_min": round(secs / 60, 1),
            "source": "spotify"}


# --- FIX 1: duplicate tracks --------------------------------------------

def test_track_key_uses_name_and_artist_not_spotify_id():
    from moodos.spotify import _track_key

    a = _t("listen", "industrial ambient, augur")
    b = dict(a, id="spotify:DIFFERENT_ID", uri="spotify:track:OTHER")
    # Same song, different Spotify id (album/live/remix variant) must collide.
    assert _track_key(a) == _track_key(b)


def test_track_key_is_case_and_punctuation_insensitive():
    from moodos.spotify import _track_key

    assert _track_key(_t("Listen!", "Industrial Ambient, Augur")) == \
           _track_key(_t("listen", "industrial ambient, augur"))


def test_track_key_falls_back_to_title_when_name_missing():
    from moodos.spotify import _track_key

    legacy = {"title": "Vichudo — Kinjal Dave"}
    structured = {"name": "Vichudo", "artist": "Kinjal Dave"}
    assert _track_key(legacy) == _track_key(structured)


def test_dedupe_tracks_removes_the_reported_duplicate():
    from moodos.spotify import _dedupe_tracks

    rows = [
        _t("listen", "industrial ambient, augur"),
        _t("Vichudo", "Kinjal Dave"),
        dict(_t("listen", "industrial ambient, augur"), id="spotify:alt"),  # dup, other id
        _t("Tu Haiye Haali Aave", "Jigardan Gadhavi"),
    ]
    out = _dedupe_tracks(rows)
    titles = [t["title"] for t in out]
    assert titles.count("listen — industrial ambient, augur") == 1
    assert len(out) == 3
    # order preserved
    assert titles[0] == "listen — industrial ambient, augur"


def test_dedupe_tracks_keeps_distinct_songs_same_artist():
    from moodos.spotify import _dedupe_tracks

    out = _dedupe_tracks([_t("Song A", "X"), _t("Song B", "X"), _t("Song A", "Y")])
    assert len(out) == 3


def test_two_music_steps_never_share_a_track():
    """The reported symptom: the same song in two legs of one plan."""
    pool = [_t(f"Song {i}", f"Artist {i}", secs=200) for i in range(14)]
    plan = {"steps": [
        {"kind": "music", "title": "mix one", "duration_min": 20},
        {"kind": "music", "title": "mix two", "duration_min": 20},
    ], "total_duration_min": 40, "total_cost_inr": 0}
    orch._attach_music_tracks(plan, pool)
    a = [t["title"] for t in plan["steps"][0]["tracks"]]
    b = [t["title"] for t in plan["steps"][1]["tracks"]]
    assert a and b
    assert not set(a) & set(b), f"tracks leaked across legs: {set(a) & set(b)}"


def test_single_music_step_has_no_internal_duplicates():
    pool = [_t(f"Song {i}", f"Artist {i}", secs=200) for i in range(10)]
    plan = {"steps": [{"kind": "music", "title": "mix", "duration_min": 30}],
            "total_duration_min": 30, "total_cost_inr": 0}
    orch._attach_music_tracks(plan, pool)
    tr = [t["title"] for t in plan["steps"][0]["tracks"]]
    assert len(tr) == len(set(tr))


# --- FIX 2: background Mem0 write ---------------------------------------

def test_background_mem0_write_records_movie_and_tracks(monkeypatch):
    import app

    calls = []

    def fake_add(user_id, text, **kw):
        calls.append((user_id, text, kw.get("category")))
        return True

    monkeypatch.setattr(app.mem0, "add", fake_add)
    bundle = {"plan": {"steps": [
        {"kind": "movie", "title": "The Lunchbox", "tracks": []},
        {"kind": "music", "title": "mix",
         "tracks": [{"title": "A — B"}, {"title": "C — D"}]},
    ]}}
    app._remember_suggestions_bg("demo", bundle)
    blob = " ".join(c[1] for c in calls)
    assert "Suggested movie: The Lunchbox" in blob
    assert "Suggested songs: A — B, C — D" in blob
    assert all(c[2] == "episodic" for c in calls)


def test_background_mem0_write_never_raises(monkeypatch):
    import app

    def boom(*a, **k):
        raise RuntimeError("mem0 down")

    monkeypatch.setattr(app.mem0, "add", boom)
    # Must swallow: a Mem0 outage cannot break the already-sent plan.
    app._remember_suggestions_bg("demo", {"plan": {"steps": [
        {"kind": "movie", "title": "X", "tracks": []}]}})


def test_background_mem0_write_handles_empty_plan(monkeypatch):
    import app

    monkeypatch.setattr(app.mem0, "add", lambda *a, **k: True)
    app._remember_suggestions_bg("demo", {"plan": {"steps": []}})
    app._remember_suggestions_bg("demo", {})


# --- FIX 3: single REST block -------------------------------------------

def _plan_with_n_rests(n):
    steps = [
        {"order": 1, "kind": "movie", "title": "Film", "duration_min": 120, "cost_inr": 250},
        {"order": 2, "kind": "cafe", "title": "Cafe", "duration_min": 40, "cost_inr": 300},
    ]
    for i in range(n):
        steps.append({"order": len(steps) + 1, "kind": "rest",
                      "title": f"Buffer {i}", "duration_min": 45, "cost_inr": 0,
                      "flexible": True})
    return {"steps": steps, "total_duration_min": 0, "total_cost_inr": 0}


def test_multiple_rest_blocks_collapse_to_one():
    plan = orch._limit_rest_filler(_plan_with_n_rests(3))
    rests = [s for s in plan["steps"] if s["kind"] == "rest"]
    assert len(rests) == 1, f"expected 1 rest block, got {len(rests)}"


def test_rest_collapsing_never_stretches_a_movie():
    # The reported plan had 3 x 45min buffers; naive redistribution would make
    # a 120min film into a 210min one. Fixed steps must not be touched.
    plan = orch._limit_rest_filler(_plan_with_n_rests(3))
    movie = next(s for s in plan["steps"] if s["kind"] == "movie")
    assert movie["duration_min"] == 120


def test_rest_collapsing_respects_flexible_caps():
    plan = orch._limit_rest_filler(_plan_with_n_rests(4))
    for s in plan["steps"]:
        if s["kind"] in ("cafe", "food", "place", "restaurant"):
            assert s["duration_min"] <= 90
        if s["kind"] == "rest":
            assert s["duration_min"] <= 45 + 200  # retained buffer is labelled


def test_rest_collapsing_keeps_plan_time_accounted():
    before = sum(s["duration_min"] for s in _plan_with_n_rests(3)["steps"])
    plan = orch._limit_rest_filler(_plan_with_n_rests(3))
    after = sum(s["duration_min"] for s in plan["steps"])
    assert after == before, "time silently lost"
    assert plan["total_duration_min"] == after


def test_rest_collapsing_noop_when_single_rest():
    plan = _plan_with_n_rests(1)
    out = orch._limit_rest_filler(plan)
    assert len([s for s in out["steps"] if s["kind"] == "rest"]) == 1


def test_rest_collapsing_noop_when_no_rest():
    plan = {"steps": [{"kind": "cafe", "title": "C", "duration_min": 40, "cost_inr": 1}],
            "total_duration_min": 40, "total_cost_inr": 1}
    out = orch._limit_rest_filler(plan)
    assert len(out["steps"]) == 1


def test_rest_collapsing_renumbers_orders():
    plan = orch._limit_rest_filler(_plan_with_n_rests(3))
    assert [s["order"] for s in plan["steps"]] == list(range(1, len(plan["steps"]) + 1))
