from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_totto_target = parse_vtex_target

TottoStore = make_vtex_store(
    store_id="totto",
    title="Totto",
    site="cl.totto.com",
    base="https://cl.totto.com",
    category_help="Slug VTEX, por ejemplo mochilas",
    intelligent_search=True,
    group="moda",
)
