from retail.batch.rules import Alert
from retail.notification_preferences import alert_kind, normalize_preferences, wants_alert


def offer(rule="price_drop_percent", **extra):
    return Alert(
        catalog_id="tv", query="tv", rule=rule, name="TV", store="tienda",
        price=100, previous_price=200, message="oferta", url=None,
        compare_code="tv-1", extra=extra,
    )


def test_preferences_are_opt_in_and_sanitized():
    assert normalize_preferences(None) == {
        "channels": [], "kinds": ["watch"],
        "min_discount_self": 0.0, "min_discount_other_stores": 0.0,
        "email_categories": [], "email_min_real_discount": 0.0,
        "payment_cards": [], "preferred_sizes": [], "shipping_region": "",
    }
    prefs = normalize_preferences({
        "channels": ["email", "push", "invalid", "email"],
        "kinds": ["real", "invalid"],
        "min_discount_self": 120,
        "min_discount_other_stores": -5,
    })
    assert prefs == {
        "channels": ["email", "push"], "kinds": ["real"],
        "min_discount_self": 100.0, "min_discount_other_stores": 0.0,
        "email_categories": [], "email_min_real_discount": 0.0,
        "payment_cards": [], "preferred_sizes": [], "shipping_region": "",
    }


def test_payment_and_variant_preferences_filter_ineligible_alerts():
    card = offer("common_discount", percent=30, price_basis="card", payment_card_name="CMR Falabella")
    sizes = offer("common_discount", percent=30, only_extreme_sizes=True, available_variants=["36", "47"])
    assert not wants_alert({"kinds": ["common"]}, card)
    assert wants_alert({"kinds": ["common"], "payment_cards": ["CMR Falabella"]}, card)
    assert not wants_alert({"kinds": ["common"], "preferred_sizes": ["40"]}, sizes)
    assert wants_alert({"kinds": ["common"], "preferred_sizes": ["47"]}, sizes)


def test_offer_types_and_independent_minimums():
    common = offer("common_discount", percent=20)
    real = offer("below_median", percent_vs_median=-25)
    super_offer = offer("cross_store_gap", gap_percent=51)
    watch = offer("watch_target", target_price=100)
    assert [alert_kind(item) for item in (common, real, super_offer, watch)] == [
        "common", "real", "super", "watch",
    ]
    assert wants_alert({"kinds": ["real"], "min_discount_self": 20}, real)
    assert not wants_alert({"kinds": ["real"], "min_discount_self": 30}, real)
    assert wants_alert({"kinds": ["super"], "min_discount_other_stores": 50}, super_offer)
    assert wants_alert({"kinds": ["watch"], "min_discount_self": 99}, watch)


def test_email_can_filter_categories_and_real_discount_without_affecting_telegram():
    real = offer("below_median", percent_vs_median=-25)
    real.category = "Tecnología"
    prefs = {
        "kinds": ["real"],
        "email_categories": ["tecnologia"],
        "email_min_real_discount": 30,
    }
    assert not wants_alert(prefs, real, channel="email")
    assert wants_alert(prefs, real, channel="telegram")
    prefs["email_min_real_discount"] = 20
    assert wants_alert(prefs, real, channel="email")
    prefs["email_categories"] = ["hogar"]
    assert not wants_alert(prefs, real, channel="email")


def test_batch_notification_category_has_priority_over_catalog_label():
    real = offer("below_median", percent_vs_median=-40, notification_category="tecnologia")
    real.category = "Smartphones"
    assert wants_alert(
        {"kinds": ["real"], "email_categories": ["tecnologia"]},
        real,
        channel="email",
    )
