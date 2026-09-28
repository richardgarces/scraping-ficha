from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_pumasafety_target = parse_vtex_target

PumasafetyStore = make_vtex_store(
    store_id="pumasafety",
    title="Puma Safety",
    site="www.pumasafety.cl",
    base="https://www.pumasafety.cl",
    category_help="Slug VTEX, por ejemplo botines",
    group="ferreteria",
)
