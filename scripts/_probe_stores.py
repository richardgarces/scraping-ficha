"""Detecta VTEX / Shopify / Magento en sitios de retail chileno."""
from __future__ import annotations

import json
import sys

from retail.http import HttpSession

CANDIDATES = [
    ("ABCDin", "https://www.abcdin.cl"),
    ("La Polar", "https://www.lapolar.cl"),
    ("Hites", "https://www.hites.com"),
    ("Corona", "https://www.corona.cl"),
    ("Tricot", "https://www.tricot.cl"),
    ("Jumbo", "https://www.jumbo.cl"),
    ("Santa Isabel", "https://www.santaisabel.cl"),
    ("Unimarc", "https://www.unimarc.cl"),
    ("Acuenta", "https://www.acuenta.cl"),
    ("Construmart", "https://www.construmart.cl"),
    ("Imperial", "https://www.imperial.cl"),
    ("Homy", "https://www.homy.cl"),
    ("Casa Royal", "https://www.casaroyal.cl"),
    ("SP Digital", "https://www.spdigital.cl"),
    ("Winpy", "https://www.winpy.cl"),
    ("Globalbox", "https://www.globalbox.cl"),
    ("MyBox", "https://www.mybox.cl"),
    ("Cruz Verde", "https://www.cruzverde.cl"),
    ("Salcobrand", "https://www.salcobrand.cl"),
    ("Ahumada", "https://www.farmaciasahumada.cl"),
    ("Farmex", "https://www.farmex.cl"),
    ("Decathlon", "https://www.decathlon.cl"),
    ("Adidas", "https://www.adidas.cl"),
    ("The North Face", "https://www.thenorthface.cl"),
    ("Audiomusica", "https://www.audiomusica.com"),
    ("ProMusic", "https://www.promusic.cl"),
    ("Bizzarro", "https://www.bizzarro.cl"),
    ("Music Store", "https://www.musicstore.cl"),
    ("Yamaha", "https://www.yamaha.cl"),
    ("Casa de la Música", "https://www.casadelamusica.cl"),
    ("Maicao", "https://www.maicao.cl"),
    ("DB", "https://www.db.cl"),
    ("Buscalibre", "https://www.buscalibre.cl"),
    ("Baby Infanti", "https://www.babyinfanti.cl"),
    ("Dafiti", "https://www.dafiti.cl"),
    ("Entel Shop", "https://www.entel.cl"),
    ("WOM", "https://tienda.wom.cl"),
    ("Claro", "https://www.clarochile.cl"),
    ("Samsung", "https://www.samsung.com/cl"),
    ("HP Store", "https://www.hp.com/cl-es/shop"),
    ("Linio", "https://www.linio.cl"),
    ("Paris Homecenter?", "https://www.cdiscount.cl"),
    ("Mica", "https://www.mica.cl"),
    ("Crate & Barrel", "https://www.crateandbarrel.cl"),
    ("Crate", "https://www.cb2.cl"),
    ("La Polar Hogar", "https://www.lapolar.cl"),
    ("Style Store", "https://www.stylesstore.cl"),
    ("Marathon", "https://www.marathonsports.cl"),
    ("Umbru", "https://www.umbru.cl"),
    ("Lippi already", "https://www.lippioutdoor.com"),
]


def sniff(html: str) -> list[str]:
    low = html.lower()
    hits = []
    if "vtex" in low or "vtexassets" in low or "io.vtex.com" in low:
        hits.append("html:vtex")
    if "cdn.shopify.com" in low or "myshopify.com" in low or "shopify" in low:
        hits.append("html:shopify")
    if "mage/" in low or "magento" in low or "mage-cache" in low:
        hits.append("html:magento")
    if "salesforce" in low or "demandware" in low or "sfcc" in low:
        hits.append("html:salesforce")
    return hits


def try_get(http: HttpSession, url: str) -> tuple[int, str, str]:
    try:
        return http.get(url)
    except Exception as exc:
        return 0, "", str(exc)[:80]


def vtex_ok(status: int, ctype: str, body: str) -> bool:
    if status != 200 or "json" not in ctype:
        return False
    try:
        data = json.loads(body)
    except Exception:
        return False
    return isinstance(data, list)


def shopify_ok(status: int, ctype: str, body: str) -> bool:
    if status != 200:
        return False
    try:
        data = json.loads(body)
    except Exception:
        return False
    return isinstance(data, dict) and "products" in data


def main() -> int:
    http = HttpSession(timeout=12)
    try:
        for name, base in CANDIDATES:
            flags: list[str] = []
            status, ctype, body = try_get(http, base)
            flags.extend(sniff(body))
            vs, vt, vb = try_get(http, f"{base}/api/catalog_system/pub/products/search?ft=guitarra&_from=0&_to=1")
            if vtex_ok(vs, vt, vb):
                flags.append(f"vtex-api:{vs}")
            elif vs:
                flags.append(f"vtex:{vs}")
            ss, st, sb = try_get(http, f"{base}/products.json?limit=1")
            if shopify_ok(ss, st, sb):
                n = len(json.loads(sb).get("products") or [])
                flags.append(f"shopify-api:{n}")
            elif ss:
                flags.append(f"shopify:{ss}")
            ms, mt, mb = try_get(http, f"{base}/catalogsearch/result/?q=piano")
            if ms == 200 and ("product-item" in mb or "mage" in mb.lower()):
                flags.append("magento-search")
            elif ms:
                flags.append(f"mage:{ms}")
            print(f"{name:22} {base:40} {status:3}  {', '.join(flags) or 'sin señal'}")
            sys.stdout.flush()
    finally:
        http.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
