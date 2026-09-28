"""Señales de farmacia en retail.intent (fallback sin genérico)."""

from retail.intent import looks_pharmacy, parse
from retail.relevance import fold


def test_looks_pharmacy_keywords_and_forms():
    assert looks_pharmacy(fold("jarabe para la tos"))
    assert looks_pharmacy(fold("cápsulas blandas"))
    assert looks_pharmacy(fold("comprimido 500 mg"))
    assert looks_pharmacy(fold("solución oral"))
    assert looks_pharmacy(fold("analgésico"))


def test_looks_pharmacy_drug_suffix_and_dose():
    assert looks_pharmacy("rosuvastatina")
    assert looks_pharmacy("amoxicilina 500mg")
    assert looks_pharmacy(fold("losartán"))


def test_mg_alone_does_not_look_pharmacy():
    assert not looks_pharmacy("mg")
    assert not looks_pharmacy("500 mg")
    assert not looks_pharmacy("500mg")


def test_tech_and_fashion_do_not_look_pharmacy():
    assert not looks_pharmacy("notebook")
    assert not looks_pharmacy("tv 50 pulgadas")
    assert not looks_pharmacy("polera nike")
    assert not looks_pharmacy("xyzzy")


def test_parse_sets_pharmacy_flag():
    assert parse(fold("amoxicilina")).pharmacy is True
    assert parse("notebook").pharmacy is False
