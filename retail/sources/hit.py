from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_hit_target = parse_vtex_target

HitStore = make_vtex_store(
    store_id="hit",
    title="HIT",
    site="www.hit.cl",
    base="https://www.hit.cl",
    category_help="Slug VTEX, por ejemplo poleras",
    intelligent_search=True,
    group="moda",
)
