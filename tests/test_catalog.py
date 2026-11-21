"""Adding a language profile from the catalog."""
import json
import shutil

from compa import catalog, settings


def test_languages_already_in_settings_are_not_offered():
    keys = [language.key for language in catalog.addable_languages()]

    assert "spanish" not in keys and "italian" in keys


def test_adding_a_language_writes_a_working_profile(tmp_path, monkeypatch):
    shutil.copy(settings.REPO / "settings.json", tmp_path / "settings.json")
    monkeypatch.setattr(catalog, "REPO", tmp_path)
    monkeypatch.setattr(settings, "REPO", tmp_path)

    catalog.add_language("italian", "B1")

    profile = settings.load_profile("italian")
    assert (profile.language, profile.level, profile.voice) == ("it", "B1", "kokoro:if_sara")
    assert "spanish" in json.loads((tmp_path / "settings.json").read_text())["languages"]
