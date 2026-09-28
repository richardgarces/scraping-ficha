from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_dimarsa_target = parse_vtex_target

DimarsaStore = make_vtex_store(
    store_id="dimarsa",
    title="Dimarsa",
    site="www.dimarsa.cl",
    base="https://www.dimarsa.cl",
    category_help="Slug VTEX, por ejemplo linea-blanca/microondas",
    group="retail",
)
