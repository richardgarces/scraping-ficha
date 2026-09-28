from retail.http import HttpSession


def test_session_ignores_env_proxy():
    session = HttpSession()
    try:
        assert session._backend in {"curl_cffi", "httpx"}
        assert session._client.trust_env is False
    finally:
        session.close()
