from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List

# --- Unlock lists (these stay fixed, per your request) ---

AVAILABLE_CARS: List[str] = [
 "3","9","34","40","53","78","16","67","61","59","71","73","82","64","84","23","39","80","5","51","13","70","72","44",
 "32","87","30","10","28","75","89","18","74","29","7","79","86","19","60","38","22","88","68","49","63","6","26","24",
 "43","25","58","15","42","12","57","46","90","27","1","36","83","54","33","62","76","47","8","56","85","21","81","48",
 "69","35","20","31","77","93","91","92","95","97","94","96","98","99","100","101","104","102","103","105","107","109",
 "106","108","111","110","125","127","118","117","114","126","128","113","112","115","116","130","133","132","134","131",
 "135","137","142","141","140","139","136","138"
]

AVAILABLE_TRACKS: List[str] = [
 "17","18","11","12","23","35","15","24","16","1","5","2","6","19","20","36","25","26","29","30","39","31","37","40",
 "41","42","43","44","45","46","38","32","47","48","33","34","28","27"
]


@dataclass(frozen=True)
class Preset:
    name: str
    updates: Dict[str, Any]


def make_currency_updates(coins: int, rating_points: str, player_exp: str) -> Dict[str, Any]:
    # Keep ratingPoints/playerExp as strings because your sample shows quoted values.
    return {
        "coins": int(coins),
        "ratingPoints": str(rating_points),
        "playerExp": str(player_exp),
    }


def make_unlock_updates() -> Dict[str, Any]:
    return {
        "availableCars": AVAILABLE_CARS,
        "availableTracks": AVAILABLE_TRACKS,
    }


def make_stats_updates(
    time_in_game: str,
    races_played: str,
    drift_races_played: str,
    time_attack_races_played: str,
    mp_races_played: str,
    purchases_count: str,
    max_points_per_drift: str,
    max_points_per_race: str,
    average_points_per_race: str,
    cups1: str,
    cups2: str,
    cups3: str,
) -> Dict[str, Any]:
    # Keep these as strings (matches your snippet, including "1E+09").
    return {
        "timeInGame": str(time_in_game),
        "racesPlayed": str(races_played),
        "driftRacesPlayed": str(drift_races_played),
        "timeAttackRacesPlayed": str(time_attack_races_played),
        "MPRacesPlayed": str(mp_races_played),
        "purchasesCount": str(purchases_count),
        "maxPointsPerDrift": str(max_points_per_drift),
        "maxPointsPerRace": str(max_points_per_race),
        "averagePointsPerRace": str(average_points_per_race),
        "cups1": str(cups1),
        "cups2": str(cups2),
        "cups3": str(cups3),
    }
