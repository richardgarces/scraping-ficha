from retail.platforms.magento import make_magento_store, parse_magento_target

parse_guess_target = parse_magento_target

GuessStore = make_magento_store(
    store_id="guess",
    title="Guess",
    site="www.guess.cl",
    base="https://www.guess.cl",
    category_help="Slug Magento, por ejemplo categoria.html",
)
