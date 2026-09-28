from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_perryellis_target = parse_vtex_target

PerryellisStore = make_vtex_store(
    store_id="perryellis",
    title="Perry Ellis",
    site="www.perryellis.cl",
    base="https://www.perryellis.cl",
    category_help="Slug VTEX, por ejemplo categoria/subcategoria",
)
