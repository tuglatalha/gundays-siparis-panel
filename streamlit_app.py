import base64
import hashlib
import io
import os
import shutil
import sqlite3
from contextlib import closing
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import streamlit as st

APP_TITLE = "Günday's Home Sipariş Takip"
APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "gundays_home_siparis.db"

STATUSES = [
    "Sipariş Alındı",
    "Üretimde",
    "Hazır",
    "Sevkiyat Bekliyor",
    "Gönderildi",
    "Teslim Edildi",
    "İptal Edildi",
]
PAYMENT_STATUSES = ["Bekliyor", "Kısmi Ödendi", "Ödendi", "Vadeli", "İptal"]


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def money(value) -> str:
    try:
        value = float(value or 0)
    except Exception:
        value = 0.0
    formatted = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{formatted} TL"


def today_str() -> str:
    return date.today().isoformat()


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def db_connect():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def run_sql(sql: str, params=(), fetch: bool = False):
    with closing(db_connect()) as conn:
        cur = conn.execute(sql, params)
        rows = cur.fetchall() if fetch else None
        conn.commit()
        return rows


def df_query(sql: str, params=()) -> pd.DataFrame:
    with closing(db_connect()) as conn:
        return pd.read_sql_query(sql, conn, params=params)


def init_db():
    with closing(db_connect()) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'Admin',
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS firms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                firm_name TEXT NOT NULL,
                branch TEXT DEFAULT '',
                contact_name TEXT DEFAULT '',
                phone TEXT DEFAULT '',
                address TEXT DEFAULT '',
                tax_no TEXT DEFAULT '',
                tax_office TEXT DEFAULT '',
                note TEXT DEFAULT '',
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_name TEXT NOT NULL,
                model TEXT DEFAULT '',
                color TEXT DEFAULT '',
                category TEXT DEFAULT '',
                unit_price REAL NOT NULL DEFAULT 0,
                stock INTEGER NOT NULL DEFAULT 0,
                note TEXT DEFAULT '',
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_no TEXT UNIQUE NOT NULL,
                firm_id INTEGER,
                firm_name_snapshot TEXT DEFAULT '',
                branch_snapshot TEXT DEFAULT '',
                order_date TEXT NOT NULL,
                delivery_date TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'Sipariş Alındı',
                payment_status TEXT NOT NULL DEFAULT 'Bekliyor',
                shipping_note TEXT DEFAULT '',
                general_note TEXT DEFAULT '',
                created_by TEXT DEFAULT 'admin',
                total_amount REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY(firm_id) REFERENCES firms(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                product_id INTEGER,
                product_name_snapshot TEXT NOT NULL,
                model_snapshot TEXT DEFAULT '',
                color_snapshot TEXT DEFAULT '',
                quantity INTEGER NOT NULL DEFAULT 1,
                unit_price REAL NOT NULL DEFAULT 0,
                line_total REAL NOT NULL DEFAULT 0,
                note TEXT DEFAULT '',
                FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE,
                FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                payment_date TEXT NOT NULL,
                amount REAL NOT NULL DEFAULT 0,
                method TEXT DEFAULT '',
                note TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE
            );
            """
        )
        exists = conn.execute("SELECT COUNT(*) AS c FROM users WHERE username='admin'").fetchone()["c"]
        if not exists:
            conn.execute(
                "INSERT INTO users (username, password_hash, role, active, created_at) VALUES (?, ?, ?, ?, ?)",
                ("admin", hash_password("admin123"), "Admin", 1, now_str()),
            )
        conn.commit()


def auth_user(username: str, password: str):
    rows = run_sql(
        "SELECT * FROM users WHERE username=? AND password_hash=? AND active=1",
        (username.strip(), hash_password(password)),
        fetch=True,
    )
    return dict(rows[0]) if rows else None


def update_password(username: str, current: str, new: str) -> bool:
    user = auth_user(username, current)
    if not user:
        return False
    run_sql("UPDATE users SET password_hash=? WHERE username=?", (hash_password(new), username))
    return True


def next_order_no() -> str:
    year = datetime.now().year
    prefix = f"GH-{year}-"
    rows = run_sql("SELECT order_no FROM orders WHERE order_no LIKE ? ORDER BY order_no DESC LIMIT 1", (f"{prefix}%",), fetch=True)
    if not rows:
        return f"{prefix}0001"
    last = rows[0]["order_no"]
    try:
        number = int(last.split("-")[-1]) + 1
    except Exception:
        number = 1
    return f"{prefix}{number:04d}"


def firm_label(row) -> str:
    branch = (row.get("branch") or "").strip()
    return f"{row['firm_name']} / {branch}" if branch else row["firm_name"]


def product_label(row) -> str:
    parts = [row.get("product_name", "")]
    if row.get("model"):
        parts.append(row["model"])
    if row.get("color"):
        parts.append(row["color"])
    return " - ".join([p for p in parts if p])


def read_firms(active_only=False) -> pd.DataFrame:
    sql = "SELECT * FROM firms"
    if active_only:
        sql += " WHERE active=1"
    sql += " ORDER BY firm_name, branch, id"
    return df_query(sql)


def read_products(active_only=False) -> pd.DataFrame:
    sql = "SELECT * FROM products"
    if active_only:
        sql += " WHERE active=1"
    sql += " ORDER BY product_name, model, color, id"
    return df_query(sql)


def read_orders() -> pd.DataFrame:
    return df_query(
        """
        SELECT o.id, o.order_no, o.firm_name_snapshot AS firm_name, o.branch_snapshot AS branch,
               o.order_date, o.delivery_date, o.status, o.payment_status, o.total_amount,
               IFNULL((SELECT SUM(amount) FROM payments p WHERE p.order_id=o.id), 0) AS paid_amount,
               o.shipping_note, o.general_note, o.created_by, o.created_at
        FROM orders o
        ORDER BY o.id DESC
        """
    )


def read_order_items(order_id: int) -> pd.DataFrame:
    return df_query(
        """
        SELECT product_name_snapshot AS product_name, model_snapshot AS model, color_snapshot AS color,
               quantity, unit_price, line_total, note
        FROM order_items
        WHERE order_id=?
        ORDER BY id
        """,
        (order_id,),
    )


def read_payments() -> pd.DataFrame:
    return df_query(
        """
        SELECT p.id, o.order_no, o.firm_name_snapshot AS firm_name, p.payment_date, p.amount, p.method, p.note, p.created_at
        FROM payments p
        JOIN orders o ON o.id=p.order_id
        ORDER BY p.id DESC
        """
    )


def create_order(firm_id: int, order_date: str, delivery_date: str, status: str, payment_status: str,
                 shipping_note: str, general_note: str, created_by: str, cart: list[dict]):
    if not cart:
        raise ValueError("Siparişe en az bir ürün kalemi eklemelisin.")
    rows = run_sql("SELECT * FROM firms WHERE id=?", (firm_id,), fetch=True)
    if not rows:
        raise ValueError("Firma bulunamadı.")
    firm = dict(rows[0])
    total = sum(float(x["line_total"]) for x in cart)
    order_no = next_order_no()
    with closing(db_connect()) as conn:
        cur = conn.execute(
            """
            INSERT INTO orders (order_no, firm_id, firm_name_snapshot, branch_snapshot, order_date, delivery_date,
                                status, payment_status, shipping_note, general_note, created_by, total_amount, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order_no, firm_id, firm["firm_name"], firm["branch"], order_date, delivery_date,
                status, payment_status, shipping_note, general_note, created_by, total, now_str()
            ),
        )
        order_id = cur.lastrowid
        for item in cart:
            conn.execute(
                """
                INSERT INTO order_items (order_id, product_id, product_name_snapshot, model_snapshot, color_snapshot,
                                         quantity, unit_price, line_total, note)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order_id, item.get("product_id"), item.get("product_name", ""), item.get("model", ""),
                    item.get("color", ""), int(item.get("quantity", 1)), float(item.get("unit_price", 0)),
                    float(item.get("line_total", 0)), item.get("note", "")
                ),
            )
            if item.get("product_id"):
                conn.execute("UPDATE products SET stock = MAX(stock - ?, 0) WHERE id=?", (int(item.get("quantity", 1)), item.get("product_id")))
        conn.commit()
    return order_no


def delete_order(order_id: int):
    run_sql("DELETE FROM orders WHERE id=?", (order_id,))


def firm_used(firm_id: int) -> bool:
    rows = run_sql("SELECT COUNT(*) AS c FROM orders WHERE firm_id=?", (firm_id,), fetch=True)
    return rows[0]["c"] > 0


def product_used(product_id: int) -> bool:
    rows = run_sql("SELECT COUNT(*) AS c FROM order_items WHERE product_id=?", (product_id,), fetch=True)
    return rows[0]["c"] > 0


def backup_excel_bytes() -> bytes:
    output = io.BytesIO()
    sheets = {
        "Firmalar": read_firms(False),
        "Urunler": read_products(False),
        "Siparisler": read_orders(),
        "Odemeler": read_payments(),
    }
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for name, df in sheets.items():
            df.to_excel(writer, index=False, sheet_name=name)
        # order items separately
        items = df_query(
            """
            SELECT o.order_no, oi.product_name_snapshot AS product_name, oi.model_snapshot AS model, oi.color_snapshot AS color,
                   oi.quantity, oi.unit_price, oi.line_total, oi.note
            FROM order_items oi
            JOIN orders o ON o.id=oi.order_id
            ORDER BY o.id DESC, oi.id
            """
        )
        items.to_excel(writer, index=False, sheet_name="Siparis_Kalemleri")
    return output.getvalue()


def css():
    st.markdown(
        """
        <style>
        .stApp {
            background: radial-gradient(circle at top left, #1b130b 0%, #07111f 30%, #05070d 100%) !important;
            color: #f8fafc !important;
        }
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #0c1424 0%, #070b13 100%) !important;
            border-right: 1px solid rgba(212, 175, 55, .24);
        }
        h1, h2, h3, h4, label, p, span, div { color: #f8fafc; }
        .gh-subtitle { color:#aab3c5; margin-top:-.6rem; margin-bottom:1.2rem; }
        .gh-card {
            border: 1px solid rgba(212,175,55,.45);
            background: linear-gradient(145deg, rgba(15,23,42,.95), rgba(5,9,17,.98));
            border-radius: 20px;
            padding: 24px;
            box-shadow: 0 18px 50px rgba(0,0,0,.35);
            min-height: 132px;
        }
        .gh-card-title { color: #f4d67a; font-size:.9rem; font-weight:800; }
        .gh-card-value { color:#ffffff; font-size:2.15rem; font-weight:900; margin-top:.55rem; }
        .gh-card-note { color:#aab3c5; font-size:.86rem; margin-top:.3rem; }
        div[data-testid="stMetricValue"] { color:#fff !important; }
        .stButton>button, .stDownloadButton>button {
            border: 1px solid rgba(212,175,55,.68) !important;
            background: linear-gradient(90deg, rgba(60,45,22,.96), rgba(10,17,31,.98)) !important;
            color: #fff !important;
            border-radius: 12px !important;
            font-weight: 700 !important;
        }
        .stTextInput input, .stTextArea textarea, .stNumberInput input, .stDateInput input, .stSelectbox div[data-baseweb="select"] > div {
            background: #262833 !important;
            color: #fff !important;
            border-color: rgba(255,255,255,.12) !important;
        }
        .stDataFrame { border-radius: 14px; overflow:hidden; }
        [data-testid="stAlert"] { border-radius: 12px; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def card(title: str, value: str, note: str):
    st.markdown(
        f"""
        <div class="gh-card">
          <div class="gh-card-title">{title}</div>
          <div class="gh-card-value">{value}</div>
          <div class="gh-card-note">{note}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def login_page():
    st.markdown(f"# {APP_TITLE}")
    st.markdown('<div class="gh-subtitle">Sipariş, firma, ürün, ödeme ve raporları tek panelden yönetin.</div>', unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 1.25, 1])
    with col2:
        st.markdown("## Yönetim Paneli Girişi")
        with st.form("login_form"):
            username = st.text_input("Kullanıcı adı")
            password = st.text_input("Şifre", type="password")
            submit = st.form_submit_button("Giriş yap", use_container_width=True)
            if submit:
                user = auth_user(username, password)
                if user:
                    st.session_state["logged_in"] = True
                    st.session_state["user"] = user
                    st.rerun()
                else:
                    st.error("Kullanıcı adı veya şifre hatalı.")
        st.info("İlk kurulum bilgisi: admin / admin123. Yayına almadan önce şifreyi değiştirin.")


def sidebar():
    with st.sidebar:
        st.markdown("### Günday's Home")
        user = st.session_state.get("user", {"username": "admin", "role": "Admin"})
        st.caption(f"Kullanıcı: {user['username']} / {user['role']}")
        pages = ["Dashboard", "Yeni Sipariş", "Siparişler", "Firmalar", "Ürünler", "Ödemeler", "Raporlar", "Yedek / Ayarlar"]
        page = st.radio("", pages, label_visibility="collapsed")
        st.divider()
        if st.button("Çıkış yap", use_container_width=True):
            st.session_state.clear()
            st.rerun()
    return page


def dashboard_page():
    st.title("Dashboard")
    st.markdown('<div class="gh-subtitle">Günday\'s Home genel sipariş özeti</div>', unsafe_allow_html=True)
    orders = read_orders()
    total_orders = len(orders)
    active_orders = len(orders[~orders["status"].isin(["Teslim Edildi", "İptal Edildi"])]) if not orders.empty else 0
    ciro = float(orders.loc[orders["status"] != "İptal Edildi", "total_amount"].sum()) if not orders.empty else 0
    outstanding = float((orders["total_amount"] - orders["paid_amount"]).clip(lower=0).sum()) if not orders.empty else 0
    c1, c2, c3, c4 = st.columns(4)
    with c1: card("Toplam Sipariş", str(total_orders), "Tüm kayıtlar")
    with c2: card("Aktif Sipariş", str(active_orders), "Teslim/iptal hariç")
    with c3: card("Ciro", money(ciro), "İptal hariç sipariş toplamı")
    with c4: card("Ödeme Bekleyen", money(outstanding), "Tahsilat farkı")
    st.divider()
    col1, col2 = st.columns([1.25, 1])
    with col1:
        st.subheader("Son Siparişler")
        if orders.empty:
            st.info("Henüz sipariş yok.")
        else:
            view = orders[["order_no", "firm_name", "branch", "order_date", "status", "payment_status", "total_amount"]].head(10).copy()
            view["total_amount"] = view["total_amount"].apply(money)
            st.dataframe(view, use_container_width=True, hide_index=True, height=330)
    with col2:
        st.subheader("Durum Dağılımı")
        if orders.empty:
            st.info("Grafik için veri yok.")
        else:
            chart = orders.groupby("status", dropna=False)["id"].count().reset_index(name="adet")
            st.bar_chart(chart, x="status", y="adet", height=330)
    st.subheader("Hızlı Uyarılar")
    if orders.empty:
        st.success("Şu an kritik uyarı yok.")
    else:
        warn = orders[(orders["status"].isin(["Sipariş Alındı", "Üretimde", "Hazır", "Sevkiyat Bekliyor"]))]
        overdue = warn[(warn["delivery_date"].fillna("") < today_str()) & (warn["delivery_date"].fillna("") != "")]
        if overdue.empty:
            st.success("Şu an kritik uyarı yok.")
        else:
            st.warning(f"Teslim tarihi geçmiş {len(overdue)} açık sipariş var.")


def firms_page():
    st.title("Firmalar")
    st.caption("Bayi, müşteri ve şube kartlarını yönetin")
    with st.expander("+ Yeni firma / şube ekle", expanded=True):
        with st.form("firm_add"):
            c1, c2, c3 = st.columns([1, 1, 1])
            with c1:
                firm_name = st.text_input("Firma adı *")
                branch = st.text_input("Şube")
                contact_name = st.text_input("Yetkili kişi")
            with c2:
                phone = st.text_input("Telefon")
                tax_no = st.text_input("Vergi No / VKN")
                tax_office = st.text_input("Vergi Dairesi")
            with c3:
                address = st.text_area("Adres", height=92)
                note = st.text_area("Not", height=92)
            if st.form_submit_button("Firmayı kaydet", use_container_width=True):
                if not firm_name.strip():
                    st.error("Firma adı zorunlu.")
                else:
                    run_sql(
                        """
                        INSERT INTO firms (firm_name, branch, contact_name, phone, address, tax_no, tax_office, note, active, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                        """,
                        (firm_name.strip(), branch.strip(), contact_name.strip(), phone.strip(), address.strip(), tax_no.strip(), tax_office.strip(), note.strip(), now_str()),
                    )
                    st.success("Firma kaydedildi.")
                    st.rerun()
    firms = read_firms(False)
    st.subheader("Kayıtlı Firmalar")
    if firms.empty:
        st.info("Henüz firma yok.")
    else:
        view = firms.copy()
        view["active"] = view["active"].map({1: "Aktif", 0: "Pasif"})
        view = view.rename(columns={"id":"ID", "firm_name":"Firma", "branch":"Şube", "contact_name":"Yetkili", "phone":"Telefon", "tax_no":"Vergi No", "tax_office":"Vergi Dairesi", "note":"Not", "active":"Durum", "created_at":"Kayıt Tarihi"})
        st.dataframe(view[["ID","Firma","Şube","Yetkili","Telefon","Adres","Vergi No","Vergi Dairesi","Durum","Kayıt Tarihi"]], use_container_width=True, hide_index=True, height=330)
    st.subheader("Firma Düzelt / Sil")
    if firms.empty:
        return
    options = {int(r.id): f"F-{int(r.id):04d} - {r.firm_name} / {r.branch or '-'}" for r in firms.itertuples(index=False)}
    selected = st.selectbox("Firma seç", list(options.keys()), format_func=lambda x: options[x])
    row = firms[firms["id"] == selected].iloc[0]
    with st.form("firm_edit"):
        c1, c2, c3 = st.columns(3)
        with c1:
            ef = st.text_input("Firma adı", value=str(row["firm_name"] or ""))
            eb = st.text_input("Şube", value=str(row["branch"] or ""))
            ec = st.text_input("Yetkili kişi", value=str(row["contact_name"] or ""))
        with c2:
            ep = st.text_input("Telefon", value=str(row["phone"] or ""))
            et = st.text_input("Vergi No / VKN", value=str(row["tax_no"] or ""))
            eto = st.text_input("Vergi Dairesi", value=str(row["tax_office"] or ""))
        with c3:
            ea = st.text_area("Adres", value=str(row["address"] or ""), height=92)
            en = st.text_area("Not", value=str(row["note"] or ""), height=92)
            eact = st.selectbox("Durum", [1, 0], index=0 if int(row["active"]) == 1 else 1, format_func=lambda x: "Aktif" if x == 1 else "Pasif")
        save = st.form_submit_button("Firma bilgisini güncelle", use_container_width=True)
        if save:
            if not ef.strip():
                st.error("Firma adı boş olamaz.")
            else:
                run_sql(
                    """UPDATE firms SET firm_name=?, branch=?, contact_name=?, phone=?, address=?, tax_no=?, tax_office=?, note=?, active=? WHERE id=?""",
                    (ef.strip(), eb.strip(), ec.strip(), ep.strip(), ea.strip(), et.strip(), eto.strip(), en.strip(), int(eact), int(selected)),
                )
                st.success("Firma güncellendi.")
                st.rerun()
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Firmayı pasife al", use_container_width=True):
            run_sql("UPDATE firms SET active=0 WHERE id=?", (int(selected),))
            st.success("Firma pasife alındı.")
            st.rerun()
    with c2:
        if st.button("Kalıcı sil", use_container_width=True):
            if firm_used(int(selected)):
                st.warning("Bu firma geçmiş siparişlerde kullanılmış. Raporlar bozulmasın diye pasife alıyorum.")
                run_sql("UPDATE firms SET active=0 WHERE id=?", (int(selected),))
            else:
                run_sql("DELETE FROM firms WHERE id=?", (int(selected),))
                st.success("Firma silindi.")
            st.rerun()


def products_page():
    st.title("Ürünler")
    st.caption("Ürün kartları, renkler, fiyatlar ve stok bilgisi")
    with st.expander("+ Yeni ürün ekle", expanded=True):
        with st.form("product_add"):
            c1, c2, c3 = st.columns(3)
            with c1:
                name = st.text_input("Ürün adı *")
                model = st.text_input("Model")
                category = st.text_input("Kategori")
            with c2:
                color = st.text_input("Renk")
                price = st.number_input("Birim fiyat", min_value=0.0, step=50.0, value=0.0)
            with c3:
                stock = st.number_input("Stok", min_value=0, step=1, value=0)
                note = st.text_area("Not", height=92)
            if st.form_submit_button("Ürünü kaydet", use_container_width=True):
                if not name.strip():
                    st.error("Ürün adı zorunlu.")
                else:
                    run_sql(
                        """INSERT INTO products (product_name, model, color, category, unit_price, stock, note, active, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)""",
                        (name.strip(), model.strip(), color.strip(), category.strip(), float(price), int(stock), note.strip(), now_str()),
                    )
                    st.success("Ürün kaydedildi.")
                    st.rerun()
    products = read_products(False)
    st.subheader("Kayıtlı Ürünler")
    if products.empty:
        st.info("Henüz ürün yok.")
    else:
        view = products.copy()
        view["active"] = view["active"].map({1: "Aktif", 0: "Pasif"})
        view["unit_price"] = view["unit_price"].apply(money)
        view = view.rename(columns={"id":"ID", "product_name":"Ürün", "model":"Model", "color":"Renk", "category":"Kategori", "unit_price":"Birim Fiyat", "stock":"Stok", "note":"Not", "active":"Durum", "created_at":"Kayıt Tarihi"})
        st.dataframe(view[["ID","Ürün","Model","Renk","Kategori","Birim Fiyat","Stok","Durum","Not","Kayıt Tarihi"]], use_container_width=True, hide_index=True, height=330)
    st.subheader("Ürün Düzelt / Sil")
    if products.empty:
        return
    options = {int(r.id): f"U-{int(r.id):04d} - {product_label({'product_name': r.product_name, 'model': r.model, 'color': r.color})}" for r in products.itertuples(index=False)}
    selected = st.selectbox("Ürün seç", list(options.keys()), format_func=lambda x: options[x])
    row = products[products["id"] == selected].iloc[0]
    with st.form("product_edit"):
        c1, c2, c3 = st.columns(3)
        with c1:
            en = st.text_input("Ürün adı", value=str(row["product_name"] or ""))
            em = st.text_input("Model", value=str(row["model"] or ""))
            ecat = st.text_input("Kategori", value=str(row["category"] or ""))
        with c2:
            eco = st.text_input("Renk", value=str(row["color"] or ""))
            eprice = st.number_input("Birim fiyat", min_value=0.0, step=50.0, value=float(row["unit_price"] or 0))
        with c3:
            estock = st.number_input("Stok", min_value=0, step=1, value=int(row["stock"] or 0))
            enote = st.text_area("Not", value=str(row["note"] or ""), height=92)
            eact = st.selectbox("Durum", [1, 0], index=0 if int(row["active"]) == 1 else 1, format_func=lambda x: "Aktif" if x == 1 else "Pasif")
        if st.form_submit_button("Ürün bilgisini güncelle", use_container_width=True):
            if not en.strip():
                st.error("Ürün adı boş olamaz.")
            else:
                run_sql(
                    """UPDATE products SET product_name=?, model=?, color=?, category=?, unit_price=?, stock=?, note=?, active=? WHERE id=?""",
                    (en.strip(), em.strip(), eco.strip(), ecat.strip(), float(eprice), int(estock), enote.strip(), int(eact), int(selected)),
                )
                st.success("Ürün güncellendi.")
                st.rerun()
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Ürünü pasife al", use_container_width=True):
            run_sql("UPDATE products SET active=0 WHERE id=?", (int(selected),))
            st.success("Ürün pasife alındı.")
            st.rerun()
    with c2:
        if st.button("Kalıcı sil", use_container_width=True):
            if product_used(int(selected)):
                st.warning("Bu ürün geçmiş siparişlerde kullanılmış. Raporlar bozulmasın diye pasife alıyorum.")
                run_sql("UPDATE products SET active=0 WHERE id=?", (int(selected),))
            else:
                run_sql("DELETE FROM products WHERE id=?", (int(selected),))
                st.success("Ürün silindi.")
            st.rerun()


def new_order_page():
    st.title("Yeni Sipariş")
    st.caption("Firma seçin, ürünleri ekleyin, siparişi kaydedin")
    firms = read_firms(True)
    products = read_products(True)
    if "cart" not in st.session_state:
        st.session_state["cart"] = []
    if firms.empty:
        st.warning("Sipariş oluşturmak için önce Firmalar bölümünden en az bir firma eklemelisin.")
        return
    if products.empty:
        st.warning("Sipariş oluşturmak için önce Ürünler bölümünden en az bir ürün eklemelisin.")
        return
    firm_options = {int(r.id): firm_label({"firm_name": r.firm_name, "branch": r.branch}) for r in firms.itertuples(index=False)}
    product_options = {int(r.id): product_label({"product_name": r.product_name, "model": r.model, "color": r.color}) for r in products.itertuples(index=False)}
    st.subheader("Sipariş Bilgileri")
    c1, c2, c3 = st.columns(3)
    with c1:
        firm_id = st.selectbox("Firma / Şube", list(firm_options.keys()), format_func=lambda x: firm_options[x])
        order_date_val = st.date_input("Sipariş tarihi", value=date.today())
    with c2:
        delivery_date_val = st.date_input("Tahmini teslim tarihi", value=date.today())
        status = st.selectbox("Sipariş durumu", STATUSES, index=0)
    with c3:
        payment_status = st.selectbox("Ödeme durumu", PAYMENT_STATUSES, index=0)
        created_by = st.text_input("Oluşturan", value=st.session_state.get("user", {}).get("username", "admin"))
    shipping_note = st.text_area("Sevkiyat notu", height=80)
    general_note = st.text_area("Genel not", height=80)
    st.subheader("Ürün Kalemi Ekle")
    c1, c2, c3, c4 = st.columns([2, .7, .9, .8])
    with c1:
        product_id = st.selectbox("Ürün", list(product_options.keys()), format_func=lambda x: product_options[x])
    product_row = products[products["id"] == product_id].iloc[0]
    with c2:
        quantity = st.number_input("Adet", min_value=1, step=1, value=1)
    with c3:
        unit_price = st.number_input("Birim fiyat", min_value=0.0, step=50.0, value=float(product_row["unit_price"] or 0))
    line_total = int(quantity) * float(unit_price)
    with c4:
        st.markdown("**Satır toplamı**")
        st.markdown(f"### {money(line_total)}")
    item_note = st.text_input("Kalem notu")
    if st.button("+ Kalemi sepete ekle", use_container_width=True):
        st.session_state["cart"].append({
            "product_id": int(product_id),
            "product_name": str(product_row["product_name"]),
            "model": str(product_row["model"] or ""),
            "color": str(product_row["color"] or ""),
            "quantity": int(quantity),
            "unit_price": float(unit_price),
            "line_total": float(line_total),
            "note": item_note.strip(),
        })
        st.success("Kalem sepete eklendi.")
        st.rerun()
    st.subheader("Sipariş Sepeti")
    if not st.session_state["cart"]:
        st.info("Sepette ürün yok.")
    else:
        cart_df = pd.DataFrame(st.session_state["cart"])
        view = cart_df[["product_name", "model", "color", "quantity", "unit_price", "line_total", "note"]].copy()
        view["unit_price"] = view["unit_price"].apply(money)
        view["line_total"] = view["line_total"].apply(money)
        st.dataframe(view, use_container_width=True, hide_index=True, height=260)
        st.markdown(f"### Sipariş Toplamı: {money(cart_df['line_total'].sum())}")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Sepeti temizle", use_container_width=True):
                st.session_state["cart"] = []
                st.rerun()
        with c2:
            if st.button("Siparişi kaydet", use_container_width=True):
                try:
                    no = create_order(
                        int(firm_id), order_date_val.isoformat(), delivery_date_val.isoformat(), status, payment_status,
                        shipping_note.strip(), general_note.strip(), created_by.strip(), st.session_state["cart"]
                    )
                    st.session_state["cart"] = []
                    st.success(f"Sipariş kaydedildi: {no}")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Sipariş kaydedilemedi: {exc}")


def orders_page():
    st.title("Siparişler")
    st.caption("Siparişleri filtreleyin, durum ve ödeme bilgisini güncelleyin")
    orders = read_orders()
    if orders.empty:
        st.info("Henüz sipariş yok.")
        return
    c1, c2, c3 = st.columns(3)
    with c1:
        search = st.text_input("Firma ara")
    with c2:
        status_filter = st.selectbox("Durum filtresi", ["Tümü"] + STATUSES)
    with c3:
        pay_filter = st.selectbox("Ödeme filtresi", ["Tümü"] + PAYMENT_STATUSES)
    filt = orders.copy()
    if search.strip():
        filt = filt[filt["firm_name"].str.contains(search.strip(), case=False, na=False)]
    if status_filter != "Tümü":
        filt = filt[filt["status"] == status_filter]
    if pay_filter != "Tümü":
        filt = filt[filt["payment_status"] == pay_filter]
    view = filt[["id", "order_no", "firm_name", "branch", "order_date", "delivery_date", "status", "payment_status", "total_amount", "paid_amount", "shipping_note"]].copy()
    view["total_amount"] = view["total_amount"].apply(money)
    view["paid_amount"] = view["paid_amount"].apply(money)
    st.dataframe(view, use_container_width=True, hide_index=True, height=360)
    st.subheader("Sipariş Detayı / Güncelleme")
    options = {int(r.id): f"{r.order_no} - {r.firm_name} / {r.branch or '-'} - {money(r.total_amount)}" for r in filt.itertuples(index=False)}
    if not options:
        st.warning("Filtreye uygun sipariş yok.")
        return
    selected = st.selectbox("Sipariş seç", list(options.keys()), format_func=lambda x: options[x])
    row = orders[orders["id"] == selected].iloc[0]
    items = read_order_items(int(selected))
    st.dataframe(items.assign(unit_price=items["unit_price"].apply(money), line_total=items["line_total"].apply(money)), use_container_width=True, hide_index=True, height=240)
    with st.form("order_update"):
        c1, c2, c3 = st.columns(3)
        with c1:
            ns = st.selectbox("Yeni durum", STATUSES, index=STATUSES.index(row["status"]) if row["status"] in STATUSES else 0)
        with c2:
            npay = st.selectbox("Yeni ödeme durumu", PAYMENT_STATUSES, index=PAYMENT_STATUSES.index(row["payment_status"]) if row["payment_status"] in PAYMENT_STATUSES else 0)
        with c3:
            ndelivery = st.date_input("Teslim tarihi", value=pd.to_datetime(row["delivery_date"] or today_str()).date())
        nship = st.text_area("Sevkiyat notu", value=str(row["shipping_note"] or ""), height=80)
        ngen = st.text_area("Genel not", value=str(row["general_note"] or ""), height=80)
        if st.form_submit_button("Siparişi güncelle", use_container_width=True):
            run_sql("UPDATE orders SET status=?, payment_status=?, delivery_date=?, shipping_note=?, general_note=? WHERE id=?", (ns, npay, ndelivery.isoformat(), nship.strip(), ngen.strip(), int(selected)))
            st.success("Sipariş güncellendi.")
            st.rerun()
    if st.button("Siparişi kalıcı sil", use_container_width=True):
        delete_order(int(selected))
        st.success("Sipariş, kalemleri ve ödemeleriyle birlikte silindi.")
        st.rerun()


def payments_page():
    st.title("Ödemeler")
    orders = read_orders()
    if orders.empty:
        st.info("Ödeme eklemek için önce sipariş oluşturmalısın.")
        return
    options = {int(r.id): f"{r.order_no} - {r.firm_name} - Kalan: {money(max(float(r.total_amount)-float(r.paid_amount),0))}" for r in orders.itertuples(index=False)}
    with st.form("payment_add"):
        order_id = st.selectbox("Sipariş", list(options.keys()), format_func=lambda x: options[x])
        c1, c2, c3 = st.columns(3)
        with c1:
            pdate = st.date_input("Ödeme tarihi", value=date.today())
        with c2:
            amount = st.number_input("Tutar", min_value=0.0, step=100.0, value=0.0)
        with c3:
            method = st.selectbox("Yöntem", ["Nakit", "Havale/EFT", "Kredi Kartı", "Çek/Senet", "Diğer"])
        note = st.text_input("Not")
        if st.form_submit_button("Ödemeyi kaydet", use_container_width=True):
            if amount <= 0:
                st.error("Ödeme tutarı 0'dan büyük olmalı.")
            else:
                run_sql("INSERT INTO payments (order_id, payment_date, amount, method, note, created_at) VALUES (?, ?, ?, ?, ?, ?)", (int(order_id), pdate.isoformat(), float(amount), method, note.strip(), now_str()))
                # status auto update
                updated = read_orders()
                r = updated[updated["id"] == int(order_id)].iloc[0]
                if float(r["paid_amount"]) >= float(r["total_amount"]):
                    run_sql("UPDATE orders SET payment_status='Ödendi' WHERE id=?", (int(order_id),))
                elif float(r["paid_amount"]) > 0:
                    run_sql("UPDATE orders SET payment_status='Kısmi Ödendi' WHERE id=?", (int(order_id),))
                st.success("Ödeme kaydedildi.")
                st.rerun()
    payments = read_payments()
    st.subheader("Ödeme Kayıtları")
    if payments.empty:
        st.info("Henüz ödeme yok.")
    else:
        view = payments.copy()
        view["amount"] = view["amount"].apply(money)
        st.dataframe(view, use_container_width=True, hide_index=True, height=330)
        opts = {int(r.id): f"{r.order_no} - {money(r.amount)} - {r.payment_date}" for r in payments.itertuples(index=False)}
        sel = st.selectbox("Silinecek ödeme kaydı", list(opts.keys()), format_func=lambda x: opts[x])
        if st.button("Seçili ödemeyi sil", use_container_width=True):
            run_sql("DELETE FROM payments WHERE id=?", (int(sel),))
            st.success("Ödeme silindi.")
            st.rerun()


def reports_page():
    st.title("Raporlar")
    orders = read_orders()
    if orders.empty:
        st.info("Rapor için henüz sipariş yok.")
        return
    valid_orders = orders[orders["status"] != "İptal Edildi"].copy()
    c1, c2, c3 = st.columns(3)
    with c1: card("Toplam Ciro", money(valid_orders["total_amount"].sum()), "İptal hariç")
    with c2: card("Toplam Tahsilat", money(valid_orders["paid_amount"].sum()), "Kayıtlı ödemeler")
    with c3: card("Açık Bakiye", money((valid_orders["total_amount"]-valid_orders["paid_amount"]).clip(lower=0).sum()), "Tahsilat farkı")
    st.subheader("Firma Bazlı Satış")
    firm_report = valid_orders.groupby("firm_name", dropna=False).agg(siparis_adedi=("id", "count"), toplam_ciro=("total_amount", "sum")).reset_index()
    if not firm_report.empty:
        view = firm_report.copy(); view["toplam_ciro"] = view["toplam_ciro"].apply(money)
        st.dataframe(view, use_container_width=True, hide_index=True, height=280)
        st.bar_chart(firm_report, x="firm_name", y="toplam_ciro", height=320)
    st.subheader("Ürün Bazlı Satış")
    items = df_query(
        """
        SELECT oi.product_name_snapshot AS product_name, SUM(oi.quantity) AS toplam_adet, SUM(oi.line_total) AS toplam_tutar
        FROM order_items oi
        JOIN orders o ON o.id=oi.order_id
        WHERE o.status != 'İptal Edildi'
        GROUP BY oi.product_name_snapshot
        ORDER BY toplam_tutar DESC
        """
    )
    if items.empty:
        st.info("Ürün raporu için kalem yok.")
    else:
        view = items.copy(); view["toplam_tutar"] = view["toplam_tutar"].apply(money)
        st.dataframe(view, use_container_width=True, hide_index=True, height=280)
        st.bar_chart(items, x="product_name", y="toplam_adet", height=320)
    st.subheader("Excel Dışa Aktar")
    st.download_button("Tüm raporları Excel indir", data=backup_excel_bytes(), file_name=f"gundays_home_rapor_{today_str()}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)


def settings_page():
    st.title("Yedek / Ayarlar")
    st.caption("Yedekleme, geri yükleme ve şifre değişimi")
    st.subheader("Yedek İndir")
    c1, c2 = st.columns(2)
    with c1:
        if DB_PATH.exists():
            st.download_button("SQLite veritabanı yedeğini indir", data=DB_PATH.read_bytes(), file_name=f"gundays_home_db_{today_str()}.db", mime="application/octet-stream", use_container_width=True)
    with c2:
        st.download_button("Excel yedeği indir", data=backup_excel_bytes(), file_name=f"gundays_home_yedek_{today_str()}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
    st.subheader("Veritabanı Geri Yükle")
    st.warning("Geri yükleme mevcut veritabanını değiştirir. Önce mevcut yedeği indirin.")
    upload = st.file_uploader(".db yedeği yükle", type=["db", "sqlite", "sqlite3"])
    if upload and st.button("Bu yedeği geri yükle", use_container_width=True):
        backup_path = DATA_DIR / f"before_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        if DB_PATH.exists():
            shutil.copy(DB_PATH, backup_path)
        DB_PATH.write_bytes(upload.getvalue())
        st.success("Yedek geri yüklendi. Uygulamayı yeniden başlatıyorum.")
        st.rerun()
    st.subheader("Şifre Değiştir")
    with st.form("password_change"):
        current = st.text_input("Mevcut şifre", type="password")
        new = st.text_input("Yeni şifre", type="password")
        new2 = st.text_input("Yeni şifre tekrar", type="password")
        if st.form_submit_button("Şifreyi değiştir", use_container_width=True):
            username = st.session_state.get("user", {}).get("username", "admin")
            if not new or len(new) < 6:
                st.error("Yeni şifre en az 6 karakter olmalı.")
            elif new != new2:
                st.error("Yeni şifreler eşleşmiyor.")
            elif update_password(username, current, new):
                st.success("Şifre değiştirildi.")
            else:
                st.error("Mevcut şifre hatalı.")


def main():
    st.set_page_config(page_title=APP_TITLE, page_icon="📦", layout="wide", initial_sidebar_state="expanded")
    css()
    init_db()
    if not st.session_state.get("logged_in"):
        login_page()
        return
    page = sidebar()
    if page == "Dashboard": dashboard_page()
    elif page == "Yeni Sipariş": new_order_page()
    elif page == "Siparişler": orders_page()
    elif page == "Firmalar": firms_page()
    elif page == "Ürünler": products_page()
    elif page == "Ödemeler": payments_page()
    elif page == "Raporlar": reports_page()
    elif page == "Yedek / Ayarlar": settings_page()


if __name__ == "__main__":
    main()
