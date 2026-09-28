from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_newman_target = parse_vtex_target

NewmanStore = make_vtex_store(
    store_id="newman",
    title="Newman",
    site="www.newman.cl",
    base="https://www.newman.cl",
    category_help="Slug VTEX, por ejemplo camisas",
    intelligent_search=True,
    group="moda",
)
