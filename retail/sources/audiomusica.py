from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_audiomusica_target = parse_vtex_target

AudiomusicaStore = make_vtex_store(
    store_id="audiomusica",
    title="AudioMúsica",
    site="www.audiomusica.com",
    base="https://www.audiomusica.com",
    category_help="Slug VTEX, por ejemplo instrumentos-cuerda/guitarras",
)
