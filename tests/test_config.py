import json

from jupydex.config import DEFAULT_PROFILE, load_connect_params


def test_load_connect_params_minimal(tmp_path):
    path = tmp_path / "jupydex.json"
    path.write_text(
        json.dumps(
            {
                "url": "http://example.com:8888/lab?token=abc",
                "workspace": "/remote/workspace",
            }
        ),
        encoding="utf-8",
    )

    params = load_connect_params(path)

    assert params.profile == DEFAULT_PROFILE
    assert params.url == "http://example.com:8888/lab?token=abc"
    assert params.workspace == "/remote/workspace"
    assert params.token is None
    assert params.mirror is None


def test_load_connect_params_full(tmp_path):
    path = tmp_path / "jupydex.json"
    path.write_text(
        json.dumps(
            {
                "profile": "remote",
                "url": "http://example.com:8888/lab",
                "token": "abc",
                "workspace": "/remote/workspace",
                "mirror": ".jupydex/mirrors/remote",
            }
        ),
        encoding="utf-8",
    )

    params = load_connect_params(path)

    assert params.profile == "remote"
    assert params.token == "abc"
    assert params.mirror == ".jupydex/mirrors/remote"
