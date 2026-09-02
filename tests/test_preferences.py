import json
from pathlib import Path

from preferences import Preferences, PreferenceStore


def test_preferences_round_trip_as_json(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    store = PreferenceStore(path)

    store.save(Preferences(geoip_auto_update=False))

    assert store.load().geoip_auto_update is False
    assert json.loads(path.read_text()) == {"geoip_auto_update": False}
    assert path.stat().st_mode & 0o777 == 0o600


def test_invalid_preferences_fall_back_to_defaults(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("not-json")

    assert PreferenceStore(path).load() == Preferences()
