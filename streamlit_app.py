from __future__ import annotations

import csv
import hashlib
import os
import shutil
import sqlite3
import zipfile
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from io import BytesIO, StringIO
from pathlib import Path
from typing import Any, Iterable

import streamlit as st

APP_TITLE = "Günday's Home Sipariş Paneli"
DB_PATH = Path("gundays_ultra_panel_v1.db")
DEFAULT_USER = "admin"
DEFAULT_PASS = "admin123"
ORDER_STATUSES = ["Sipariş Alındı", "Hazırlanıyor", "Üretimde", "Hazır", "Sevkiyat Bekliyor", "Gönderildi", "Teslim Edildi", "İptal"]
PAYMENT_METHODS = ["Nakit", "Kredi Kartı", "Havale/EFT", "Çek", "Senet", "Diğer"]
MOBILYA_COLORS = [("Naturel", 0), ("Ceviz", 0), ("Lake Beyaz", 300), ("Siyah", 300)]
GAMER_COLORS = [("Siyah", 0), ("Antrasit", 0), ("Mavi", 0), ("Kırmızı", 0), ("Pembe", 0), ("Yeşil", 0), ("Turuncu", 0), ("Beyaz", 0), ("Sarı", 0)]
NO_COLOR = [("Standart", 0)]

st.set_page_config(page_title=APP_TITLE, page_icon="📦", layout="wide", initial_sidebar_state="expanded")

# ---------------------------- Styling ----------------------------
def inject_css() -> None:
    st.markdown(
        """
        <style>
        :root{
            --bg:#050913; --panel:#0b1324; --panel2:#111a2e; --line:#2a3550;
            --gold:#d5a640; --gold2:#f0c96a; --text:#f7f7f8; --muted:#aab4c5;
            --green:#22c55e; --red:#ef4444; --blue:#60a5fa; --orange:#f59e0b;
        }
        .stApp { background: radial-gradient(circle at top right, #102144 0%, #050913 44%, #050913 100%); color: var(--text); }
        [data-testid="stSidebar"] { background: linear-gradient(180deg, #091326 0%, #050913 100%); border-right:1px solid rgba(213,166,64,.25); }
        [data-testid="stSidebar"] * { color: #f3f4f6; }
        h1, h2, h3 { letter-spacing:-.4px; }
        .block-container { padding-top: 2.1rem; max-width: 1500px; }
        div[data-testid="stMetric"]{
            background: linear-gradient(145deg, rgba(15,24,44,.98), rgba(7,12,24,.98));
            border:1px solid rgba(213,166,64,.55); border-radius:18px; padding:18px 20px;
            box-shadow:0 14px 35px rgba(0,0,0,.28);
        }
        div[data-testid="stMetric"] label { color:#f0c96a !important; font-weight:800 !important; }
        div[data-testid="stMetric"] [data-testid="stMetricValue"] { color:#fff !important; font-weight:900; }
        .info-card{background:linear-gradient(145deg,#0d1629,#09101e); border:1px solid rgba(213,166,64,.35); border-radius:18px; padding:16px 18px; margin:.35rem 0 1rem 0;}
        .soft-card{background:rgba(255,255,255,.035); border:1px solid rgba(255,255,255,.09); border-radius:16px; padding:15px;}
        .ok{background:rgba(34,197,94,.15);border:1px solid rgba(34,197,94,.35);padding:12px 14px;border-radius:12px;color:#86efac;font-weight:800;}
        .warn{background:rgba(245,158,11,.15);border:1px solid rgba(245,158,11,.4);padding:12px 14px;border-radius:12px;color:#fde68a;font-weight:800;}
        .bad{background:rgba(239,68,68,.15);border:1px solid rgba(239,68,68,.35);padding:12px 14px;border-radius:12px;color:#fecaca;font-weight:800;}
        .tiny{color:#aab4c5;font-size:.92rem;}
        .status-pill{display:inline-block;border:1px solid rgba(213,166,64,.45);color:#f0c96a;background:rgba(213,166,64,.12);padding:5px 10px;border-radius:999px;font-weight:800;font-size:.85rem;}
        .big-title{font-size:2.15rem;font-weight:950;margin-bottom:.2rem;}
        .sub{color:#aab4c5;margin-bottom:1.3rem;}
        .stButton > button, .stDownloadButton > button { border-radius:12px; border:1px solid rgba(213,166,64,.55); background:linear-gradient(90deg,rgba(213,166,64,.22),rgba(213,166,64,.12)); color:#fff; font-weight:800; }
        .stButton > button:hover, .stDownloadButton > button:hover { border-color:#f0c96a; color:#fff; background:linear-gradient(90deg,rgba(213,166,64,.35),rgba(213,166,64,.18)); }
        input, textarea, div[data-baseweb="select"] > div { border-radius:12px !important; }
        hr { border-color: rgba(255,255,255,.12); }
        </style>
        """,
        unsafe_allow_html=True,
    )

inject_css()

# ---------------------------- Helpers ----------------------------
def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def money(v: Any) -> str:
    try:
        n = float(v or 0)
    except Exception:
        n = 0.0
    return f"{n:,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")


def parse_float(v: Any) -> float:
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("TL", "").replace("₺", "").replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except Exception:
        return 0.0


def hash_password(pw: str) -> str:
    return hashlib.sha256(pw.encode("utf-8")).hexdigest()


@contextmanager
def connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def q(sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
    with connect() as con:
        cur = con.execute(sql, tuple(params))
        rows = cur.fetchall()
    return [dict(r) for r in rows]


def one(sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
    rows = q(sql, params)
    return rows[0] if rows else None


def exec_sql(sql: str, params: Iterable[Any] = ()) -> int:
    with connect() as con:
        cur = con.execute(sql, tuple(params))
        return int(cur.lastrowid or 0)


def table_cols(table: str) -> set[str]:
    with connect() as con:
        rows = con.execute(f"PRAGMA table_info({table})").fetchall()
    return {r[1] for r in rows}


def add_col(table: str, col: str, decl: str) -> None:
    cols = table_cols(table)
    if col not in cols:
        exec_sql(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")


def create_schema() -> None:
    with connect() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS users(
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                role TEXT DEFAULT 'Admin',
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS firms(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                branch TEXT DEFAULT '',
                contact TEXT DEFAULT '',
                phone TEXT DEFAULT '',
                address TEXT DEFAULT '',
                tax_no TEXT DEFAULT '',
                tax_office TEXT DEFAULT '',
                note TEXT DEFAULT '',
                active INTEGER DEFAULT 1,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS products(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                category TEXT DEFAULT '',
                model TEXT DEFAULT '',
                base_price REAL DEFAULT 0,
                stock INTEGER DEFAULT 0,
                note TEXT DEFAULT '',
                active INTEGER DEFAULT 1,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS product_colors(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                color_name TEXT NOT NULL,
                price_delta REAL DEFAULT 0,
                active INTEGER DEFAULT 1,
                UNIQUE(product_id, color_name),
                FOREIGN KEY(product_id) REFERENCES products(id)
            );
            CREATE TABLE IF NOT EXISTS orders(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_no TEXT UNIQUE,
                firm_id INTEGER,
                order_date TEXT,
                delivery_date TEXT,
                status TEXT DEFAULT 'Sipariş Alındı',
                general_note TEXT DEFAULT '',
                shipment_note TEXT DEFAULT '',
                created_by TEXT DEFAULT 'admin',
                active INTEGER DEFAULT 1,
                created_at TEXT,
                FOREIGN KEY(firm_id) REFERENCES firms(id)
            );
            CREATE TABLE IF NOT EXISTS order_items(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER,
                product_id INTEGER,
                product_name TEXT DEFAULT '',
                color_name TEXT DEFAULT '',
                qty INTEGER DEFAULT 1,
                unit_price REAL DEFAULT 0,
                line_total REAL DEFAULT 0,
                note TEXT DEFAULT '',
                FOREIGN KEY(order_id) REFERENCES orders(id),
                FOREIGN KEY(product_id) REFERENCES products(id)
            );
            CREATE TABLE IF NOT EXISTS payments(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER,
                payment_date TEXT,
                method TEXT,
                amount REAL DEFAULT 0,
                due_months INTEGER DEFAULT 0,
                due_date TEXT DEFAULT '',
                note TEXT DEFAULT '',
                created_at TEXT,
                FOREIGN KEY(order_id) REFERENCES orders(id)
            );
            """
        )

    # Migration guard for old/partial DB files.
    for table, cols in {
        "firms": {"name": "TEXT DEFAULT ''", "branch": "TEXT DEFAULT ''", "contact": "TEXT DEFAULT ''", "phone": "TEXT DEFAULT ''", "address": "TEXT DEFAULT ''", "tax_no": "TEXT DEFAULT ''", "tax_office": "TEXT DEFAULT ''", "note": "TEXT DEFAULT ''", "active": "INTEGER DEFAULT 1", "created_at": "TEXT"},
        "products": {"name": "TEXT DEFAULT ''", "category": "TEXT DEFAULT ''", "model": "TEXT DEFAULT ''", "base_price": "REAL DEFAULT 0", "stock": "INTEGER DEFAULT 0", "note": "TEXT DEFAULT ''", "active": "INTEGER DEFAULT 1", "created_at": "TEXT"},
        "orders": {"order_no": "TEXT", "firm_id": "INTEGER", "order_date": "TEXT", "delivery_date": "TEXT", "status": "TEXT DEFAULT 'Sipariş Alındı'", "general_note": "TEXT DEFAULT ''", "shipment_note": "TEXT DEFAULT ''", "created_by": "TEXT DEFAULT 'admin'", "active": "INTEGER DEFAULT 1", "created_at": "TEXT"},
        "order_items": {"order_id": "INTEGER", "product_id": "INTEGER", "product_name": "TEXT DEFAULT ''", "color_name": "TEXT DEFAULT ''", "qty": "INTEGER DEFAULT 1", "unit_price": "REAL DEFAULT 0", "line_total": "REAL DEFAULT 0", "note": "TEXT DEFAULT ''"},
        "payments": {"order_id": "INTEGER", "payment_date": "TEXT", "method": "TEXT", "amount": "REAL DEFAULT 0", "due_months": "INTEGER DEFAULT 0", "due_date": "TEXT DEFAULT ''", "note": "TEXT DEFAULT ''", "created_at": "TEXT"},
    }.items():
        for c, decl in cols.items():
            add_col(table, c, decl)

    if not one("SELECT username FROM users WHERE username=?", [DEFAULT_USER]):
        exec_sql(
            "INSERT INTO users(username,password_hash,role,created_at) VALUES(?,?,?,?)",
            [DEFAULT_USER, hash_password(DEFAULT_PASS), "Admin", now_str()],
        )


def init_defaults() -> None:
    # Keep defaults minimal. User can delete/passive later.
    if not q("SELECT id FROM firms LIMIT 1"):
        exec_sql("INSERT INTO firms(name,branch,contact,phone,address,tax_no,tax_office,note,active,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)", ["Hedef AVM", "Merkez", "", "", "", "", "", "Demo firma", 1, now_str()])
    if not q("SELECT id FROM products LIMIT 1"):
        pid = exec_sql("INSERT INTO products(name,category,model,base_price,stock,note,active,created_at) VALUES(?,?,?,?,?,?,?,?)", ["İkili Dilsiz Uşak", "Mobilya", "Ahşap", 1250, 20, "Demo ürün", 1, now_str()])
        for color, delta in MOBILYA_COLORS:
            exec_sql("INSERT OR IGNORE INTO product_colors(product_id,color_name,price_delta,active) VALUES(?,?,?,1)", [pid, color, delta])


create_schema()
init_defaults()

# ---------------------------- Data fetchers ----------------------------
def firm_label(r: dict[str, Any]) -> str:
    branch = (r.get("branch") or "").strip()
    return f"{r.get('name','')} / {branch}" if branch else str(r.get("name", ""))


def product_label(r: dict[str, Any]) -> str:
    bits = [str(r.get("name") or "")]
    if r.get("model"):
        bits.append(str(r["model"]))
    if r.get("category"):
        bits.append(str(r["category"]))
    return " - ".join([b for b in bits if b])


def active_firms() -> list[dict[str, Any]]:
    return q("SELECT * FROM firms WHERE COALESCE(active,1)=1 ORDER BY name, branch")


def active_products() -> list[dict[str, Any]]:
    return q("SELECT * FROM products WHERE COALESCE(active,1)=1 ORDER BY name, model")


def colors_for_product(product_id: int) -> list[dict[str, Any]]:
    rows = q("SELECT * FROM product_colors WHERE product_id=? AND COALESCE(active,1)=1 ORDER BY color_name", [product_id])
    if not rows:
        exec_sql("INSERT OR IGNORE INTO product_colors(product_id,color_name,price_delta,active) VALUES(?,?,?,1)", [product_id, "Standart", 0])
        rows = q("SELECT * FROM product_colors WHERE product_id=? AND COALESCE(active,1)=1 ORDER BY color_name", [product_id])
    return rows


def next_order_no() -> str:
    year = datetime.now().year
    row = one("SELECT COUNT(*) AS n FROM orders WHERE order_no LIKE ?", [f"GH-{year}-%"])
    n = int(row["n"] or 0) + 1 if row else 1
    return f"GH-{year}-{n:04d}"


def order_totals(order_id: int) -> tuple[float, float, float]:
    total_row = one("SELECT COALESCE(SUM(line_total),0) AS total FROM order_items WHERE order_id=?", [order_id])
    paid_row = one("SELECT COALESCE(SUM(amount),0) AS paid FROM payments WHERE order_id=?", [order_id])
    total = float(total_row["total"] or 0) if total_row else 0.0
    paid = float(paid_row["paid"] or 0) if paid_row else 0.0
    return total, paid, max(total - paid, 0)


def payment_status(total: float, paid: float) -> str:
    if total <= 0:
        return "Bekliyor"
    if paid <= 0:
        return "Bekliyor"
    if paid + 0.01 >= total:
        return "Ödendi"
    return "Kısmi Ödendi"


def order_rows(where: str = "", params: list[Any] | None = None) -> list[dict[str, Any]]:
    params = params or []
    rows = q(
        f"""
        SELECT o.*, f.name AS firm_name, f.branch AS firm_branch
        FROM orders o
        LEFT JOIN firms f ON f.id=o.firm_id
        WHERE COALESCE(o.active,1)=1 {where}
        ORDER BY date(o.created_at) DESC, o.id DESC
        """,
        params,
    )
    out: list[dict[str, Any]] = []
    for r in rows:
        total, paid, remaining = order_totals(int(r["id"]))
        r["total"] = total
        r["paid"] = paid
        r["remaining"] = remaining
        r["payment_status"] = payment_status(total, paid)
        r["firm"] = firm_label({"name": r.get("firm_name") or "", "branch": r.get("firm_branch") or ""})
        out.append(r)
    return out


def order_items(order_id: int) -> list[dict[str, Any]]:
    return q("SELECT * FROM order_items WHERE order_id=? ORDER BY id", [order_id])


def order_payments(order_id: int) -> list[dict[str, Any]]:
    return q("SELECT * FROM payments WHERE order_id=? ORDER BY payment_date DESC, id DESC", [order_id])


def display_table(rows: list[dict[str, Any]], columns: list[str] | None = None) -> None:
    if not rows:
        st.info("Kayıt yok.")
        return
    data = rows
    if columns:
        data = [{c: r.get(c, "") for c in columns} for r in rows]
    st.dataframe(data, use_container_width=True)


def safe_delete_or_passive(table: str, row_id: int, used_sql: str, used_params: list[Any]) -> str:
    used = one(used_sql, used_params)
    n = int((used or {}).get("n") or 0)
    if n > 0:
        exec_sql(f"UPDATE {table} SET active=0 WHERE id=?", [row_id])
        return "Kayıt geçmiş işlemlerde kullanıldığı için silinmedi, pasife alındı."
    exec_sql(f"DELETE FROM {table} WHERE id=?", [row_id])
    return "Kayıt kalıcı olarak silindi."

# ---------------------------- Auth ----------------------------
def login_page() -> None:
    st.markdown("<div class='big-title'>Günday's Home Sipariş Paneli</div>", unsafe_allow_html=True)
    st.markdown("<div class='sub'>Firma, ürün, sipariş ve ödeme takibini tek ekrandan yönetin.</div>", unsafe_allow_html=True)
    _, mid, _ = st.columns([1, 1.2, 1])
    with mid:
        st.markdown("### Yönetim Paneli Girişi")
        with st.form("login_form"):
            username = st.text_input("Kullanıcı adı")
            password = st.text_input("Şifre", type="password")
            ok = st.form_submit_button("Giriş yap", use_container_width=True)
        if ok:
            u = one("SELECT * FROM users WHERE username=?", [username.strip()])
            if u and u["password_hash"] == hash_password(password):
                st.session_state.logged_in = True
                st.session_state.username = username.strip()
                st.rerun()
            else:
                st.error("Kullanıcı adı veya şifre hatalı.")
        st.info("İlk giriş: admin / admin123")

# ---------------------------- Pages ----------------------------
def dashboard_page() -> None:
    st.markdown("<div class='big-title'>Dashboard</div>", unsafe_allow_html=True)
    st.markdown("<div class='sub'>Günday's Home genel sipariş özeti</div>", unsafe_allow_html=True)
    orders = order_rows()
    total_orders = len(orders)
    active_orders = len([o for o in orders if o.get("status") not in ["Teslim Edildi", "İptal"]])
    revenue = sum(float(o.get("total") or 0) for o in orders if o.get("status") != "İptal")
    remaining = sum(float(o.get("remaining") or 0) for o in orders if o.get("status") != "İptal")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Toplam Sipariş", total_orders, "Tüm kayıtlar")
    c2.metric("Aktif Sipariş", active_orders, "Teslim/iptal hariç")
    c3.metric("Ciro", money(revenue), "Sipariş toplamı")
    c4.metric("Kalan Ödeme", money(remaining), "Tahsil edilecek")

    st.divider()
    left, right = st.columns([1.15, 1])
    with left:
        st.markdown("### Son Siparişler")
        recent = orders[:8]
        rows = []
        for o in recent:
            rows.append({"Sipariş No": o.get("order_no"), "Firma": o.get("firm"), "Tarih": o.get("order_date"), "Teslim": o.get("delivery_date"), "Durum": o.get("status"), "Ödeme": o.get("payment_status"), "Toplam": money(o.get("total"))})
        display_table(rows)
    with right:
        st.markdown("### Durum Dağılımı")
        counts: dict[str, int] = {}
        for o in orders:
            counts[o.get("status") or "-"] = counts.get(o.get("status") or "-", 0) + 1
        display_table([{"Durum": k, "Adet": v} for k, v in counts.items()])

    st.markdown("### Teslimatı Yaklaşan Siparişler")
    today = date.today()
    alerts = []
    for o in orders:
        if o.get("status") in ["Teslim Edildi", "İptal"]:
            continue
        ds = (o.get("delivery_date") or "").strip()
        if not ds:
            continue
        try:
            dd = datetime.strptime(ds, "%Y-%m-%d").date()
        except Exception:
            continue
        days = (dd - today).days
        if days < 0:
            alerts.append({"Sipariş No": o["order_no"], "Firma": o["firm"], "Teslim": ds, "Uyarı": f"{abs(days)} gün gecikti", "Kalan": money(o["remaining"])})
        elif days <= 3:
            alerts.append({"Sipariş No": o["order_no"], "Firma": o["firm"], "Teslim": ds, "Uyarı": f"{days} gün kaldı", "Kalan": money(o["remaining"])})
    if alerts:
        st.markdown("<div class='warn'>Teslim tarihi yaklaşan / geçmiş sipariş var.</div>", unsafe_allow_html=True)
        display_table(alerts)
    else:
        st.markdown("<div class='ok'>Şu an kritik teslimat uyarısı yok.</div>", unsafe_allow_html=True)


def firms_page() -> None:
    st.markdown("<div class='big-title'>Firmalar</div>", unsafe_allow_html=True)
    st.markdown("<div class='sub'>Bayi, müşteri ve şube kartlarını yönetin</div>", unsafe_allow_html=True)
    with st.expander("+ Yeni firma / şube ekle", expanded=True):
        with st.form("add_firm"):
            c1, c2, c3 = st.columns(3)
            name = c1.text_input("Firma adı *")
            phone = c2.text_input("Telefon")
            branch = c1.text_input("Şube")
            tax_no = c2.text_input("Vergi No / VKN")
            contact = c1.text_input("Yetkili kişi")
            tax_office = c2.text_input("Vergi Dairesi")
            address = c3.text_area("Adres", height=110)
            note = c3.text_area("Not", height=90)
            submit = st.form_submit_button("Firmayı kaydet", use_container_width=True)
        if submit:
            if not name.strip():
                st.error("Firma adı zorunlu.")
            else:
                exec_sql("INSERT INTO firms(name,branch,contact,phone,address,tax_no,tax_office,note,active,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)", [name.strip(), branch.strip(), contact.strip(), phone.strip(), address.strip(), tax_no.strip(), tax_office.strip(), note.strip(), 1, now_str()])
                st.success("Firma kaydedildi.")
                st.rerun()

    st.markdown("### Kayıtlı Firmalar")
    firms = q("SELECT * FROM firms ORDER BY active DESC, name, branch")
    display_table([{ "ID": r["id"], "Firma": r.get("name"), "Şube": r.get("branch"), "Yetkili": r.get("contact"), "Telefon": r.get("phone"), "Adres": r.get("address"), "Durum": "Aktif" if r.get("active") else "Pasif", "Kayıt": r.get("created_at") } for r in firms])

    st.markdown("### Firma Düzelt / Sil")
    if firms:
        opts = {f"{r['id']} - {firm_label(r)}": r for r in firms}
        sel = st.selectbox("Firma seç", list(opts.keys()), key="firm_edit_select")
        r = opts[sel]
        with st.form("edit_firm"):
            c1, c2, c3 = st.columns(3)
            ename = c1.text_input("Firma adı", value=r.get("name") or "")
            ephone = c2.text_input("Telefon", value=r.get("phone") or "")
            ebranch = c1.text_input("Şube", value=r.get("branch") or "")
            etax = c2.text_input("Vergi No / VKN", value=r.get("tax_no") or "")
            econtact = c1.text_input("Yetkili kişi", value=r.get("contact") or "")
            etaxoff = c2.text_input("Vergi Dairesi", value=r.get("tax_office") or "")
            eactive = c3.selectbox("Durum", ["Aktif", "Pasif"], index=0 if r.get("active") else 1)
            eaddress = c3.text_area("Adres", value=r.get("address") or "", height=100)
            enote = st.text_area("Not", value=r.get("note") or "")
            save = st.form_submit_button("Değişiklikleri kaydet", use_container_width=True)
        if save:
            exec_sql("UPDATE firms SET name=?,branch=?,contact=?,phone=?,address=?,tax_no=?,tax_office=?,note=?,active=? WHERE id=?", [ename.strip(), ebranch.strip(), econtact.strip(), ephone.strip(), eaddress.strip(), etax.strip(), etaxoff.strip(), enote.strip(), 1 if eactive == "Aktif" else 0, r["id"]])
            st.success("Firma güncellendi.")
            st.rerun()
        cdel1, cdel2 = st.columns(2)
        if cdel1.button("Firmayı pasife al", use_container_width=True):
            exec_sql("UPDATE firms SET active=0 WHERE id=?", [r["id"]])
            st.warning("Firma pasife alındı.")
            st.rerun()
        if cdel2.button("Firmayı sil / geçmiş varsa pasife al", use_container_width=True):
            msg = safe_delete_or_passive("firms", int(r["id"]), "SELECT COUNT(*) AS n FROM orders WHERE firm_id=?", [r["id"]])
            st.warning(msg)
            st.rerun()


def product_color_template(template: str) -> list[tuple[str, float]]:
    if template == "Mobilya renkleri":
        return MOBILYA_COLORS
    if template == "Oyuncu koltuğu renkleri":
        return GAMER_COLORS
    return NO_COLOR


def products_page() -> None:
    st.markdown("<div class='big-title'>Ürünler</div>", unsafe_allow_html=True)
    st.markdown("<div class='sub'>Ürün kartları ve renk seçeneklerini yönetin</div>", unsafe_allow_html=True)

    with st.expander("+ Yeni ürün ekle", expanded=True):
        with st.form("add_product"):
            c1, c2, c3 = st.columns(3)
            name = c1.text_input("Ürün adı *")
            category = c1.text_input("Kategori", placeholder="Örn: Oyuncu Koltuğu, Mobilya")
            model = c2.text_input("Model")
            base_price = c2.number_input("Ana fiyat", min_value=0.0, step=50.0, format="%.2f")
            stock = c3.number_input("Stok", min_value=0, step=1)
            template = c3.selectbox("Renk şablonu", ["Mobilya renkleri", "Oyuncu koltuğu renkleri", "Renk istemiyorum"])
            note = st.text_area("Not")
            submit = st.form_submit_button("Ürünü kaydet", use_container_width=True)
        if submit:
            if not name.strip():
                st.error("Ürün adı zorunlu.")
            else:
                pid = exec_sql("INSERT INTO products(name,category,model,base_price,stock,note,active,created_at) VALUES(?,?,?,?,?,?,?,?)", [name.strip(), category.strip(), model.strip(), base_price, int(stock), note.strip(), 1, now_str()])
                for color, delta in product_color_template(template):
                    exec_sql("INSERT OR IGNORE INTO product_colors(product_id,color_name,price_delta,active) VALUES(?,?,?,1)", [pid, color, delta])
                st.success("Ürün kaydedildi.")
                st.rerun()

    st.markdown("### Kayıtlı Ürünler")
    products = q("SELECT * FROM products ORDER BY active DESC, name, model")
    rows = []
    for p in products:
        color_txt = ", ".join([f"{c['color_name']} (+{money(c['price_delta'])})" if float(c.get("price_delta") or 0) else c["color_name"] for c in colors_for_product(int(p["id"]))])
        rows.append({"ID": p["id"], "Ürün": p.get("name"), "Kategori": p.get("category"), "Model": p.get("model"), "Ana Fiyat": money(p.get("base_price")), "Stok": p.get("stock"), "Renkler": color_txt, "Durum": "Aktif" if p.get("active") else "Pasif"})
    display_table(rows)

    st.markdown("### Ürün Düzelt / Renk Yönetimi")
    if products:
        opts = {f"{p['id']} - {product_label(p)}": p for p in products}
        sel = st.selectbox("Ürün seç", list(opts.keys()), key="product_edit_select")
        p = opts[sel]
        with st.form("edit_product"):
            c1, c2, c3 = st.columns(3)
            ename = c1.text_input("Ürün adı", value=p.get("name") or "")
            ecat = c1.text_input("Kategori", value=p.get("category") or "")
            emodel = c2.text_input("Model", value=p.get("model") or "")
            eprice = c2.number_input("Ana fiyat", min_value=0.0, step=50.0, format="%.2f", value=float(p.get("base_price") or 0))
            estock = c3.number_input("Stok", min_value=0, step=1, value=int(p.get("stock") or 0))
            eactive = c3.selectbox("Durum", ["Aktif", "Pasif"], index=0 if p.get("active") else 1)
            enote = st.text_area("Not", value=p.get("note") or "")
            save = st.form_submit_button("Ürünü güncelle", use_container_width=True)
        if save:
            exec_sql("UPDATE products SET name=?,category=?,model=?,base_price=?,stock=?,note=?,active=? WHERE id=?", [ename.strip(), ecat.strip(), emodel.strip(), eprice, int(estock), enote.strip(), 1 if eactive == "Aktif" else 0, p["id"]])
            st.success("Ürün güncellendi.")
            st.rerun()

        st.markdown("#### Renk seçenekleri")
        color_rows = colors_for_product(int(p["id"]))
        display_table([{"ID": c["id"], "Renk": c["color_name"], "Ek Ücret": money(c["price_delta"]), "Durum": "Aktif" if c.get("active") else "Pasif"} for c in color_rows])
        with st.form("add_color"):
            cc1, cc2 = st.columns(2)
            cname = cc1.text_input("Yeni renk adı")
            cdelta = cc2.number_input("Ek ücret", step=50.0, format="%.2f")
            addc = st.form_submit_button("Rengi ekle", use_container_width=True)
        if addc and cname.strip():
            exec_sql("INSERT OR IGNORE INTO product_colors(product_id,color_name,price_delta,active) VALUES(?,?,?,1)", [p["id"], cname.strip(), cdelta])
            st.success("Renk eklendi.")
            st.rerun()
        if color_rows:
            color_opts = {f"{c['id']} - {c['color_name']}": c for c in color_rows}
            csel = st.selectbox("Silinecek/pasife alınacak renk", list(color_opts.keys()))
            if st.button("Rengi pasife al", use_container_width=True):
                exec_sql("UPDATE product_colors SET active=0 WHERE id=?", [color_opts[csel]["id"]])
                st.warning("Renk pasife alındı.")
                st.rerun()
        cdel1, cdel2 = st.columns(2)
        if cdel1.button("Ürünü pasife al", use_container_width=True):
            exec_sql("UPDATE products SET active=0 WHERE id=?", [p["id"]])
            st.warning("Ürün pasife alındı.")
            st.rerun()
        if cdel2.button("Ürünü sil / geçmiş varsa pasife al", use_container_width=True):
            msg = safe_delete_or_passive("products", int(p["id"]), "SELECT COUNT(*) AS n FROM order_items WHERE product_id=?", [p["id"]])
            st.warning(msg)
            st.rerun()


def new_order_page() -> None:
    st.markdown("<div class='big-title'>Yeni Sipariş</div>", unsafe_allow_html=True)
    st.markdown("<div class='sub'>Firma seçin, ürünleri sepete ekleyin ve siparişi kaydedin</div>", unsafe_allow_html=True)
    firms = active_firms()
    products = active_products()
    if not firms:
        st.warning("Önce firma eklemelisin.")
        return
    if not products:
        st.warning("Önce ürün eklemelisin.")
        return
    if "cart" not in st.session_state:
        st.session_state.cart = []

    st.markdown("### Sipariş Bilgileri")
    c1, c2, c3 = st.columns(3)
    firm_opts = {firm_label(f): f for f in firms}
    firm_sel = c1.selectbox("Firma / Şube", list(firm_opts.keys()))
    order_dt = c2.date_input("Sipariş tarihi", value=date.today())
    delivery_dt = c2.date_input("Tahmini teslim tarihi", value=date.today() + timedelta(days=7))
    status = c3.selectbox("Sipariş durumu", ORDER_STATUSES, index=0)
    created_by = c3.text_input("Oluşturan", value=st.session_state.get("username", "admin"))
    shipment_note = st.text_area("Sevkiyat notu")
    general_note = st.text_area("Genel not")

    st.markdown("### Ürün Kalemi Ekle")
    product_opts = {product_label(p): p for p in products}
    pc1, pc2, pc3, pc4 = st.columns([2, 1.2, 1, 1])
    psel = pc1.selectbox("Ürün", list(product_opts.keys()))
    prod = product_opts[psel]
    colors = colors_for_product(int(prod["id"]))
    color_opts = {f"{c['color_name']} (+{money(c['price_delta'])})": c for c in colors}
    csel = pc2.selectbox("Renk", list(color_opts.keys()))
    color = color_opts[csel]
    qty = pc3.number_input("Adet", min_value=1, step=1, value=1)
    default_unit = float(prod.get("base_price") or 0) + float(color.get("price_delta") or 0)
    unit_price = pc4.number_input("Birim fiyat", min_value=0.0, step=50.0, format="%.2f", value=float(default_unit))
    note = st.text_input("Kalem notu")
    line_total = int(qty) * float(unit_price)
    st.markdown(f"<div class='info-card'><b>Satır toplamı:</b> {money(line_total)}</div>", unsafe_allow_html=True)
    if st.button("+ Kalemi sepete ekle", use_container_width=True):
        st.session_state.cart.append({"product_id": prod["id"], "product_name": prod["name"], "color_name": color["color_name"], "qty": int(qty), "unit_price": float(unit_price), "line_total": float(line_total), "note": note})
        st.success("Kalem sepete eklendi.")
        st.rerun()

    st.markdown("### Sipariş Sepeti")
    if st.session_state.cart:
        display_table([{ "Ürün": i["product_name"], "Renk": i["color_name"], "Adet": i["qty"], "Birim": money(i["unit_price"]), "Toplam": money(i["line_total"]), "Not": i.get("note", "") } for i in st.session_state.cart])
        total = sum(float(i["line_total"]) for i in st.session_state.cart)
        st.metric("Sipariş Toplamı", money(total))
        cc1, cc2 = st.columns(2)
        if cc1.button("Sepeti temizle", use_container_width=True):
            st.session_state.cart = []
            st.rerun()
        if cc2.button("Siparişi kaydet", use_container_width=True):
            order_id = exec_sql("INSERT INTO orders(order_no,firm_id,order_date,delivery_date,status,general_note,shipment_note,created_by,active,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)", [next_order_no(), firm_opts[firm_sel]["id"], str(order_dt), str(delivery_dt), status, general_note.strip(), shipment_note.strip(), created_by.strip(), 1, now_str()])
            for i in st.session_state.cart:
                exec_sql("INSERT INTO order_items(order_id,product_id,product_name,color_name,qty,unit_price,line_total,note) VALUES(?,?,?,?,?,?,?,?)", [order_id, i["product_id"], i["product_name"], i["color_name"], i["qty"], i["unit_price"], i["line_total"], i.get("note", "")])
            st.session_state.cart = []
            st.success("Sipariş kaydedildi.")
            st.rerun()
    else:
        st.info("Sepette ürün yok.")


def orders_page() -> None:
    st.markdown("<div class='big-title'>Siparişler</div>", unsafe_allow_html=True)
    st.markdown("<div class='sub'>Siparişleri filtreleyin, ödeme ve teslimat durumunu yönetin</div>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    search = c1.text_input("Firma / Sipariş ara")
    status_filter = c2.selectbox("Durum", ["Tümü"] + ORDER_STATUSES)
    pay_filter = c3.selectbox("Ödeme", ["Tümü", "Bekliyor", "Kısmi Ödendi", "Ödendi"])

    orders = order_rows()
    if search.strip():
        s = search.lower().strip()
        orders = [o for o in orders if s in (o.get("firm") or "").lower() or s in (o.get("order_no") or "").lower()]
    if status_filter != "Tümü":
        orders = [o for o in orders if o.get("status") == status_filter]
    if pay_filter != "Tümü":
        orders = [o for o in orders if o.get("payment_status") == pay_filter]

    rows = [{"ID": o["id"], "Sipariş No": o["order_no"], "Firma": o["firm"], "Sipariş": o["order_date"], "Teslim": o["delivery_date"], "Durum": o["status"], "Ödeme": o["payment_status"], "Toplam": money(o["total"]), "Ödenen": money(o["paid"]), "Kalan": money(o["remaining"])} for o in orders]
    display_table(rows)

    st.markdown("### Sipariş Detayı / Güncelleme")
    if not orders:
        return
    opts = {f"{o['order_no']} - {o['firm']} - {money(o['total'])}": o for o in orders}
    sel = st.selectbox("Sipariş seç", list(opts.keys()))
    o = opts[sel]
    total, paid, remaining = order_totals(int(o["id"]))
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Toplam", money(total))
    m2.metric("Ödenen", money(paid))
    m3.metric("Kalan", money(remaining))
    m4.metric("Ödeme", payment_status(total, paid))

    st.markdown("#### Ürün Kalemleri")
    display_table([{ "Ürün": i["product_name"], "Renk": i["color_name"], "Adet": i["qty"], "Birim": money(i["unit_price"]), "Toplam": money(i["line_total"]), "Not": i.get("note", "") } for i in order_items(int(o["id"]))])

    st.markdown("#### Sipariş bilgilerini güncelle")
    with st.form("order_update"):
        u1, u2, u3 = st.columns(3)
        new_status = u1.selectbox("Durum", ORDER_STATUSES, index=ORDER_STATUSES.index(o.get("status")) if o.get("status") in ORDER_STATUSES else 0)
        try:
            dd_val = datetime.strptime(o.get("delivery_date") or str(date.today()), "%Y-%m-%d").date()
        except Exception:
            dd_val = date.today()
        new_delivery = u2.date_input("Teslim tarihi", value=dd_val)
        shipment = st.text_area("Sevkiyat notu", value=o.get("shipment_note") or "")
        general = st.text_area("Genel not", value=o.get("general_note") or "")
        upd = st.form_submit_button("Siparişi güncelle", use_container_width=True)
    if upd:
        exec_sql("UPDATE orders SET status=?, delivery_date=?, shipment_note=?, general_note=? WHERE id=?", [new_status, str(new_delivery), shipment, general, o["id"]])
        st.success("Sipariş güncellendi.")
        st.rerun()

    st.markdown("#### Ödemeler")
    pays = order_payments(int(o["id"]))
    display_table([{ "ID": p["id"], "Tarih": p["payment_date"], "Yöntem": p["method"], "Tutar": money(p["amount"]), "Vade Ayı": p.get("due_months"), "Vade Tarihi": p.get("due_date"), "Not": p.get("note") } for p in pays])
    with st.form("add_payment"):
        p1, p2, p3, p4 = st.columns(4)
        pay_date = p1.date_input("Ödeme tarihi", value=date.today())
        method = p2.selectbox("Yöntem", PAYMENT_METHODS)
        amount = p3.number_input("Tutar", min_value=0.0, step=100.0, format="%.2f")
        due_months = p4.number_input("Vade ayı", min_value=0, step=1, value=0)
        due_date = st.date_input("Vade tarihi", value=date.today()) if method in ["Çek", "Senet"] else None
        pnote = st.text_input("Ödeme notu")
        addp = st.form_submit_button("Ödeme ekle", use_container_width=True)
    if addp:
        if amount <= 0:
            st.error("Ödeme tutarı 0'dan büyük olmalı.")
        else:
            exec_sql("INSERT INTO payments(order_id,payment_date,method,amount,due_months,due_date,note,created_at) VALUES(?,?,?,?,?,?,?,?)", [o["id"], str(pay_date), method, amount, int(due_months), str(due_date) if due_date else "", pnote, now_str()])
            st.success("Ödeme eklendi.")
            st.rerun()
    if pays:
        del_opts = {f"{p['id']} - {p['method']} - {money(p['amount'])}": p for p in pays}
        del_sel = st.selectbox("Silinecek ödeme", list(del_opts.keys()))
        if st.button("Seçili ödemeyi sil", use_container_width=True):
            exec_sql("DELETE FROM payments WHERE id=?", [del_opts[del_sel]["id"]])
            st.warning("Ödeme silindi.")
            st.rerun()

    st.markdown("#### Tehlikeli işlem")
    if st.button("Bu siparişi komple sil", use_container_width=True):
        exec_sql("DELETE FROM payments WHERE order_id=?", [o["id"]])
        exec_sql("DELETE FROM order_items WHERE order_id=?", [o["id"]])
        exec_sql("DELETE FROM orders WHERE id=?", [o["id"]])
        st.warning("Sipariş, kalemleri ve ödemeleri silindi.")
        st.rerun()


def backup_zip_bytes() -> bytes:
    buf = BytesIO()
    tables = ["firms", "products", "product_colors", "orders", "order_items", "payments"]
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for table in tables:
            rows = q(f"SELECT * FROM {table}")
            csv_buf = StringIO()
            if rows:
                writer = csv.DictWriter(csv_buf, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)
            else:
                csv_buf.write("")
            zf.writestr(f"{table}.csv", csv_buf.getvalue())
    return buf.getvalue()


def settings_page() -> None:
    st.markdown("<div class='big-title'>Yedek / Ayarlar</div>", unsafe_allow_html=True)
    st.markdown("<div class='sub'>Yedek alma, veritabanı indirme ve şifre değişimi</div>", unsafe_allow_html=True)
    st.markdown("### Yedekler")
    c1, c2 = st.columns(2)
    c1.download_button("CSV yedeği indir", data=backup_zip_bytes(), file_name=f"gundays_csv_yedek_{datetime.now().strftime('%Y%m%d_%H%M')}.zip", mime="application/zip", use_container_width=True)
    if DB_PATH.exists():
        c2.download_button("SQLite veritabanı indir", data=DB_PATH.read_bytes(), file_name=f"gundays_veritabani_{datetime.now().strftime('%Y%m%d_%H%M')}.db", mime="application/octet-stream", use_container_width=True)

    st.markdown("### Veritabanını onar")
    if st.button("Veritabanı tablolarını/kolonlarını kontrol et", use_container_width=True):
        create_schema()
        st.success("Veritabanı kontrol edildi.")

    st.markdown("### Şifre değiştir")
    with st.form("change_pw"):
        old = st.text_input("Mevcut şifre", type="password")
        new = st.text_input("Yeni şifre", type="password")
        new2 = st.text_input("Yeni şifre tekrar", type="password")
        ok = st.form_submit_button("Şifreyi değiştir", use_container_width=True)
    if ok:
        username = st.session_state.get("username", DEFAULT_USER)
        u = one("SELECT * FROM users WHERE username=?", [username])
        if not u or u["password_hash"] != hash_password(old):
            st.error("Mevcut şifre hatalı.")
        elif len(new) < 4:
            st.error("Yeni şifre en az 4 karakter olmalı.")
        elif new != new2:
            st.error("Yeni şifreler eşleşmiyor.")
        else:
            exec_sql("UPDATE users SET password_hash=? WHERE username=?", [hash_password(new), username])
            st.success("Şifre değiştirildi.")

    st.markdown("### Geri yükleme")
    uploaded = st.file_uploader("SQLite .db yedeği yükle", type=["db", "sqlite", "sqlite3"])
    if uploaded is not None:
        if st.button("Yedeği geri yükle", use_container_width=True):
            DB_PATH.write_bytes(uploaded.read())
            create_schema()
            st.success("Yedek geri yüklendi. Uygulamayı yeniden başlatman iyi olur.")

# ---------------------------- Main ----------------------------
def sidebar() -> str:
    st.sidebar.markdown("### Günday's Home")
    st.sidebar.caption(f"Kullanıcı: {st.session_state.get('username','admin')}")
    pages = ["Dashboard", "Firmalar", "Ürünler", "Yeni Sipariş", "Siparişler", "Yedek / Ayarlar"]
    page = st.sidebar.radio("", pages, label_visibility="collapsed")
    st.sidebar.divider()
    if st.sidebar.button("Çıkış yap", use_container_width=True):
        st.session_state.logged_in = False
        st.session_state.username = ""
        st.rerun()
    return page


def main() -> None:
    if not st.session_state.get("logged_in"):
        login_page()
        return
    page = sidebar()
    if page == "Dashboard":
        dashboard_page()
    elif page == "Firmalar":
        firms_page()
    elif page == "Ürünler":
        products_page()
    elif page == "Yeni Sipariş":
        new_order_page()
    elif page == "Siparişler":
        orders_page()
    elif page == "Yedek / Ayarlar":
        settings_page()

if __name__ == "__main__":
    main()
