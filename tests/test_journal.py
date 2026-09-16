import pytest

from moodos import journal
from moodos.db import init_db
from moodos.mood_map import (
    dominant_plan_kind,
    intensity_score,
    mood_valence,
    plan_summary,
    time_bucket,
)

init_db()

TEST_USER = "journal_test"


@pytest.fixture(autouse=True)
def clean_journal():
    journal.clear_journal(TEST_USER)
    yield
    journal.clear_journal(TEST_USER)


def log(user_id, mood, intensity="medium", days_ago=0, rainy=False, plan=None):
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return journal.log_mood_entry(
        user_id,
        {"current_mood": mood, "desired_mood": "relaxed", "intensity": intensity, "social": "solo"},
        {"condition": "rain" if rainy else "clear", "rainy": rainy, "temperature_c": 24},
        plan or {"steps": [{"kind": "cafe", "title": "Cafe"}]},
        now=now,
    )


def test_mood_valence_lexicon():
    assert mood_valence("stressed") == -1.0
    assert mood_valence("de-stressed") == 0.6
    assert mood_valence("exhausted") == -0.6
    assert mood_valence("low energy") == -0.3
    assert mood_valence("relaxed") == 0.5
    assert mood_valence("ecstatic") == 1.0
    assert mood_valence("total gibberish") == 0.0
    assert mood_valence(None) == 0.0


def test_intensity_and_buckets():
    assert intensity_score("low") == 1
    assert intensity_score("high") == 3
    assert intensity_score(None) == 2
    assert time_bucket(9) == "morning"
    assert time_bucket(14) == "afternoon"
    assert time_bucket(19) == "evening"
    assert time_bucket(23) == "night"


def test_plan_derivations():
    plan = {"steps": [{"kind": "cafe"}, {"kind": "travel"}, {"kind": "movie"}, {"kind": "movie"}]}
    assert dominant_plan_kind(plan) == "movie"
    assert dominant_plan_kind({"steps": []}) is None
    assert plan_summary({"steps": [{"title": "Walk"}, {"kind": "travel"}, {"title": "Cafe"}]}) == "Walk → Cafe"


def test_log_and_list_roundtrip():
    log(TEST_USER, "tired")
    entries = journal.recent_entries(TEST_USER)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["current_mood"] == "tired"
    assert entry["mood_valence"] == -0.6
    assert entry["intensity_score"] == 2
    assert entry["plan_kind"] == "cafe"
    assert entry["source"] == "plan"


def test_weekly_trend_groups_by_week():
    log(TEST_USER, "tired", days_ago=1)
    log(TEST_USER, "exhausted", days_ago=2)
    log(TEST_USER, "happy", days_ago=25)
    trend = journal.weekly_trend(TEST_USER, weeks=6)
    assert len(trend) >= 2  # recent two days + older day land in 2+ buckets
    assert sum(r["count"] for r in trend) == 3
    weeks = [r["week"] for r in trend]
    assert weeks == sorted(weeks)  # ordered oldest -> newest
    assert trend[-1]["top_mood"] in ("tired", "exhausted")  # newest bucket is the recent two


def test_weekday_and_time_of_day():
    log(TEST_USER, "tired")
    weekday = journal.by_weekday(TEST_USER)
    assert len(weekday) == 7
    today = [r for r in weekday if r["count"] > 0]
    assert len(today) == 1
    tod = journal.by_time_of_day(TEST_USER)
    assert sum(r["count"] for r in tod) == 1


def test_weather_correlation_split():
    log(TEST_USER, "stressed", rainy=True, days_ago=1)
    log(TEST_USER, "happy", rainy=False, days_ago=2)
    weather = journal.weather_correlation(TEST_USER)
    assert weather["rainy"]["count"] == 1
    assert weather["rainy"]["avg_valence"] == -1.0
    assert weather["clear"]["avg_valence"] == 0.8


def test_insight_needs_minimum_entries():
    log(TEST_USER, "tired")
    assert journal.insight(TEST_USER) is None


def test_insight_low_energy_fires():
    for days, mood in [(1, "tired"), (2, "exhausted"), (3, "bored")]:
        log(TEST_USER, mood, intensity="low", days_ago=days)
    for days in (14, 16, 20, 25):
        log(TEST_USER, "happy", intensity="medium", days_ago=days)
    insight = journal.insight(TEST_USER)
    assert insight is not None
    assert insight["kind"] == "low_energy"


def test_delete_entry_and_clear():
    entry_id = log(TEST_USER, "tired")
    assert journal.delete_entry(TEST_USER, entry_id) is True
    assert journal.delete_entry(TEST_USER, entry_id) is False
    log(TEST_USER, "happy")
    assert journal.clear_journal(TEST_USER) == 1
    assert journal.recent_entries(TEST_USER) == []


def test_react_once_per_entry():
    entry_id = log(TEST_USER, "tired")
    assert journal.is_reactable_entry(TEST_USER, entry_id) is True
    assert journal.react_to_entry(TEST_USER, entry_id, "happy") is True
    assert journal.is_reactable_entry(TEST_USER, entry_id) is False
    assert journal.react_to_entry(TEST_USER, entry_id, "sad") is False
    entry = journal.recent_entries(TEST_USER)[0]
    assert entry["mood_reaction"] == "happy"


def test_react_validates_label():
    entry_id = log(TEST_USER, "tired")
    with pytest.raises(ValueError):
        journal.react_to_entry(TEST_USER, entry_id, "love_it")


def test_react_to_missing_entry_is_false():
    assert journal.react_to_entry(TEST_USER, 999999, "sad") is False
    assert journal.is_reactable_entry(TEST_USER, 999999) is False


def test_summary_strip_reports_rated_state():
    e1 = log(TEST_USER, "tired")
    log(TEST_USER, "happy")
    journal.react_to_entry(TEST_USER, e1, "neutral")
    strip = journal.summary_strip(TEST_USER)
    assert strip["total_shown"] == 2
    assert strip["rated_count"] == 1
    by_id = {it["id"]: it for it in strip["entries"]}
    assert by_id[e1]["mood_reaction"] == "neutral"
    assert by_id[e1]["reactable"] is False
    other = [it for it in strip["entries"] if it["id"] != e1][0]
    assert other["reactable"] is True
    assert other["mood_reaction"] is None
    assert "happy" in other["line"]
    assert f"Cafe" in other["line"]


def test_insight_reaction_patterns():
    def seed(moods, reacted):
        for i, m in enumerate(moods):
            entry = log(TEST_USER, m, days_ago=i)
            if i < len(reacted):
                journal.react_to_entry(TEST_USER, entry, reacted[i])

    seed(["happy", "neutral", "good", "fine", "great"] * 2, ["sad"] * 7)
    low = journal.insight(TEST_USER)
    assert low is not None
    assert low["kind"] == "plans_missing"

    journal.clear_journal(TEST_USER)
    seed(["low", "meh", "bored", "low", "meh", "low", "meh",
          "stressed", "stressed", "stressed"], ["happy"] * 7)
    insight = journal.insight(TEST_USER)
    assert insight is not None
    assert insight["kind"] == "plans_landing"

    journal.clear_journal(TEST_USER)
    seed(["happy", "great", "good", "low", "meh"] * 2, ["sad", "sad", "happy"] + ["happy"] * 4)
    pat = journal.insight(TEST_USER)
    assert pat is not None
    assert pat["kind"] == "reaction_mismatch"