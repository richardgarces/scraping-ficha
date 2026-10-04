from retail.web import anti_scraping


def setup_function():
    anti_scraping.reset_limits()


def test_visitor_signature_expires_and_rejects_tampering(monkeypatch):
    monkeypatch.setenv("RETAIL_SECRET", "test-secret")
    token = anti_scraping.sign_visitor(now=1_000)
    assert anti_scraping.valid_visitor(token, now=1_001)
    assert not anti_scraping.valid_visitor(token + "x", now=1_001)
    assert not anti_scraping.valid_visitor(token, now=1_000 + anti_scraping.VISITOR_MAX_AGE + 1)


def test_direct_or_automated_data_access_is_rejected(monkeypatch):
    monkeypatch.setenv("RETAIL_SECRET", "test-secret")
    browser = {"user-agent": "Mozilla/5.0", "x-forwarded-for": "203.0.113.10"}
    direct = anti_scraping.inspect_request("/api/catalog", "GET", browser, {}, None, now=10)
    assert direct and direct.status_code == 403

    token = anti_scraping.sign_visitor()
    bot = anti_scraping.inspect_request(
        "/api/catalog", "GET", {"user-agent": "python-requests/2.32"},
        {anti_scraping.VISITOR_COOKIE: token}, None, now=10,
    )
    assert bot and bot.status_code == 403


def test_browser_with_page_cookie_can_read_but_is_rate_limited(monkeypatch):
    monkeypatch.setenv("RETAIL_SECRET", "test-secret")
    browser = {"user-agent": "Mozilla/5.0", "x-forwarded-for": "203.0.113.11"}
    cookies = {anti_scraping.VISITOR_COOKIE: anti_scraping.sign_visitor()}
    for index in range(20):
        assert anti_scraping.inspect_request(
            "/api/search/stream", "GET", browser, cookies, None, now=float(index)
        ) is None
    blocked = anti_scraping.inspect_request(
        "/api/search/stream", "GET", browser, cookies, None, now=20.0
    )
    assert blocked and blocked.status_code == 429 and blocked.retry_after


def test_health_static_and_authenticated_operations_are_exempt():
    bot = {"user-agent": "curl/8.0"}
    assert anti_scraping.inspect_request("/api/health", "GET", bot, {}, None) is None
    assert anti_scraping.inspect_request("/static/app.js", "GET", bot, {}, None) is None
    assert anti_scraping.inspect_request("/offer-shots/lider_1.png", "GET", {"user-agent": ""}, {}, None) is None
    assert anti_scraping.inspect_request("/api/admin/stats", "GET", bot, {}, None) is None
    assert anti_scraping.inspect_request("/api/price-alert", "GET", bot, {}, None) is None
