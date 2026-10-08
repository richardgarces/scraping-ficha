#!/usr/bin/env python3
"""Probe marcas Cyber marcadas «no» en docs/tiendas.md y scaffoldea Shopify/VTEX viables."""
from __future__ import annotations

import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from retail.registry import STORE_GROUP, list_stores  # noqa: E402
from retail.scaffold import scaffold_store  # noqa: E402

DOC = ROOT / "docs" / "tiendas.md"

CAT_TO_GROUP = {
    "Accesorios Moda": "moda",
    "Alimentos y Bebidas": "gastronomia",
    "Automotriz": "autos",
    "Deportes y Outdoor": "deporte",
    "Entretención": "juguetes",
    "Ferretería y Construcción": "ferreteria",
    "Hogar": "hogar",
    "Infantil": "infantil",
    "Mascotas": "otros",
    "Muebles": "hogar",
    "Multitiendas y Supermercados": "retail",
    "Música y Audio": "musica",
    "Neumáticos y Accesorios": "otros",
    "Ropa Interior y Pijamas": "moda",
    "Salud y Belleza": "belleza",
    "Tecnología": "tecnologia",
    "Vestuario Industrial": "calzado",
    "Vestuario y Calzado": "moda",
}

# Marcas que no son catálogo scrapeable de productos retail.
NOT_POSSIBLE = {
    "Chery", "Dercocenter", "Exeed", "Hyundai", "JAC", "Subaru",  # dealers / sin catálogo útil
    "Punto Ticket", "Ticketmaster", "SOYPREMIUM",  # tickets / membresías
    "Papa Johns",  # food delivery
    "ENEL STORE", "Tu Tienda Metrogas",  # utilities
    "DRA. SIERRALTA", "Lasertam", "UltraEstetica", "Simmedical",  # clínicas / servicios
}

# Dominios conocidos / preferidos (override del guess).
URL_OVERRIDES: dict[str, str] = {
    "Adidas": "www.adidas.cl",
    "Bata": "www.bata.cl",
    "H&M": "www2.hm.com",
    "Skechers": "www.skechers.cl",
    "Columbia": "www.columbia.cl",
    "Jumbo": "www.jumbo.cl",
    "Santa Isabel": "www.santaisabel.cl",
    "Petco": "www.petco.cl",
    "SuperZoo": "www.superzoo.cl",
    "Hoka": "www.hoka.com",
    "Lacoste": "www.lacoste.cl",
    "O’neill": "www.oneill.cl",
    "O'neill": "www.oneill.cl",
    "JBL": "www.jbl.cl",
    "Sony": "store.sony.cl",
    "Lenovo": "www.lenovo.com",
    "Mac Online": "www.maconline.com",
    "Kärcher": "www.kaercher.com",
    "Cic": "www.cic.cl",
    "Emma Sleep": "www.emma-colchon.cl",
    "Hasbro": "www.hasbro.com",
    "Lego": "www.lego.com",
    "Pandora": "cl.pandora.net",
    "Bath & Body Works": "www.bathandbodyworks.cl",
    "Victoria’s Secret": "www.victoriassecret.cl",
    "Victoria's Secret": "www.victoriassecret.cl",
    "Autoplanet": "www.autoplanet.cl",
    "miCoca-Cola.cl": "www.micoca-cola.cl",
    "Nutriscomarket.cl": "www.nutriscomarket.cl",
    "FERRETERIA.CL": "www.ferreteria.cl",
    "TodoToner.cl": "www.todotoner.cl",
    "Balustore.cl": "www.balustore.cl",
    "Pz.cl": "www.pz.cl",
    "iRobot": "www.irobot.cl",
    "Reuse": "www.reuse.cl",
    "Dimacofi": "www.dimacofi.cl",
    "EPSON": "epson.cl",
    "Back Online": "www.backonline.cl",
    "Giant Bicycles": "www.giant-bicycles.com",
    "Weinbrenner": "www.weinbrenner.cl",
    "Laika Mascotas": "www.laika.com.co",
    "Club de perros y gatos": "www.clubdeperrosygatos.cl",
    "Farmacias Knop": "www.farmaciasknop.cl",
    "L’bel": "www.lbel.cl",
    "ÉSIKA": "www.esika.cl",
    "UGG": "www.ugg.com",
    "Marathon": "www.marathonsports.cl",
    "Rockford": "www.rockford.cl",
    "Rusty": "www.rusty.cl",
    "Penguin": "www.originalpenguin.cl",
    "North Star": "www.northstar.cl",
    "Bubblegummers": "www.bubblegummers.cl",
    "Carestino": "www.carestino.cl",
    "Bestway": "www.bestway.cl",
    "Blanik": "www.blanik.cl",
    "Imperial": "www.imperial.cl",
    "Marienberg": "www.marienberg.cl",
    "AmortiguadoresK": "www.amortiguadoresk.cl",
    "Chile Neumaticos": "www.chileneumaticos.cl",
    "Mall del Neumatico": "www.malldelneumatico.cl",
    "Supermercado del Neumatico": "www.supermercadodelneumatico.cl",
    "Music World": "www.musicworld.cl",
    "Casa Amarilla": "www.casaamarilla.cl",
    "La Barra CCU": "www.labarra.cl",
    "Volka Chokolade": "www.volkachokolade.cl",
    "Tremus": "www.tremus.cl",
    "Booz": "www.booz.cl",
    "Aurus Joyeria": "www.aurus.cl",
    "Humana": "www.humana.cl",
    "Nerfis": "www.nerfis.cl",
    "Orocash": "www.orocash.cl",
    "Andesland": "www.andesland.cl",
    "Atletis": "www.atletis.cl",
    "Trail Store": "www.trailstore.cl",
    "La Pica del Ski": "www.lapicadelski.cl",
    "Getway": "www.getway.cl",
    "Kano": "www.kano.cl",
    "Bamers": "www.bamers.cl",
    "Belsport": "www.belsport.cl",
    "Bruno Rossi": "www.brunorossi.cl",
    "Family Shop": "www.familyshop.cl",
    "Kliper": "www.kliper.cl",
    "Ludovica": "www.ludovica.cl",
    "Mingo": "www.mingo.cl",
    "Panama Jack": "www.panamajack.cl",
    "Quebec": "www.quebec.cl",
    "Renatta & Go": "www.renattaandgo.cl",
    "Surprice": "www.surprice.cl",
    "Umbrale": "www.umbrale.cl",
    "Zappa": "www.zappa.cl",
    "16 hrs": "www.16hrs.cl",
    "Antihuman": "www.antihuman.cl",
    "Bold": "www.bold.cl",
    "Calper": "www.calper.cl",
    "Doxie Chile": "www.doxie.cl",
    "Globe": "www.globe.cl",
    "PIERO BUTTI": "www.pierobutti.cl",
    "Pollini": "www.pollini.cl",
    "Tworld Store": "www.tworld.cl",
    "Amazing": "www.amazing.cl",
    "Globaltecno": "www.globaltecno.cl",
    "SC Global": "www.scglobal.cl",
    "Tecno Lace": "www.tecnolace.cl",
    "Tu Gadget": "www.tugadget.cl",
    "Cherimoya": "www.cherimoya.cl",
    "Coreana": "www.coreana.cl",
    "Kliki": "www.kliki.cl",
    "LATTAFA PERFUMES": "www.lattafa.cl",
    "Long Love": "www.longlove.cl",
    "Sairam Perfumes": "www.sairam.cl",
    "Secretos de amor": "www.secretosdeamor.cl",
    "Skar Cosmetics": "www.skar.cl",
    "V&P Perfumeria": "www.vyperfumeria.cl",
    "Mi tienda Cotidian": "www.cotidian.cl",
    "JPT": "www.jpt.cl",
    "JPT Luxury": "www.jptluxury.cl",
    "DR. PET": "www.drpet.cl",
    "Felinus": "www.felinus.cl",
    "Pawal": "www.pawal.cl",
    "LIVING STORE": "www.livingstore.cl",
    "Muebles Santa Ana": "www.mueblessantaana.cl",
    "Novahus": "www.novahus.cl",
    "Vekka Home": "www.vekkahome.cl",
    "De todo y mas": "www.detodoyymas.cl",
    "SuperStore": "www.superstore.cl",
    "Blupoint Music": "www.blupoint.cl",
    "Cortinas Izurieta": "www.cortinasizurieta.cl",
    "Covepa": "www.covepa.cl",
    "DONDE NACEN LAS VELAS": "www.dondenacenlasvelas.cl",
    "El Castillo": "www.elcastillo.cl",
    "Igpro": "www.igpro.cl",
    "Kendal": "www.kendal.cl",
    "LANCO PAINTS": "www.lanco.cl",
    "Mabe": "www.mabe.cl",
    "Mi foto": "www.mifoto.cl",
    "Steward": "www.steward.cl",
    "CHC": "www.chc.cl",
    "EITA Comercializadora": "www.eita.cl",
    "Crescente": "www.crescente.cl",
    "Mi primera Foto": "www.miprimerafoto.cl",
    "Pichintun": "www.pichintun.cl",
    "SlimeHuum": "www.slimehuum.cl",
    "Baepink": "www.baepink.cl",
    "Fumetas Store": "www.fumetas.cl",
    "Ozeta": "www.ozeta.cl",
    "Zigzaboo": "www.zigzaboo.cl",
    "Junheinrich": "www.jungheinrich.cl",
    "Maktotal": "www.maktotal.cl",
    "Maquep Chile": "www.maquep.cl",
    "MiService": "www.miservice.cl",
    "Oviedo Ferreteria": "www.oviedo.cl",
    "RCR Ferreteria": "www.rcr.cl",
    "Authievre Motors": "www.authievre.cl",
    "Bemarket": "www.bemarket.cl",
    "Caren": "www.caren.cl",
    "Descuento Neumatico": "www.descuentoneumatico.cl",
    "Maxxis Chile": "www.maxxis.cl",
    "Mitas": "www.mitas.cl",
    "Mundo Repuestos": "www.mundorepuestos.cl",
    "Neumaspot": "www.neumaspot.cl",
    "NEUMATICOSK": "www.neumaticosk.cl",
    "Red Barrera": "www.redbarrera.cl",
    "AWL": "www.awl.cl",
    "Bamo": "www.bamo.cl",
    "Discovery": "www.discovery.cl",
    "Volcano Trailer": "www.volcanotrailer.cl",
    "Vulcano": "www.vulcano.cl",
    "Djoyas": "www.djoyas.cl",
}


def slug_id(name: str) -> str:
    text = name.casefold()
    text = text.replace("&", " and ")
    text = text.replace("ä", "a").replace("ö", "o").replace("ü", "u")
    text = text.replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")
    text = text.replace("ñ", "n").replace("’", "").replace("'", "")
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    text = re.sub(r"_+", "_", text)
    if text and text[0].isdigit():
        text = "t_" + text
    return text[:32]


def guess_host(name: str) -> str:
    if name in URL_OVERRIDES:
        return URL_OVERRIDES[name]
    if ".cl" in name.casefold() or ".com" in name.casefold():
        host = re.sub(r"^www\.", "", name.casefold().strip())
        return host if host.startswith("www.") else f"www.{host}"
    base = slug_id(name).replace("_", "")
    return f"www.{base}.cl"


def parse_no_rows() -> list[tuple[str, str]]:
    rows = []
    for line in DOC.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|") or "Tienda | Categoría" in line or line.startswith("| ---"):
            continue
        parts = [p.strip() for p in line.strip("|").split("|")]
        if len(parts) < 5:
            continue
        name, cat, status = parts[0], parts[1], parts[2]
        if status == "no":
            rows.append((name, cat))
    return rows


def fetch(url: str, timeout: float = 12.0) -> tuple[int, str, str]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; RetailChileProbe/1.0)",
            "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(250_000).decode("utf-8", errors="ignore")
            return resp.status, str(resp.geturl()), body
    except urllib.error.HTTPError as exc:
        body = exc.read(80_000).decode("utf-8", errors="ignore") if exc.fp else ""
        return exc.code, url, body
    except Exception:
        return 0, url, ""


def detect_platform(host: str) -> tuple[str | None, str]:
    """Devuelve (platform, base_url) o (None, reason)."""
    base = f"https://{host}"
    # Shopify
    status, final, body = fetch(f"{base}/products.json?limit=1")
    if status == 200 and '"products"' in body:
        return "shopify", final.split("/products.json")[0].rstrip("/") or base
    # VTEX catalog
    status, final, body = fetch(f"{base}/api/catalog_system/pub/products/search?_from=0&_to=0")
    if status in {200, 206} and (body.strip().startswith("[") or "productId" in body or body.strip() == "[]"):
        return "vtex", urllib.request.urlparse(final)._replace(path="", params="", query="", fragment="").geturl().rstrip("/") or base
    # VTEX intelligent search marker in HTML
    status, final, body = fetch(base + "/")
    if status and status < 400:
        low = body.casefold()
        if "cdn.shopify.com" in low or "myshopify.com" in low:
            return "shopify", base
        if "vtexassets.com" in low or "vtexcommercestable" in low or "/api/io/" in low:
            return "vtex", base
        if "mage/cookies" in low or "Magento_" in body:
            return "magento", base
    return None, f"unreachable_or_custom status={status}"


def ensure_store_group(store_id: str, group: str) -> None:
    path = ROOT / "retail" / "registry.py"
    text = path.read_text(encoding="utf-8")
    if f'"{store_id}":' in text:
        return
    # Insert before closing brace of STORE_GROUP (last entry before }\n\n\n@dataclass)
    needle = '\n    "decathlon": "deporte",\n}'
    if needle not in text:
        # fallback: before end of STORE_GROUP
        match = re.search(r'(STORE_GROUP: dict\[str, str\] = \{.*?)(\n\})', text, re.S)
        if not match:
            raise SystemExit("No pude ubicar STORE_GROUP para insertar")
        insert_at = match.end(1)
        text = text[:insert_at] + f'\n    "{store_id}": "{group}",' + text[insert_at:]
    else:
        text = text.replace(needle, f'\n    "decathlon": "deporte",\n    "{store_id}": "{group}",\n}}')
    path.write_text(text, encoding="utf-8")


def main() -> int:
    existing = {spec.id for spec in list_stores()}
    rows = parse_no_rows()
    results: list[dict] = []
    created = 0
    for name, cat in rows:
        group = CAT_TO_GROUP.get(cat, "otros")
        if cat == "Multitiendas y Supermercados" and name in {"Jumbo", "Santa Isabel"}:
            group = "supermercados"
        if name in NOT_POSSIBLE:
            results.append({"name": name, "cat": cat, "status": "no es posible", "reason": "servicio_o_sin_catalogo"})
            continue
        store_id = slug_id(name)
        if store_id in existing or (ROOT / "retail" / "sources" / f"{store_id}.py").exists():
            results.append({"name": name, "cat": cat, "status": "si", "store_id": store_id, "reason": "ya_existia"})
            continue
        host = guess_host(name)
        platform, info = detect_platform(host)
        time.sleep(0.35)
        if not platform:
            results.append({"name": name, "cat": cat, "status": "no", "reason": info, "host": host})
            continue
        try:
            path = scaffold_store(
                store_id,
                name,
                host,
                platform=platform,
                brand=name if platform == "vtex" else None,
            )
            # Añadir group= en VTEX scaffolded file
            src = path.read_text(encoding="utf-8")
            if platform == "vtex" and "group=" not in src:
                src = src.replace(
                    'category_help="Slug VTEX, por ejemplo ropa/polerones",\n)',
                    f'category_help="Slug VTEX, por ejemplo ropa/polerones",\n    group="{group}",\n)',
                )
                path.write_text(src, encoding="utf-8")
            ensure_store_group(store_id, group)
            existing.add(store_id)
            created += 1
            results.append({
                "name": name,
                "cat": cat,
                "status": "si",
                "store_id": store_id,
                "platform": platform,
                "host": host,
                "group": group,
            })
            print(f"[+] {name} -> {store_id} ({platform}) group={group}")
        except Exception as exc:
            results.append({"name": name, "cat": cat, "status": "no", "reason": str(exc), "host": host})
            print(f"[!] {name}: {exc}")

    out = ROOT / "docs" / "tiendas_probe_results.json"
    import json
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Created {created} stores. Results: {out}")
    print("si", sum(1 for r in results if r["status"] == "si"))
    print("no", sum(1 for r in results if r["status"] == "no"))
    print("no es posible", sum(1 for r in results if r["status"] == "no es posible"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
