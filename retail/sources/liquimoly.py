from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_liquimoly_target = parse_vtex_target

LiquimolyStore = make_vtex_store(
    store_id="liquimoly",
    title="Liqui Moly",
    site="www.liqui-moly.cl",
    base="https://www.liqui-moly.cl",
    category_help="Slug VTEX, por ejemplo categoria/subcategoria",
)
