from jupydex.config import DEFAULT_PROFILE, ConfigStore, MirrorConfig, Profile, ProfileManager


def test_default_profile_name_falls_back_to_default(tmp_path):
    store = ConfigStore(tmp_path / "config.json")

    assert store.default_profile_name() == DEFAULT_PROFILE


def test_default_profile_name_reads_config(tmp_path):
    store = ConfigStore(tmp_path / "config.json")
    store.save_all({"default_profile": "lab1", "profiles": {}})

    assert store.default_profile_name() == "lab1"


def test_set_default_profile_requires_existing_profile(tmp_path):
    store = ConfigStore(tmp_path / "config.json")
    store.save_all({"profiles": {"lab1": {}}})

    store.set_default_profile("lab1")

    assert store.default_profile_name() == "lab1"


def test_set_default_profile_rejects_missing_profile(tmp_path):
    store = ConfigStore(tmp_path / "config.json")
    store.save_all({"profiles": {}})

    try:
        store.set_default_profile("lab1")
    except KeyError as exc:
        assert "lab1" in str(exc)
    else:
        raise AssertionError("Expected KeyError")


def test_remove_profile_selects_next_default(tmp_path):
    store = ConfigStore(tmp_path / "config.json")
    store.save_all(
        {
            "default_profile": "lab2",
            "profiles": {
                "lab1": {},
                "lab2": {},
            },
        }
    )

    assert store.remove_profile("lab2") == "lab1"
    assert store.default_profile_name() == "lab1"


def test_remove_profile_clears_default_when_empty(tmp_path):
    store = ConfigStore(tmp_path / "config.json")
    store.save_all({"default_profile": "lab1", "profiles": {"lab1": {}}})

    assert store.remove_profile("lab1") is None
    assert store.load_all() == {"profiles": {}}


def test_remove_profile_rejects_missing_profile(tmp_path):
    store = ConfigStore(tmp_path / "config.json")
    store.save_all({"profiles": {}})

    try:
        store.remove_profile("lab1")
    except KeyError as exc:
        assert "lab1" in str(exc)
    else:
        raise AssertionError("Expected KeyError")


def test_mirror_config_uses_defaults(tmp_path):
    store = ConfigStore(tmp_path / "config.json")

    mirror_config = store.mirror_config()

    assert mirror_config.max_file_size_mb == 5.0
    assert ".venv" in mirror_config.ignore_dirs
    assert "*.safetensors" in mirror_config.ignore_globs


def test_mirror_config_can_be_saved(tmp_path):
    store = ConfigStore(tmp_path / "config.json")
    mirror_config = MirrorConfig(
        max_file_size_mb=None,
        ignore_dirs=["venv"],
        ignore_globs=["*.pt"],
    )

    store.save_mirror_config(mirror_config)

    assert store.mirror_config() == mirror_config


def test_profile_manager_wraps_profile_operations(tmp_path):
    manager = ProfileManager(ConfigStore(tmp_path / "config.json"))
    profile = Profile(
        base_url="http://example.com",
        token="tok",
        workspace="workspace",
        workspace_input="/remote/workspace",
        mirror_path="/tmp/mirror",
    )

    manager.save("lab1", profile)
    manager.set_default("lab1")
    assert manager.remove("lab1") is None

    manager.save("lab1", profile)
    assert manager.get("lab1") == profile
    assert manager.list() == {"lab1": profile}
