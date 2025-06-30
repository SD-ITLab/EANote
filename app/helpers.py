"""
helpers.py – EAN-Lookup, Icecat-Importer, Cache-Einträge

• Scannt zuerst die lokale DB
• Fragt dann Open-Icecat-Live (gratis) – optional UPCitemdb-Trial
• Legt neue Kategorien + Hersteller automatisch an
• Liefert (name, product_id)  oder (None, None)
"""

from __future__ import annotations
import os, requests
from typing import Tuple, Optional, Dict, Any

from sqlalchemy import select, insert
from sqlalchemy.orm import Session
from db import engine, category, brand, product

# ---------------------------------------------------------------------------
# Konfig
# ---------------------------------------------------------------------------

ICE_USER = os.getenv("ICE_USER", "openIcecat-live")
ICE_LANG = os.getenv("ICE_LANG", "de")      # de, en, …

# ---------------------------------------------------------------------------
# 1) Helper: Kategorie / Brand anlegen oder ID zurückgeben
# ---------------------------------------------------------------------------

def _ensure_category(cat_name: str | None) -> int:
    name = cat_name.strip() if cat_name else "Sonstiges"
    with Session(engine) as s, s.begin():
        cid = s.scalar(select(category.c.id).where(category.c.name == name))
        if cid:
            return cid
        return s.scalar(
            insert(category).values(name=name).returning(category.c.id)
        )

def _ensure_brand(brand_name: str | None) -> Optional[int]:
    if not brand_name or not brand_name.strip():
        return None
    name = brand_name.strip()
    with Session(engine) as s, s.begin():
        bid = s.scalar(select(brand.c.id).where(brand.c.name == name))
        if bid:
            return bid
        return s.scalar(
            insert(brand).values(name=name).returning(brand.c.id)
        )

# ---------------------------------------------------------------------------
# 2) Icecat-Live-Lookup  (liefert komplettes JSON oder None)
# ---------------------------------------------------------------------------

def _icecat_fetch_json(ean: str, lang: str) -> Optional[Dict[str, Any]]:
    url = ( "https://live.icecat.biz/api"
            f"?UserName={ICE_USER}&Language={lang}&GTIN={ean}&Output=json" )
    r = requests.get(url, timeout=5)
    if r.status_code == 200:
        return r.json()
    return None

# ---------------------------------------------------------------------------
# 3) Name & Meta aus Icecat-JSON extrahieren
# ---------------------------------------------------------------------------

def _extract_name(js: Dict[str, Any]) -> Optional[str]:
    """Versucht diverse Pfade, gibt ersten nicht-leeren String zurück."""
    paths = [
        ("dataSheet", "productName"),
        ("dataSheet", "title"),
        ("summaryDescription", "title"),
        ("product", "title"), ("product", "Title"),
        ("data", "GeneralInfo", "Title"),
        ("data", "GeneralInfo", "TitleInfo", "GeneratedLocalTitle", "Value"),
        ("data", "GeneralInfo", "TitleInfo", "GeneratedIntTitle"),
    ]
    for p in paths:
        node: Any = js
        for key in p:
            node = node.get(key) if isinstance(node, dict) else None
            if node is None:
                break
        if isinstance(node, str) and node.strip():
            return node.strip()
    return None

def _extract_meta(js: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """Liefert (Kategorie‐Name, Brand‐Name) oder (None, None)."""
    cat = (
        js.get("data", {})
          .get("GeneralInfo", {})
          .get("Category", {})
	  .get("Name", {})
	  .get("Value")
        or js.get("data", {})
            .get("GeneralInfo", {})
            .get("CategoryName")
        or js.get("dataSheet", {})
             .get("category", {})
             .get("Name")
    )
    brand = (
        js.get("data", {})
          .get("GeneralInfo", {})
          .get("Brand")
        or js.get("GeneralInfo", {})
            .get("Brand")
    )
    return cat, brand

# ---------------------------------------------------------------------------
# 4) Optionaler UPCitemdb-Trial-Lookup (kleines Kontingent)
# ---------------------------------------------------------------------------

def _upc_lookup_name(ean: str) -> Optional[str]:
    url = f"https://api.upcitemdb.com/prod/trial/lookup?upc={ean}"
    try:
        r = requests.get(url, timeout=4)
        if r.status_code == 200:
            items = r.json().get("items", [])
            return items[0]["title"] if items else None
    except Exception:
        pass
    return None

# ---------------------------------------------------------------------------
# 5) Hauptfunktion: local → Icecat → UPC
# ---------------------------------------------------------------------------

def get_or_fetch_product(ean: str) -> Tuple[Optional[str], Optional[int]]:
    """
    • Prüft erst lokale DB
    • Versucht dann Icecat (gewählte Sprache, dann en)
    • Optional UPCitemdb-Trial
    Rückgabe: (Produktname, product.id)  oder (None, None)
    """

    # ---- 1) lokaler Treffer
    with Session(engine) as s:
        row = s.execute(
            select(product.c.id, product.c.name).where(product.c.ean == ean)
        ).first()
        if row:
            return row.name, row.id

    # ---- 2) Icecat (Language + en Fallback)
    for lang in (ICE_LANG, "en" if ICE_LANG.lower() != "en" else None):
        if not lang:
            continue
        js = _icecat_fetch_json(ean, lang)
        if not js:
            continue
        name = _extract_name(js)
        if name:
            cat, brand = _extract_meta(js)
            cat_id   = _ensure_category(cat)
            brand_id = _ensure_brand(brand)

            with Session(engine) as s, s.begin():
                s.execute(
                    insert(product)
                    .values(ean=ean, name=name,
                            category_id=cat_id, brand_id=brand_id)
                    .prefix_with("IGNORE")          # vermeidet Duplikat-Error
                )
                pid = s.scalar(
                    select(product.c.id).where(product.c.ean == ean)
                )
            return name, pid

    # ---- 3) UPC-Trial (Name ohne Meta, seltener nötig)
    upc_name = _upc_lookup_name(ean)
    if upc_name:
        cat_id = _ensure_category("Sonstiges")
        with Session(engine) as s, s.begin():
            s.execute(
                insert(product)
                .values(ean=ean, name=upc_name, category_id=cat_id)
                .prefix_with("IGNORE")
            )
            pid = s.scalar(select(product.c.id).where(product.c.ean == ean))
        return upc_name, pid

    # nichts gefunden
    return None, None
