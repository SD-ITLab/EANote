# ─── Standard-Imports ────────────────────────────────────────────────
import os, re, io, sys, traceback, io
from pathlib import Path
from datetime import date, datetime
from functools import wraps
from PIL import Image
from pylibdmtx.pylibdmtx import encode as dmtx_encode

from flask import (Flask, render_template, request, send_file, session,
                   flash, redirect, url_for, abort, jsonify)
from sqlalchemy import select, insert, func, or_
from sqlalchemy.orm import Session
from fpdf import FPDF
from werkzeug.security import generate_password_hash, check_password_hash

# ─── DB / Hilfen ------------------------------------------------------
from db       import engine, init_db, category, product, brand, slip, slip_item, serial
from helpers  import get_or_fetch_product, _ensure_brand

TRANSLATE = str.maketrans(
    "ÄÖÜäöüß", "AOUaouB")     # Minimal-Ersatz, gern anpassen

def slug(txt: str) -> str:
    txt = (txt or "-").translate(TRANSLATE)
    txt = re.sub(r"[^A-Za-z0-9_-]+", "_", txt.strip())
    return txt or "-"

# ─── Flask-App anlegen (MUSS vor Dekoratoren stehen!) ────────────────
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "super-secret-change-me")
init_db()

# ─── Login-Konstanten + Decorator ────────────────────────────────────
ADMIN_USER    = "admin"
ADMIN_PW_HASH = generate_password_hash(
    os.environ.get("EAN_ADMIN_PW", "changeme123!")
)

TECH_USER     = "techniker"
TECH_PW_HASH  = generate_password_hash(
    os.environ.get("TECH_PW", "technikpass")
)

def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if session.get("role") != "admin":
            flash("Bitte als Admin einloggen …", "warn")
            return redirect(url_for("login", next=request.full_path))
        return fn(*a, **kw)
    return wrapper

def tech_or_admin_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if session.get("role") not in ("admin", "tech"):
            flash("Bitte einloggen …", "warn")
            return redirect(url_for("login", next=request.full_path))
        return fn(*a, **kw)
    return wrapper

# ─── Einziger Login-Endpunkt für beide Rollen ───────────────────────
@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        user = request.form["user"]
        pw   = request.form["pw"]
        # Admin?
        if user == ADMIN_USER and check_password_hash(ADMIN_PW_HASH, pw):
            session["role"] = "admin"
            flash("Admin angemeldet!", "ok")
            return redirect(request.args.get("next") or url_for("admin_home"))
        # Techniker?
        if user == TECH_USER and check_password_hash(TECH_PW_HASH, pw):
            session["role"] = "tech"
            flash("Techniker angemeldet!", "ok")
            return redirect(request.args.get("next") or url_for("new_slip"))
        error = "Falsche Zugangsdaten!"
    return render_template("login.html", error=error, title="Login")

@app.get("/logout")
def logout():
    session.clear()
    flash("Abgemeldet.", "ok")
    return redirect(url_for("login"))

# ─── Globaler Hook für alle Routen ───────────────────────────────────
@app.before_request
def require_login_for_everything():
    exempt = ("static", "login", "logout", "admin_home",)
    if request.endpoint in exempt:
        return
    # Admin- und Techniker-Routen
    if session.get("role") not in ("admin", "tech"):
        return redirect(url_for("login", next=request.full_path))

# ─── Admin-Bereich (geschützt) ───────────────────────────────────────
@app.get("/admin")
@login_required
def admin_home():
    # ----- Filter aus Query-String lesen -----------------------------
    q        = request.args.get("q", "").strip()          # Freitext (EAN / Produkt)
    cat_id   = request.args.get("cat") or None            # Kategorie-ID
    brand_q  = request.args.get("brand", "").strip()      # Hersteller-Teilstring

    # ----- Grund-Select (holt gleich Kategorie & Brand) --------------
    stmt = (
        select(product.c.id,
               product.c.ean,
               product.c.name,
               category.c.name.label("cat"),
               brand.c.name.label("brand"))
        .select_from(product)
        .join(category, category.c.id == product.c.category_id)
        .outerjoin(brand,   brand.c.id == product.c.brand_id)
        .order_by(product.c.name)
    )

    # ----- Wenn überhaupt gefiltert wird … ---------------------------
    has_filter = q or cat_id or brand_q
    if has_filter:
        if q:
            like = f"%{q}%"
            stmt = stmt.where(or_(product.c.name.ilike(like),
                                  product.c.ean.like(like)))
        if cat_id:
            stmt = stmt.where(product.c.category_id == int(cat_id))
        if brand_q:
            stmt = stmt.where(brand.c.name.ilike(f"%{brand_q}%"))

        with Session(engine) as s:
            rows = s.execute(stmt).all()
    else:
        rows = []       # → Erst nach einer Suche etwas anzeigen

    # ----- Kategorien für Drop-down ----------------------------------
    with Session(engine) as s:
        cats = s.execute(select(category)).all()

    return render_template(
        "admin_list.html",
        title   = "Produkt­verwaltung",
        rows    = rows,
        q       = q,
        cats    = cats,
        cat_id  = cat_id,
        brand_q = brand_q,
    )


# ── Produkt-Form anzeigen / bearbeiten ───────────────────────────────
@app.get("/admin/product/<int:pid>")
@login_required
def admin_product(pid):
    with Session(engine) as s:
        row = s.execute(
                select(
                    product.c.id,
                    product.c.ean,
                    product.c.name,
                    product.c.category_id,
                    brand.c.name.label("brand")        # Hersteller
                )
                .select_from(product)
                .outerjoin(brand, brand.c.id == product.c.brand_id)
                .where(product.c.id == pid)
            ).first()

    if not row:
        abort(404)

    prod = dict(row._mapping)          #  ← ***JSON-fähig!***

    with Session(engine) as s:
        cats = s.execute(select(category)).all()

    return render_template(
        "admin_form.html",
        prod=prod,                      #  ← wirklich ein dict
        cats=cats,
        title="Produkt bearbeiten"
    )


# ── Neues Produkt ─────────────────────────────────────────────────────
@app.get("/admin/product/new")
@login_required
def admin_product_new():
    with Session(engine) as s:
        cats = s.execute(select(category)).all()
    return render_template("admin_form.html", prod=None, cats=cats, title="Produkt anlegen")


# ── Speichern (AJAX JSON) ─────────────────────────────────────────────
@app.post("/api/admin/save-product")
@login_required
def api_save_product():
    data = request.get_json()

    # --- Brand auflösen -------------------------------------------------
    brand_name = (data.pop("brand", "") or "").strip()
    brand_id   = _ensure_brand(brand_name) if brand_name else None
    if brand_id:
        data["brand_id"] = brand_id       # in die Daten für INSERT/UPDATE einfügen

    ok, msg = True, "Gespeichert"
    try:
        with Session(engine) as s, s.begin():
            if data.get("id"):
                s.execute(product.update()
                          .where(product.c.id == data["id"])
                          .values(**data))
            else:
                s.execute(insert(product).values(**data))
    except Exception as e:
        ok, msg = False, str(e)

    return jsonify(ok=ok, msg=msg)

# ---------------------------------------------------------
def _next_slip_number(session) -> str:
    """liefert YYYY-MM-DD-NNN (NNN = 001, 002 … pro Tag)"""
    today = date.today().strftime("%Y-%m-%d")          # z. B. 2025-06-28
    pattern = f"{today}-%"                             # LIKE-Pattern

    max_num = session.scalar(
        select(func.max(slip.c.number))
        .where(slip.c.number.like(pattern))
    )
    if max_num:
        # letzte Sequenz extrahieren, +1
        last_idx = int(max_num.rsplit("-", 1)[1])
        next_idx = f"{last_idx+1:03d}"
    else:
        next_idx = "001"

    return f"{today}-{next_idx}"
# ---------------------------------------------------------

# ───────────────────────── Ressourcen ──────────────────────────
BASE_DIR  = Path(__file__).parent
FONT_PATH = BASE_DIR / "fonts" / "DejaVuSans.ttf"
LOGO_PATH = BASE_DIR / "logo.png"

# ───────────────────────── Layout-Konstanten ────────────────────
PAGE_MARGIN = 15
LINE_H      = 7
COLS   = ["Pos.", "Menge", "Kategorie", "Produkt", "Serien-Nr", "BC"]
WIDTHS = [10,      13,       27,          85,       35,          10]

ADDR_LEFT = (
    "<FIRMENNAME>\n"
    "<STANDORT-BEZEICHNUNG>\n"
    "<STRASSE> <HAUSNUMMER>\n"
    "<PLZ> <ORT>\n"
    "Tel.: <LÄNDERVORWAHL> <TELEFONNUMMER>"
)

ADDR_RIGHT = (
    "<FIRMENNAME>\n"
    "<STANDORT-BEZEICHNUNG>\n"
    "<STRASSE> <HAUSNUMMER>\n"
    "<PLZ> <ORT>\n"
    "Tel.: <LÄNDERVORWAHL> <TELEFONNUMMER>"
)


# ────────────────────────────────────────────────────────────────

# ---------- AJAX-Lookup ----------
@app.get("/lookup/<ean>")
@tech_or_admin_required
def lookup_ean(ean):
    name, pid = get_or_fetch_product(ean)
    if not name:
        return {"ok": False}

    with Session(engine) as s:
        row = s.execute(
            select(category.c.name.label("cat"),
                   brand.c.name.label("brand"))
            .select_from(product)
            .join(category, category.c.id == product.c.category_id)
            .outerjoin(brand,   brand.c.id   == product.c.brand_id)
            .where(product.c.id == pid)
        ).first()

    return {
        "ok":    True,
        "pid":   pid,
        "name":  name,
        "cat":   row.cat,
        "brand": row.brand        #  <── NEU
    }

# ---------- Protokoll-Übersicht ----------
@app.get("/slips")
@tech_or_admin_required
def list_slips():
    """Tabelle aller erzeugten PDF-Protokolle mit Such- und Datumsfilter."""
    q       = request.args.get("q", "").strip()         # Suchbegriff
    date_from = request.args.get("from")                # YYYY-MM-DD
    date_to   = request.args.get("to")

    # --- Basis-Query ---------------------------------------------------
    stmt = (
        select(slip.c.number,
               slip.c.order_no,
               slip.c.customer,
               slip.c.created_at)
        .order_by(slip.c.created_at.desc())
    )

    # --- Freitext-Suche (LIKE auf Order-Nr. & Kunde) ------------------
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(slip.c.order_no.ilike(like),
                              slip.c.customer.ilike(like)))

    # --- Datumsbereich -------------------------------------------------
    if date_from:
        stmt = stmt.where(slip.c.created_at >= date_from)
    if date_to:
        # “bis inkl.” → + 1 Tag
        stmt = stmt.where(slip.c.created_at < f"{date_to} 23:59:59")

    with Session(engine) as s:
        rows = s.execute(stmt).all()

    return render_template("slips.html",
                           rows=rows,
                           q=q,
                           date_from=date_from,
                           date_to=date_to)

    
# ---------- Next-Number ----------
@app.get("/api/next-number")
@tech_or_admin_required
def next_number():
    with Session(engine) as s:
        return {"number": _next_slip_number(s)}


# ---------- Neue Maske ----------
@app.get("/")
@tech_or_admin_required
def new_slip():
    with Session(engine) as s:
        cats  = s.execute(select(category)).all()
        nr    = _next_slip_number(s)        # ← hier erzeugen
    return render_template("new_slip.html", cats=cats, slip_no=nr)

# ---------- Speichern ----------
@app.post("/api/save-slip")
@tech_or_admin_required
def save_slip():
    data = request.get_json()
    hdr   = dict(number=data["number"],
                 order_no=data.get("order_no", ""),
                 customer=data.get("customer", ""))
    items = data["items"]

    with Session(engine) as s, s.begin():
        s.execute(insert(slip).values(**hdr).prefix_with("IGNORE"))
        slip_id = s.scalar(select(slip.c.id).where(slip.c.number == hdr["number"]))

        for it in items:
            item_id = s.scalar(
                insert(slip_item)
                   .values(
                      slip_id=slip_id,
                      product_id=it["product_id"],
                      quantity=it.get("quantity", 1)    # hier die Menge
                    )
                .prefix_with("IGNORE")
                .returning(slip_item.c.id)
            )
            if it["sns"]:
                s.execute(insert(serial),
                          [{"item_id": item_id, "sn": sn} for sn in it["sns"]])

    return {"ok": True, "pdf_url": f"/pdf/{hdr['number']}"}

# ---------- Manuelles Produkt ----------
@app.post("/api/manual-product")
def manual_product():
    data = request.get_json()
    brand_id = _ensure_brand(data.get("brand") or "")
    with Session(engine) as s, s.begin():
        pid = s.scalar(
            insert(product)
            .values(ean=data["ean"], name=data["name"],
                    category_id=data["category_id"], brand_id=brand_id)
            .prefix_with("IGNORE")
            .returning(product.c.id))
    return {"ok": True, "pid": pid, "name": data["name"]}

# ---------------------------
@app.context_processor
def inject_year():
    from datetime import datetime
    return dict(year=datetime.now().year)

# ---------- PDF ----------
@app.get("/pdf/<number>")
@tech_or_admin_required
def pdf_slip(number):
    try:
        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=PAGE_MARGIN)
        pdf.add_font("DejaVu", "",  str(FONT_PATH), uni=True)
        pdf.add_font("DejaVu", "B", str(FONT_PATH), uni=True)
        pdf.add_font("DejaVu", "I", str(FONT_PATH), uni=True)   # Italic  ← NEU
        pdf.alias_nb_pages()
        pdf.add_page()

        # ── Briefkopf ────────────────────────────────────────────
        pdf.set_font("DejaVu", "", 8)
        
        # linke Adresse  --------------------------------------------------------
        pdf.set_xy(PAGE_MARGIN, PAGE_MARGIN)
        pdf.multi_cell(60, 4, ADDR_LEFT)      # ganzer Block, 60 mm breit
        
        # Logo (40 mm) wirklich zentriert, 6 mm unter Seitenrand ---------------
        logo_w = 40
        logo_y = PAGE_MARGIN              
        if LOGO_PATH.exists():
            pdf.image(str(LOGO_PATH),
                      x=(pdf.w - logo_w) / 2,
                      y=logo_y,
                      w=logo_w)
        
        # rechte Adresse  -------------------------------------------------------
        pdf.set_xy(pdf.w - PAGE_MARGIN - 60, PAGE_MARGIN)
        pdf.multi_cell(60, 4, ADDR_RIGHT, align="R")
        
        # Trennlinie unter Logo/Adressen  --------------------------------------
        pdf.set_y(logo_y + logo_w + 0.1)
        pdf.line(PAGE_MARGIN, pdf.get_y(),
                 pdf.w - PAGE_MARGIN, pdf.get_y())
        pdf.ln(4)

        # ── Titel + Meta ─────────────────────────────────────────
        with Session(engine) as s:
            hdr = s.execute(
                select(slip.c.order_no, slip.c.customer, slip.c.created_at)
                .where(slip.c.number == number)
            ).first()
        if not hdr:
            return "Dokument nicht gefunden", 404
        
        pdf.set_font("DejaVu", "B", 14)
        pdf.set_x(PAGE_MARGIN)                       # ← Titel ausrichten
        pdf.cell(0, 8, "Seriennummernprotokoll", ln=1)
        
        pdf.set_font("DejaVu", "B", 11)
        LBL = 32                                     # Label-Spaltenbreite
        
        # Bestell-Nr.
        pdf.set_x(PAGE_MARGIN)
        pdf.cell(LBL, 6, "Bestell-Nr.:")
        pdf.cell(0,   6, hdr.order_no or "-", ln=1)
        
        # Kunde
        pdf.set_x(PAGE_MARGIN)
        pdf.cell(LBL, 6, "Kunde:")
        pdf.cell(0,   6, hdr.customer or "-", ln=1)
        
        # Datum
        pdf.set_x(PAGE_MARGIN)
        pdf.cell(LBL, 6, "Datum:")
        pdf.cell(0,   6, f"{hdr.created_at:%d.%m.%Y}", ln=1)
        
        pdf.ln(4)

        # ── Tabellen-Kopf ───────────────────────────────────────
        pdf.set_fill_color(230, 230, 230)
        pdf.set_font("DejaVu", "B", 9)
        pdf.set_x(PAGE_MARGIN)
        for w, label in zip(WIDTHS, COLS):
            pdf.cell(w, LINE_H, label, 1, 0, "C", fill=True)
        pdf.ln(LINE_H)
        
        pdf.set_font("DejaVu", "", 8)               # zurück auf Normal
        
        # ── Daten abfragen ──────────────────────────────────────
        with Session(engine) as s:
          stmt = (
              select(
                  slip_item.c.id.label("pos_id"),
                  slip_item.c.quantity.label("qty"),              # neu
                  category.c.name.label("cat"),
                  product.c.name.label("prod"),
                  func.group_concat(serial.c.sn.op("ORDER BY")(serial.c.sn))
                      .label("sns")
              )
              .select_from(slip)
              .join(slip_item, slip_item.c.slip_id == slip.c.id)
              .join(product,   product.c.id       == slip_item.c.product_id)
              .join(category,  category.c.id      == product.c.category_id)
              .outerjoin(serial, serial.c.item_id == slip_item.c.id)
              .where(slip.c.number == number)
              .group_by(
                  slip_item.c.id,
                  slip_item.c.quantity,                           # neu
                  category.c.name,
                  product.c.name
              )
              .order_by(slip_item.c.id)
          )
      
          # vorausgesetzt, stmt selektiert bereits auch slip_item.c.quantity.label("qty")
          y   = pdf.get_y()
          pos = 1     
          with Session(engine) as s:
              for row in s.execute(stmt):
                  # ── Basisparameter ────────────────────────────────
                  pdf.set_font("DejaVu", "", 8)
                  general_h     = LINE_H               # Zeilenhöhe für Spalten 1–4
                  padding       = 1                    # mm Innenabstand
                  barcode_h     = 6                    # mm Barcode/DataMatrix-Höhe
          
                  # ── Spaltenbreiten ───────────────────────────────
                  w1, w2, w3, w4 = WIDTHS[:4]          # Pos, Menge, Kategorie, Produkt
                  w_sn           = WIDTHS[4]           # Seriennummern-Spalte
                  w_bc           = WIDTHS[5] if len(WIDTHS) > 5 else 0  # optional DataMatrix
          
                  # ── Texte holen ───────────────────────────────────
                  pos_text    = str(pos)
                  qty_text    = str(row.qty)
                  cat_text    = row.cat   or "-"
                  prod_text   = row.prod  or "-"
                  sns_list    = [sn.strip() for sn in (row.sns or "").split(",") if sn.strip()]
                  serial_text = ", ".join(sns_list) if sns_list else "-"
          
                  # ── Höhe Spalten 1–4 ermitteln ────────────────────
                  max_lines = max(
                      len(pdf.multi_cell(w, general_h, t, split_only=True))
                      for w, t in zip((w1, w2, w3, w4),
                                      (pos_text, qty_text, cat_text, prod_text))
                  )
                  text_h = max_lines * general_h
          
                  # ── Höhe Serien-Text ermitteln ───────────────────
                  pdf.set_font("DejaVu", "", 6)
                  serial_line_h = pdf.font_size_pt * 25.4 / 72
                  serial_lines  = pdf.multi_cell(w_sn, serial_line_h, serial_text, split_only=True)
                  serial_h      = len(serial_lines) * serial_line_h
          
                  # ── Gesamt-Zellenhöhe ─────────────────────────────
                  content_h = max(text_h, barcode_h, serial_h)
                  row_h     = content_h + 2 * padding
          
                  # ── Spalten 1–4 zeichnen (zentriert) ─────────────
                  x = PAGE_MARGIN
                  for w, txt in zip((w1, w2, w3, w4), (pos_text, qty_text, cat_text, prod_text)):
                      # 1) Zeilen nur zählen, nicht direkt ausgeben
                      lines = pdf.multi_cell(w, general_h, txt, split_only=True)
                      text_h = len(lines) * general_h
                  
                      # 2) Y so berechnen, dass der Textblock zentriert ist
                      y_text = y + (row_h - text_h) / 2
                  
                      # 3) Für jede Zeile linksbündig ausgeben
                      for line in lines:
                          pdf.set_xy(x, y_text)
                          pdf.cell(w, general_h, line, border=0, align="L")
                          y_text += general_h
                  
                      # 4) Rahmen um die volle Zellenhöhe
                      pdf.rect(x, y, w, row_h)
                      x += w
          
                  # ── Seriennummern-Spalte ─────────────────────────
                  x_sn = x
                  pdf.set_xy(x_sn, y)
                  pdf.rect(x_sn, y, w_sn, row_h)
                  y_text = y + (row_h - serial_h) / 2
                  pdf.set_font("DejaVu", "", 6)
                  for line in serial_lines:
                      pdf.set_xy(x_sn, y_text)
                      pdf.cell(w_sn, serial_line_h, line, border=0, align="C")
                      y_text += serial_line_h
                  x += w_sn
          
                  # ── DataMatrix-Spalte (optional) ─────────────────
                  if w_bc:
                      pdf.set_xy(x, y)
                      pdf.rect(x, y, w_bc, row_h)
                      buf = io.BytesIO()
                      dmtx = dmtx_encode(serial_text.encode("utf8"))
                      img  = Image.frombytes("RGB", (dmtx.width, dmtx.height), dmtx.pixels)
                      img.save(buf, format="PNG")
                      buf.seek(0)
                      inner_w = w_bc - 2 * padding
                      aspect  = dmtx.width / dmtx.height
                      bc_h    = barcode_h
                      bc_w    = bc_h * aspect
                      if bc_w > inner_w:
                          bc_w = inner_w
                          bc_h = bc_w / aspect
                      bc_x = x + (w_bc - bc_w) / 2
                      bc_y = y + (row_h - bc_h) / 2
                      pdf.image(buf, x=bc_x, y=bc_y, w=bc_w, h=bc_h)
                      x += w_bc
          
                  # ── Nächste Zeile ────────────────────────────────
                  y += row_h
                  pdf.set_y(y)
                  pos += 1

        # ── Footer (Seitennummer) ───────────────────────────────
        pdf.set_auto_page_break(auto=False)    # für Footer-Korrektur
        for page_no in range(1, pdf.page_no() + 1):
            pdf.page = page_no
            pdf.set_y(-15)
            pdf.set_font("DejaVu", "I", 7)
            pdf.cell(0, 5,
                     f"Seite {page_no}/{pdf.page_no()}", 0, 0, "C")

        # ---------- PDF ausliefern ----------
        stream = io.BytesIO(pdf.output(dest="S"))
        stream.seek(0)
        
        # ------- Dateiname bauen ------------
        safe_order = slug(hdr.order_no)          # Bestell-Nr.
        safe_cust  = slug(hdr.customer)
        safe_date  = hdr.created_at.strftime("%d.%m.%Y")
        
        file_name = f"{safe_order}_{safe_cust}_{safe_date}_SNProtokoll.pdf"
        
        return send_file(
            stream,
            download_name=file_name,             # ← neu!
            as_attachment=True,
            mimetype="application/pdf"
        )

    except Exception:
        traceback.print_exc(file=sys.stderr)
        return "Interner PDF-Fehler", 500
