"""Vérification légère de l'Action (scripts/check_updates.py) : saison,
décision d'export, alerte des matchs en retard. Sans réseau."""
from datetime import date, datetime, timedelta, timezone

from scripts.check_updates import alerts, current_season, decide, schedule_signature

NOW = datetime(2026, 11, 9, 18, 0, tzinfo=timezone.utc)
SNAP = {"season": 2026, "schedule": "abc", "finals": 120,
        "assets": {"stats_player/x": "2026-11-09T14:15:08Z", "pbp/y": "2026-11-09T14:13:16Z"}}


def test_current_season_starts_thursday_after_labor_day():
    # 2026 : Labor Day le lundi 7 septembre, coup d'envoi le jeudi 10.
    assert current_season(date(2026, 9, 9)) == 2025
    assert current_season(date(2026, 9, 10)) == 2026
    assert current_season(date(2027, 1, 15)) == 2026


def test_schedule_signature_counts_only_finals_of_the_season():
    csv_text = ("game_id,season,away_score,home_score\n"
                "2026_09_A_B,2026,24,17\n2026_09_C_D,2026,NA,NA\n2026_10_E_F,2026,,\n2025_01_G_H,2025,3,0\n")
    sig, n = schedule_signature(csv_text, 2026)
    assert n == 1
    assert sig != schedule_signature(csv_text.replace("24,17", "24,20"), 2026)[0]  # score corrigé


def test_decide():
    recent = NOW - timedelta(hours=3)
    assert decide(None, SNAP, None, NOW) == (True, "aucun export précédent en cache")
    assert decide(SNAP, SNAP, recent, NOW)[0] is False
    newer = {**SNAP, "assets": {**SNAP["assets"], "stats_player/x": "2026-11-09T17:00:00Z"}}
    changed, reason = decide(SNAP, newer, recent, NOW)
    assert changed and "stats_player/x" in reason
    scores = {**SNAP, "schedule": "def", "finals": 125}
    changed, reason = decide(SNAP, scores, recent, NOW)
    assert changed and "120 -> 125" in reason
    # Rien de neuf, mais dernier export il y a plus de 24 h : rafraîchissement quotidien.
    changed, reason = decide(SNAP, SNAP, NOW - timedelta(hours=25), NOW)
    assert changed and "quotidien" in reason
    assert decide(SNAP, {**SNAP, "season": 2027}, recent, NOW)[0] is True


def game(gid, kickoff_hours_ago, final, pending):
    return {"game_id": gid, "label": gid, "final": final, "stats_pending": pending,
            "kickoff_utc": (NOW - timedelta(hours=kickoff_hours_ago)).isoformat()}


def test_alerts_only_after_24_hours():
    status = {"games": [
        game("ok", 30, True, False),               # terminé, stats publiées
        game("recent", 20, True, True),            # sans stats, mais fini depuis 16 h
        game("late", 29, True, True),              # sans stats, fini depuis 25 h
        game("no_score", 29, False, False),        # commencé il y a 29 h, pas de score
        game("future", -48, False, False),         # à venir
        {"game_id": "tbd", "final": False, "stats_pending": False, "kickoff_utc": None},
    ]}
    late = alerts(status, NOW)
    assert len(late) == 2
    assert late[0].startswith("late") and "sans stats" in late[0]
    assert late[1].startswith("no_score") and "sans score" in late[1]
    assert alerts({"games": [game("x", 27, True, True)]}, NOW) == []  # 23 h après la fin
