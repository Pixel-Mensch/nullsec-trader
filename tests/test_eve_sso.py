from __future__ import annotations

import pytest

from tests.shared import *  # noqa: F401,F403


def test_eve_sso_status_without_token_is_empty() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        sso = nst.EveSSOAuth(
            client_id="client-id",
            client_secret="",
            callback_url="http://localhost:12563/callback",
            user_agent="NullsecTrader/Test",
            token_path=os.path.join(tmpdir, "token.json"),
            metadata_path=os.path.join(tmpdir, "metadata.json"),
        )
        status = sso.describe_token_status()
    assert status["has_token"] is False
    assert status["valid"] is False
    assert status["character_id"] == 0


def test_eve_sso_ensure_token_requires_client_id() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        sso = nst.EveSSOAuth(
            client_id="",
            client_secret="",
            callback_url="http://localhost:12563/callback",
            user_agent="NullsecTrader/Test",
            token_path=os.path.join(tmpdir, "token.json"),
            metadata_path=os.path.join(tmpdir, "metadata.json"),
        )
        with pytest.raises(nst.SSOAuthError):
            sso.ensure_token(["esi-skills.read_skills.v1"], allow_login=False)
