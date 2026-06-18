from jupydex.config import DEFAULT_PROFILE, ConfigStore


def test_default_profile_name_falls_back_to_default(tmp_path):
    store = ConfigStore(tmp_path / "config.json")

    assert store.default_profile_name() == DEFAULT_PROFILE


def test_default_profile_name_reads_config(tmp_path):
    store = ConfigStore(tmp_path / "config.json")
    store.save_all({"default_profile": "lab1", "profiles": {}})

    assert store.default_profile_name() == "lab1"
