"""Negative fixtures ensure reachability does not become a false unlock claim."""
import pytest
from tests.test_unlock import FakeSession, run
from core.unlock import check_chatgpt, check_claude, check_gemini, check_netflix, check_youtube


@pytest.mark.parametrize("probe,url", [
    (check_claude, "https://claude.ai/"), (check_gemini, "https://gemini.google.com"),
    (check_netflix, "https://www.netflix.com/title/81280792"),
    (check_youtube, "https://www.youtube.com/premium"),
])
@pytest.mark.parametrize("status,body,expected", [
    (403, "<title>Just a moment...</title> cf-chl-test", "unknown"),
    (200, "<title>Just a moment...</title> challenge-platform", "unknown"),
    (429, "rate limited", "unknown"), (503, "maintenance", "failed"),
])
def test_challenge_and_server_errors_never_mean_unlocked(probe, url, status, body, expected):
    assert run(probe(FakeSession([(url, status, body, url)])))["status"] == expected


@pytest.mark.parametrize("status,body", [(403, "forbidden"), (401, '{"error":"unauthorized"}'),
    (200, "<html>unexpected page</html>"), (200, "<title>Just a moment</title>")])
def test_chatgpt_unexpected_responses_remain_unknown(status, body):
    session = FakeSession([( "https://api.openai.com", status, body, None),
                           ("https://ios.chat.openai.com", status, body, None)])
    assert run(check_chatgpt(session))["status"] == "unknown"


def test_netflix_signup_redirect_is_unknown():
    session = FakeSession([("https://www.netflix.com/title/81280792", 200, "Sign up", "https://www.netflix.com/signup")])
    assert run(check_netflix(session)) == {"status": "unknown"}


def test_claude_nonchallenge_forbidden_is_unknown():
    assert run(check_claude(FakeSession([("https://claude.ai/", 403, "forbidden", None)])))["status"] == "unknown"


def test_gemini_explicit_regional_message_is_blocked():
    assert run(check_gemini(FakeSession([("https://gemini.google.com", 200, "Not supported in your country", None)]))) == {"status": "no"}
