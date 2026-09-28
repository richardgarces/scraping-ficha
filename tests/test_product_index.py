from retail.index.products import (
    ensure_loaded,
    feed_discovered_groups,
    feed_query_aliases,
    feed_search,
    leftover_alias_tokens,
    load_active_seed,
    load_seed,
    products_for_letter,
    resolve,
    stores_for,
    unique_product_id,
)
from retail.registry import GROUP_TITLES, STORE_GROUP, list_stores


class MemoryRedis:
    def __init__(self) -> None:
        self.strings: dict[str, str] = {}
        self.hashes: dict[str, dict[str, str]] = {}
        self.sets: dict[str, set[str]] = {}
        self.zsets: dict[str, dict[str, float]] = {}
        self.ttls: dict[str, int] = {}

    def _drop(self, key: str) -> None:
        self.strings.pop(key, None)
        self.hashes.pop(key, None)
        self.sets.pop(key, None)
        self.zsets.pop(key, None)

    def ping(self) -> bool:
        return True

    def get(self, key: str) -> str | None:
        return self.strings.get(key)

    def set(self, name: str, value: str, ex=None, nx=False, xx=False, **kwargs) -> bool:
        exists = name in self.strings
        if nx and exists:
            return False
        if xx and not exists:
            return False
        self._drop(name)
        self.strings[name] = value
        if ex is not None:
            self.ttls[name] = int(ex)
        return True

    def mget(self, keys: list[str]) -> list[str | None]:
        return [self.get(key) for key in keys]

    def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            if key in self.strings or key in self.hashes or key in self.sets or key in self.zsets:
                removed += 1
            self._drop(key)
        return removed

    def hset(self, name: str, key: str | None = None, value: str | None = None, mapping: dict | None = None) -> int:
        row = self.hashes.setdefault(name, {})
        written = 0
        if mapping:
            for field, item in mapping.items():
                row[str(field)] = str(item)
                written += 1
        if key is not None:
            row[str(key)] = str(value)
            written += 1
        return written

    def hget(self, name: str, key: str) -> str | None:
        return (self.hashes.get(name) or {}).get(key)

    def hgetall(self, name: str) -> dict[str, str]:
        return dict(self.hashes.get(name) or {})

    def sadd(self, name: str, *members: str) -> int:
        bucket = self.sets.setdefault(name, set())
        before = len(bucket)
        bucket.update(str(item) for item in members)
        return len(bucket) - before

    def smembers(self, name: str) -> set[str]:
        return set(self.sets.get(name) or set())

    def zadd(self, name: str, mapping: dict[str, float]) -> int:
        bucket = self.zsets.setdefault(name, {})
        bucket.update(mapping)
        return len(mapping)


class MemorySeedRepo:
    def __init__(self, rows: list[dict] | None = None) -> None:
        self.seed: dict[str, dict] = {}
        self.queries: list[dict] = []
        for row in rows or []:
            self.seed[row["id"]] = dict(row)

    def product_index_seed_empty(self) -> bool:
        return not self.seed

    def load_product_index_seed(self) -> tuple[int, list[dict]]:
        rows = [dict(item) for item in sorted(self.seed.values(), key=lambda row: row["id"])]
        version = int(rows[0].get("version") or 1) if rows else 1
        return version, rows

    def sync_product_index_seed(self, products: list[dict], version: int) -> int:
        inserted = 0
        for item in products:
            ident = item["id"]
            if ident in self.seed:
                self.add_product_index_aliases(ident, list(item["aliases"]))
                continue
            self.seed[ident] = {
                "id": ident,
                "name": item["name"],
                "aliases": list(item["aliases"]),
                "groups": list(item["groups"]),
                "version": version,
                "hit_count": 0,
                "last_seen_at": None,
                "updated_at": "now",
            }
            inserted += 1
        return inserted

    def bump_product_index_hit(self, product_id: str) -> None:
        row = self.seed.get(product_id)
        if not row:
            return
        row["hit_count"] = int(row.get("hit_count") or 0) + 1
        row["last_seen_at"] = "seen"

    def save_product_index_query(self, document: dict) -> None:
        self.queries.append(dict(document))

    def add_product_index_aliases(self, product_id: str, aliases: list[str]) -> list[str]:
        row = self.seed.get(product_id)
        if not row:
            return []
        existing = list(row.get("aliases") or [])
        extra = [item for item in aliases if item not in existing]
        if extra:
            row["aliases"] = existing + extra
            row["updated_at"] = "now"
        return extra

    def add_product_index_groups(
        self,
        product_id: str,
        groups: list[str],
        *,
        store_ids: list[str] | None = None,
    ) -> list[str]:
        row = self.seed.get(product_id)
        if not row:
            return []
        existing = list(row.get("groups") or [])
        extra = [item for item in groups if item not in existing]
        if extra:
            row["groups"] = existing + extra
            row["extra_groups"] = list(dict.fromkeys([*(row.get("extra_groups") or []), *extra]))
        if store_ids:
            row["discovered_stores"] = list(
                dict.fromkeys([*(row.get("discovered_stores") or []), *store_ids])
            )
        row["updated_at"] = "now"
        return extra

    def unmatched_product_index_queries(self, limit: int = 50) -> list[dict]:
        rows = [item for item in self.queries if item.get("unmatched")]
        return list(reversed(rows))[:limit]


def _reset_memory() -> None:
    from retail.index import products as index_mod

    index_mod._MEMORY = None
    index_mod._SWEEPS = {}


def _mute_other_stores(monkeypatch) -> None:
    monkeypatch.setattr("retail.search.claim_unique_sweep", lambda *args, **kwargs: False)
    monkeypatch.setattr("retail.search.launch_other_store_sweep", lambda *args, **kwargs: None)


def _available() -> list[str]:
    return [spec.id for spec in list_stores()]


def test_seed_aliases_unique_and_groups_exist():
    _version, _digest, products = load_seed()
    assert len(products) >= 40
    seen: dict[str, str] = {}
    for product in products:
        assert product.groups
        for group in product.groups:
            assert group in GROUP_TITLES
            assert group != "otros"
        for key in product.keys():
            owner = seen.get(key)
            assert owner in {None, product.id}, f"alias {key} en {owner} y {product.id}"
            seen[key] = product.id
    ids = {item.id for item in products}
    assert {"tv", "leche", "taladro", "celular", "paracetamol", "ozempic", "medicamento"} <= ids


def test_resolve_tv_aliases_and_extra_words():
    assert resolve("tv", client=False).id == "tv"
    assert resolve("televisor", client=False).id == "tv"
    assert resolve("tv 50 pulgadas", client=False).id == "tv"
    assert resolve("smart tv samsung", client=False).id == "tv"
    assert resolve("mini led", client=False).id == "tv"
    assert resolve("miniled", client=False).id == "tv"
    assert resolve("tv mini led", client=False).id == "tv"


def test_resolve_leche_with_brand():
    assert resolve("leche colun", client=False).id == "leche"


def test_resolve_unknown_is_none():
    assert resolve("xyzzy", client=False) is None


def test_unmatched_query_does_not_select_all_stores():
    available = _available()
    found = stores_for("xyzzy", available, client=False)
    assert found is not None
    assert found
    assert len(found) < len(available)
    assert {STORE_GROUP[store_id] for store_id in found} <= {"retail", "tecnologia"}
    assert "falabella" in found
    assert "pcfactory" in found
    assert "ahumada" not in found
    assert "nike" not in found
    assert stores_for("xyzzy", ["falabella", "ahumada"], client=False) == ["falabella"]


def test_vehicle_query_adds_auto_sources_to_fallback():
    found = stores_for("toyota yaris 2024", _available(), client=False)
    assert found is not None
    assert "chileautos" in found
    assert "autocosmos" in found


def test_letter_t_includes_tv():
    ids = {item.id for item in products_for_letter("t", client=False)}
    assert "tv" in ids
    assert "tablet" in ids
    assert "taladro" in ids


def test_stores_for_taladro_stays_in_ferreteria_and_retail():
    found = stores_for("taladro", _available(), client=False)
    assert found is not None
    groups = {STORE_GROUP[store_id] for store_id in found}
    assert groups <= {"ferreteria", "retail"}
    assert "ferreteria" in groups
    assert "sodimac" in found
    assert "ahumada" not in found
    assert "lider" not in found


def test_resolve_ozempic_routes_to_farmacias():
    product = resolve("ozempic", client=False)
    assert product is not None
    assert product.id == "ozempic"
    assert "farmacias" in product.groups
    assert resolve("semaglutida", client=False).id == "ozempic"
    found = stores_for("ozempic", _available(), client=False)
    assert found is not None
    groups = {STORE_GROUP[store_id] for store_id in found}
    assert "farmacias" in groups
    assert groups <= {"farmacias", "supermercados", "retail"}
    assert "ahumada" in found
    assert "cruzverde" in found
    assert "salcobrand" in found
    assert "drsimi" in found
    assert "dellanatura" in found


def test_resolve_medicamento_routes_to_farmacias():
    product = resolve("medicamento", client=False)
    assert product is not None
    assert product.id == "medicamento"
    assert "farmacias" in product.groups
    assert resolve("farmaco", client=False).id == "medicamento"
    assert resolve("amoxicilina", client=False).id == "medicamento"
    assert resolve("jarabe", client=False).id == "medicamento"
    assert resolve("comprimido", client=False).id == "medicamento"
    found = stores_for("remedio", _available(), client=False)
    assert found is not None
    assert "ahumada" in found
    assert "salcobrand" in found


def test_med_like_queries_include_farmacias():
    available = _available()
    for query in ("ozempic", "paracetamol", "amoxicilina", "jarabe tos"):
        found = stores_for(query, available, client=False)
        assert found is not None, query
        assert "ahumada" in found, query
        assert "farmacias" in {STORE_GROUP[s] for s in found}, query


def test_notebook_does_not_prefer_farmacias():
    found = stores_for("notebook", _available(), client=False)
    assert found is not None
    groups = {STORE_GROUP[store_id] for store_id in found}
    assert "tecnologia" in groups
    assert "farmacias" not in groups
    assert "ahumada" not in found
    assert resolve("notebook", client=False).id == "notebook"


def test_tv_does_not_route_to_farmacias_first():
    found = stores_for("tv", _available(), client=False)
    assert found is not None
    assert "ahumada" not in found
    assert "farmacias" not in {STORE_GROUP[s] for s in found}


def test_unmatched_druglike_adds_farmacias_random_does_not():
    available = _available()
    # Marca/INN no sembrada: sufijo tipo fármaco → farmacias en fallback.
    medical = stores_for("rosuvastatina", available, client=False)
    assert medical is not None
    assert resolve("rosuvastatina", client=False) is None
    assert "ahumada" in medical
    assert {STORE_GROUP[s] for s in medical} <= {
        "retail",
        "tecnologia",
        "farmacias",
        "supermercados",
    }
    # Palabra random: sin farmacias.
    random_hit = stores_for("xyzzy", available, client=False)
    assert "ahumada" not in random_hit
    assert {STORE_GROUP[s] for s in random_hit} <= {"retail", "tecnologia"}


def test_ozempic_beats_medicamento_forms():
    assert resolve("ozempic inyeccion", client=False).id == "ozempic"
    assert resolve("inyeccion", client=False).id == "medicamento"


def test_silla_de_auto_beats_silla():
    assert resolve("silla de auto bebe", client=False).id == "silla-auto"
    assert resolve("silla gamer", client=False).id == "silla"


def test_redis_load_roundtrip():
    redis = MemoryRedis()
    meta = ensure_loaded(client=redis, force=True, repo=False)
    assert meta["backend"] == "redis"
    assert meta["source"] == "json"
    assert meta["count"] >= 40
    assert redis.hget("retail:pindex:meta", "count") == str(meta["count"])
    assert redis.hget("retail:pindex:meta", "source") == "json"
    assert redis.get("retail:pindex:alias:televisor") == "tv"
    assert "tv" in redis.smembers("retail:pindex:letter:t")
    assert resolve("tv 50 pulgadas", client=redis).id == "tv"
    assert resolve("leche colun", client=redis).id == "leche"
    found = stores_for("taladro", _available(), client=redis)
    assert found is not None
    assert "sodimac" in found
    assert "ahumada" not in found


def test_search_routes_tv_when_stores_not_forced(monkeypatch):
    from retail.search import iter_search_events

    _mute_other_stores(monkeypatch)
    monkeypatch.setattr("retail.search.lookup_search_result", lambda *args, **kwargs: None)
    monkeypatch.setattr("retail.search.lookup_store_products", lambda *args, **kwargs: {})
    monkeypatch.setattr("retail.search.store_search_result", lambda *args, **kwargs: None)
    monkeypatch.setattr("retail.search.store_store_products", lambda *args, **kwargs: None)
    monkeypatch.setattr("retail.search.connect_repo", lambda: None)
    monkeypatch.setattr("retail.search.connect_qdrant", lambda: None)
    monkeypatch.setattr("retail.search.scrape_store", lambda *args, **kwargs: ([], None))
    monkeypatch.setattr("retail.index.products.connect_redis", lambda: None)

    events = list(iter_search_events("tv", source="scrape", persist=False, delay=0, timeout=1))
    result = events[-1]["result"]
    stores = result["stores"]
    assert result["product_index"]["id"] == "tv"
    assert result["product_index"]["applied"] is True
    assert "pcfactory" in stores
    assert "falabella" in stores
    assert "ahumada" not in stores
    assert "audiomusica" not in stores
    assert len(stores) < len(_available())


def test_search_routes_when_all_stores_listed(monkeypatch):
    from retail.search import iter_search_events

    _mute_other_stores(monkeypatch)
    monkeypatch.setattr("retail.search.lookup_search_result", lambda *args, **kwargs: None)
    monkeypatch.setattr("retail.search.lookup_store_products", lambda *args, **kwargs: {})
    monkeypatch.setattr("retail.search.store_search_result", lambda *args, **kwargs: None)
    monkeypatch.setattr("retail.search.store_store_products", lambda *args, **kwargs: None)
    monkeypatch.setattr("retail.search.connect_repo", lambda: None)
    monkeypatch.setattr("retail.search.connect_qdrant", lambda: None)
    monkeypatch.setattr("retail.search.scrape_store", lambda *args, **kwargs: ([], None))
    monkeypatch.setattr("retail.index.products.connect_redis", lambda: None)

    events = list(
        iter_search_events(
            "tv",
            source="scrape",
            stores=_available(),
            persist=False,
            delay=0,
            timeout=1,
        )
    )
    result = events[-1]["result"]
    assert result["product_index"]["applied"] is True
    assert "ahumada" not in result["stores"]


def test_search_keeps_explicit_store_subset(monkeypatch):
    from retail.search import iter_search_events

    _mute_other_stores(monkeypatch)
    monkeypatch.setattr("retail.search.lookup_search_result", lambda *args, **kwargs: None)
    monkeypatch.setattr("retail.search.lookup_store_products", lambda *args, **kwargs: {})
    monkeypatch.setattr("retail.search.store_search_result", lambda *args, **kwargs: None)
    monkeypatch.setattr("retail.search.store_store_products", lambda *args, **kwargs: None)
    monkeypatch.setattr("retail.search.connect_repo", lambda: None)
    monkeypatch.setattr("retail.search.connect_qdrant", lambda: None)
    monkeypatch.setattr("retail.search.scrape_store", lambda *args, **kwargs: ([], None))
    monkeypatch.setattr("retail.index.products.connect_redis", lambda: None)

    events = list(
        iter_search_events("tv", source="scrape", stores=["lider"], persist=False, delay=0, timeout=1)
    )
    result = events[-1]["result"]
    assert result["stores"] == ["lider"]
    assert result["product_index"]["id"] == "tv"
    assert result["product_index"]["applied"] is False


def test_mongo_bootstraps_from_json_when_empty():
    repo = MemorySeedRepo()
    version, _digest, products, source = load_active_seed(repo=repo, sync_json=True)
    assert source == "mongo"
    assert version == 1
    assert len(products) >= 40
    assert "tv" in repo.seed
    assert repo.seed["tv"]["hit_count"] == 0


def test_mongo_seed_is_not_overwritten_by_json():
    repo = MemorySeedRepo()
    try:
        load_active_seed(repo=repo, sync_json=True)
        repo.seed["tv"]["aliases"] = ["televisor", "pantalla-mongo"]
        repo.seed["tv"]["hit_count"] = 9
        _version, _digest, products, source = load_active_seed(repo=repo, sync_json=True)
        assert source == "mongo"
        assert repo.seed["tv"]["hit_count"] == 9
        assert "pantalla-mongo" in repo.seed["tv"]["aliases"]
        assert "mini led" in repo.seed["tv"]["aliases"]
        found = next(item for item in products if item.id == "tv")
        assert "pantalla-mongo" in found.aliases
        assert "mini led" in found.aliases
    finally:
        _reset_memory()


def test_redis_rebuilds_from_mongo_seed():
    repo = MemorySeedRepo()
    try:
        load_active_seed(repo=repo, sync_json=True)
        repo.seed["tv"]["aliases"] = ["televisor", "pantalla-mongo"]
        redis = MemoryRedis()
        meta = ensure_loaded(client=redis, force=True, repo=repo)
        assert meta["source"] == "mongo"
        assert redis.get("retail:pindex:alias:pantalla mongo") == "tv"
        assert redis.get("retail:pindex:alias:pantallamongo") == "tv"
        assert resolve("pantalla-mongo 50", client=redis).id == "tv"
    finally:
        _reset_memory()


def test_feed_hit_bumps_seed_and_miss_stays_unmatched(monkeypatch):
    monkeypatch.setattr("retail.index.products.connect_redis", lambda: None)
    repo = MemorySeedRepo()
    load_active_seed(repo=repo, sync_json=True)
    feed_search(
        "tv 50 pulgadas",
        {"id": "tv", "groups": ["tecnologia", "retail"], "applied": True},
        store_count=33,
        applied=True,
        repo=repo,
        background=False,
    )
    assert repo.seed["tv"]["hit_count"] == 1
    assert repo.seed["tv"]["last_seen_at"] == "seen"
    hit = repo.queries[0]
    assert hit["query"] == "tv 50 pulgadas"
    assert hit["folded"] == "tv 50 pulgadas"
    assert hit["product_id"] == "tv"
    assert hit["unmatched"] is False
    assert hit["store_count"] == 33
    assert hit["applied"] is True

    feed_search("colun", None, store_count=150, applied=False, repo=repo, background=False)
    miss = repo.queries[-1]
    assert miss["query"] == "colun"
    assert miss["product_id"] is None
    assert miss["unmatched"] is True
    assert "colun" not in repo.seed
    assert resolve("colun", client=False) is None
    ids = {item.id for item in load_seed()[2]}
    assert "colun" not in ids
    unmatched = repo.unmatched_product_index_queries()
    assert unmatched[0]["query"] == "colun"


def test_search_feeds_product_index(monkeypatch):
    from retail.search import iter_search_events

    _mute_other_stores(monkeypatch)
    fed: list[tuple] = []

    def capture(query, product_index, **kwargs):
        fed.append((query, product_index, kwargs))

    monkeypatch.setattr("retail.search.lookup_search_result", lambda *args, **kwargs: None)
    monkeypatch.setattr("retail.search.lookup_store_products", lambda *args, **kwargs: {})
    monkeypatch.setattr("retail.search.store_search_result", lambda *args, **kwargs: None)
    monkeypatch.setattr("retail.search.store_store_products", lambda *args, **kwargs: None)
    monkeypatch.setattr("retail.search.connect_repo", lambda: None)
    monkeypatch.setattr("retail.search.connect_qdrant", lambda: None)
    monkeypatch.setattr("retail.search.scrape_store", lambda *args, **kwargs: ([], None))
    monkeypatch.setattr("retail.index.products.connect_redis", lambda: None)
    monkeypatch.setattr("retail.search.feed_search", capture)

    events = list(iter_search_events("tv 50 pulgadas", source="scrape", persist=False, delay=0, timeout=1))
    result = events[-1]["result"]
    assert result["product_index"]["id"] == "tv"
    assert len(fed) == 1
    assert fed[0][0] == "tv 50 pulgadas"
    assert fed[0][1]["id"] == "tv"
    assert fed[0][2]["applied"] is True
    assert fed[0][2]["store_count"] == len(result["stores"])


def _stub_search(monkeypatch) -> None:
    monkeypatch.setattr("retail.search.lookup_search_result", lambda *args, **kwargs: None)
    monkeypatch.setattr("retail.search.lookup_store_products", lambda *args, **kwargs: {})
    monkeypatch.setattr("retail.search.store_search_result", lambda *args, **kwargs: None)
    monkeypatch.setattr("retail.search.store_store_products", lambda *args, **kwargs: None)
    monkeypatch.setattr("retail.search.connect_repo", lambda: None)
    monkeypatch.setattr("retail.search.connect_qdrant", lambda: None)
    monkeypatch.setattr("retail.search.scrape_store", lambda *args, **kwargs: ([], None))
    monkeypatch.setattr("retail.index.products.connect_redis", lambda: None)


def test_unique_queries_collapse_to_tv():
    _reset_memory()
    try:
        for query in ("tele", "televisor", "tv", "tv mini", "mini tv", "mini led", "miniled"):
            assert unique_product_id(query, client=False) == "tv"
    finally:
        _reset_memory()


def test_leftover_aliases_attach_to_parlante():
    repo = MemorySeedRepo()
    _reset_memory()
    try:
        load_active_seed(repo=repo, sync_json=True)
        assert leftover_alias_tokens("parlante jbl partibox", client=False) == ["jbl", "partibox"]
        added = feed_query_aliases("parlante jbl partibox", repo=repo, client=False)
        assert added == ["jbl", "partibox"]
        assert "jbl" in repo.seed["parlante"]["aliases"]
        assert "partibox" in repo.seed["parlante"]["aliases"]
        assert resolve("jbl", client=False).id == "parlante"
        assert resolve("partibox", client=False).id == "parlante"
        assert unique_product_id("jbl", client=False) == "parlante"
    finally:
        _reset_memory()


def test_leftover_aliases_drop_stopwords_numbers_and_units():
    _reset_memory()
    try:
        assert leftover_alias_tokens("parlante de jbl para fiesta", client=False) == ["jbl", "fiesta"]
        assert leftover_alias_tokens("tv 50 pulgadas", client=False) == []
        assert leftover_alias_tokens("televisor 55 cm", client=False) == []
        # «mini» ya está cubierto por el alias «mini led» de tv
        assert leftover_alias_tokens("tv mini", client=False) == []
        assert leftover_alias_tokens("tv samsung", client=False) == ["samsung"]
    finally:
        _reset_memory()


def test_leftover_aliases_skip_unmatched_and_other_products():
    _reset_memory()
    try:
        assert leftover_alias_tokens("xyzzy123", client=False) == []
        assert leftover_alias_tokens("colun", client=False) == []
        # xbox ya es alias de consola: no se fusiona con parlante
        assert leftover_alias_tokens("parlante xbox", client=False) == []
    finally:
        _reset_memory()


def test_feed_search_indexes_leftover_aliases(monkeypatch):
    monkeypatch.setattr("retail.index.products.connect_redis", lambda: None)
    repo = MemorySeedRepo()
    try:
        load_active_seed(repo=repo, sync_json=True)
        feed_search(
            "parlante jbl partibox",
            {"id": "parlante", "groups": ["tecnologia", "retail", "musica"], "applied": True},
            store_count=10,
            applied=True,
            repo=repo,
            background=False,
        )
        assert "jbl" in repo.seed["parlante"]["aliases"]
        assert "partibox" in repo.seed["parlante"]["aliases"]
        feed_search("xyzzy", None, store_count=150, applied=False, repo=repo, background=False)
        assert "xyzzy" not in repo.seed
        assert leftover_alias_tokens("xyzzy", client=False) == []
    finally:
        _reset_memory()


def test_feed_discovered_groups_adds_farmacias_to_tv():
    repo = MemorySeedRepo()
    try:
        load_active_seed(repo=repo, sync_json=True)
        assert "farmacias" not in repo.seed["tv"]["groups"]
        extra = feed_discovered_groups("tv", ["ahumada"], query="tv mini", repo=repo, client=False)
        assert extra == ["farmacias"]
        assert "farmacias" in repo.seed["tv"]["groups"]
        assert "ahumada" in repo.seed["tv"]["discovered_stores"]
        assert "farmacias" in repo.seed["tv"]["extra_groups"]
        found = stores_for("tv", _available(), client=False)
        assert found is not None
        assert "ahumada" in found
    finally:
        _reset_memory()


def test_feed_discovered_groups_miss_does_not_remove_groups():
    repo = MemorySeedRepo()
    try:
        load_active_seed(repo=repo, sync_json=True)
        before = list(repo.seed["tv"]["groups"])
        extra = feed_discovered_groups("tv", [], query="tv", repo=repo, client=False)
        assert extra == []
        assert repo.seed["tv"]["groups"] == before
    finally:
        _reset_memory()


def test_redis_patches_new_alias_and_group():
    repo = MemorySeedRepo()
    redis = MemoryRedis()
    try:
        load_active_seed(repo=repo, sync_json=True)
        ensure_loaded(client=redis, force=True, repo=repo)
        feed_query_aliases("parlante jbl partibox", repo=repo, client=redis)
        assert redis.get("retail:pindex:alias:jbl") == "parlante"
        assert redis.get("retail:pindex:alias:partibox") == "parlante"
        extra = feed_discovered_groups("tv", ["ahumada"], query="tv", repo=repo, client=redis)
        assert extra == ["farmacias"]
        import json

        payload = json.loads(redis.get("retail:pindex:product:tv"))
        assert "farmacias" in payload["groups"]
        assert resolve("jbl", client=redis).id == "parlante"
        found = stores_for("tv", _available(), client=redis)
        assert found is not None
        assert "ahumada" in found
    finally:
        _reset_memory()


def test_phase2_not_started_when_stores_manual(monkeypatch):
    from retail.search import iter_search_events

    claimed: list[str] = []
    launched: list = []

    def capture_claim(product_id, **kwargs):
        claimed.append(product_id)
        return True

    _stub_search(monkeypatch)
    monkeypatch.setattr("retail.search.claim_unique_sweep", capture_claim)
    monkeypatch.setattr(
        "retail.search.launch_other_store_sweep",
        lambda job, **kwargs: launched.append(job) if job else None,
    )
    list(iter_search_events("tv", source="scrape", stores=["lider"], persist=False, delay=0, timeout=1))
    assert claimed == []
    assert launched == []


def test_phase2_not_started_when_no_product_match(monkeypatch):
    from retail.search import iter_search_events

    jobs: list = []

    def capture(*args, **kwargs):
        jobs.append(args)
        return False

    _stub_search(monkeypatch)
    monkeypatch.setattr("retail.search.claim_unique_sweep", capture)
    list(iter_search_events("xyzzy123", source="scrape", persist=False, delay=0, timeout=1))
    assert jobs == []


def test_phase2_starts_once_per_unique_product(monkeypatch):
    from retail.search import iter_search_events

    _reset_memory()
    launches: list = []

    def capture(job, *, background=True):
        if job:
            launches.append(job)

    _stub_search(monkeypatch)
    monkeypatch.setattr("retail.search.launch_other_store_sweep", capture)
    list(iter_search_events("tv mini", source="scrape", persist=False, delay=0, timeout=1))
    list(iter_search_events("televisor", source="scrape", persist=False, delay=0, timeout=1))
    assert len(launches) == 1
    assert launches[0]["product_id"] == "tv"
    assert launches[0]["query"] == "tv mini"
    assert "ahumada" in launches[0]["others"]
    assert "falabella" not in launches[0]["others"]
    _reset_memory()


def test_other_stores_sweep_feeds_groups_on_hit(monkeypatch):
    from retail.models import Product
    from retail.search import run_other_stores_sweep

    repo = MemorySeedRepo()
    tv = Product(
        product_id="x",
        sku_id="x",
        name="Smart TV 50 Crystal UHD 4K",
        store="ahumada",
        price=300000,
    )
    monkeypatch.setattr("retail.search.scrape_category_probes", lambda *args, **kwargs: ({"ahumada": [tv]}, [], []))
    monkeypatch.setattr("retail.search.store_store_products", lambda *args, **kwargs: None)
    try:
        load_active_seed(repo=repo, sync_json=True)
        extra = run_other_stores_sweep(
            "tv",
            "tv",
            ["ahumada"],
            persist=False,
            repo=repo,
            delay=0,
            timeout=1,
        )
        assert extra == ["farmacias"]
        assert "farmacias" in repo.seed["tv"]["groups"]
        assert "ahumada" in repo.seed["tv"]["discovered_stores"]
    finally:
        _reset_memory()


def test_other_stores_sweep_miss_keeps_groups(monkeypatch):
    from retail.search import run_other_stores_sweep

    repo = MemorySeedRepo()
    monkeypatch.setattr("retail.search.scrape_category_probes", lambda *args, **kwargs: ({"ahumada": []}, [], []))
    monkeypatch.setattr("retail.search.store_store_products", lambda *args, **kwargs: None)
    try:
        load_active_seed(repo=repo, sync_json=True)
        before = list(repo.seed["tv"]["groups"])
        extra = run_other_stores_sweep(
            "tv",
            "tv",
            ["ahumada"],
            persist=False,
            repo=repo,
            delay=0,
            timeout=1,
        )
        assert extra == []
        assert repo.seed["tv"]["groups"] == before
    finally:
        _reset_memory()
