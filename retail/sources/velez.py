from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_velez_target = parse_vtex_target

VelezStore = make_vtex_store(
    store_id="velez",
    title="Vélez",
    site="www.velez.cl",
    base="https://www.velez.cl",
    category_help="Slug VTEX, por ejemplo billeteras",
    intelligent_search=True,
    group="moda",
)
