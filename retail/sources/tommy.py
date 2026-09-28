from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_tommy_target = parse_vtex_target

TommyStore = make_vtex_store(
    store_id="tommy",
    title="Tommy Hilfiger",
    site="cl.tommy.com",
    base="https://cl.tommy.com",
    category_help="Slug VTEX, por ejemplo categoria/subcategoria",
)
