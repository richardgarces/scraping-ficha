from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_casaroyal_target = parse_vtex_target

CasaroyalStore = make_vtex_store(
    store_id="casaroyal",
    title="Casa Royal",
    site="www.casaroyal.cl",
    base="https://www.casaroyal.cl",
    category_help="Slug VTEX, por ejemplo instrumentos-musicales/guitarras-y-bajos",
    intelligent_search=True,
)
