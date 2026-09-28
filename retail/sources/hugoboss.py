from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_hugoboss_target = parse_vtex_target

HugobossStore = make_vtex_store(
    store_id="hugoboss",
    title="Hugo Boss",
    site="www.hugoboss.cl",
    base="https://www.hugoboss.cl",
    category_help="Slug VTEX, por ejemplo categoria/subcategoria",
)
