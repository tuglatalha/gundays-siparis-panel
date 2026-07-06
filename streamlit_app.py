from __future__ import annotations

import json
import os
import sqlite3
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

APP_TITLE = "Günday's Home Sipariş Paneli"
DB_PATH = Path("gundays_home_orders.db")
ADMIN_DEFAULT = ("admin", "admin123")

ORDER_STATUSES = ["Sipariş Alındı", "Hazırlanıyor", "Üretimde", "Hazır", "Sevkiyat Bekliyor", "Gönderildi", "Teslim Edildi", "İptal"]
PAYMENT_METHODS = ["Nakit", "Kredi Kartı", "Havale/EFT", "Çek", "Senet", "Diğer"]
GAMER_COLORS = ["Siyah", "Antrasit", "Mavi", "Kırmızı", "Pembe", "Yeşil", "Turuncu", "Beyaz", "Sarı"]
FURNITURE_COLORS = ["Naturel", "Ceviz", "Lake Beyaz", "Siyah"]


def tr_norm(value: Any) -> str:
    text = str(value or "").strip()
    repl = str.maketrans({"ı": "i", "İ": "i", "ğ": "g", "Ğ": "g", "ü": "u", "Ü": "u", "ş": "s", "Ş": "s", "ö": "o", "Ö": "o", "ç": "c", "Ç": "c"})
    return text.translate(repl).lower()


def money(value: Any) -> str:
    try:
        amount = float(value or 0)
    except Exception:
        amount = 0.0
    return f"{amount:,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")


def today_iso() -> str:
    return date.today().isoformat()


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def q(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    with conn() as c:
        return [dict(r) for r in c.execute(sql, params).fetchall()]


def exec_sql(sql: str, params: tuple = ()) -> None:
    with conn() as c:
        c.execute(sql, params)
        c.commit()


def table_exists(name: str) -> bool:
    rows = q("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,))
    return bool(rows)


def columns(table: str) -> set[str]:
    with conn() as c:
        return {r[1] for r in c.execute(f"PRAGMA table_info({table})").fetchall()}


def add_col(table: str, col: str, spec: str) -> None:
    if col not in columns(table):
        exec_sql(f"ALTER TABLE {table} ADD COLUMN {col} {spec}")


def init_db() -> None:
    with conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role TEXT DEFAULT 'Admin',
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS firms (
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

            CREATE TABLE IF NOT EXISTS products (
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

            CREATE TABLE IF NOT EXISTS product_colors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                color TEXT NOT NULL,
                extra_price REAL DEFAULT 0,
                active INTEGER DEFAULT 1,
                FOREIGN KEY(product_id) REFERENCES products(id)
            );

            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_no TEXT UNIQUE NOT NULL,
                firm_id INTEGER NOT NULL,
                order_date TEXT,
                delivery_date TEXT,
                status TEXT DEFAULT 'Sipariş Alındı',
                note TEXT DEFAULT '',
                created_by TEXT DEFAULT 'admin',
                created_at TEXT,
                FOREIGN KEY(firm_id) REFERENCES firms(id)
            );

            CREATE TABLE IF NOT EXISTS order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                product_id INTEGER,
                product_name TEXT,
                color TEXT DEFAULT '',
                qty INTEGER DEFAULT 1,
                unit_base_price REAL DEFAULT 0,
                color_extra REAL DEFAULT 0,
                unit_price REAL DEFAULT 0,
                line_total REAL DEFAULT 0,
                note TEXT DEFAULT '',
                FOREIGN KEY(order_id) REFERENCES orders(id),
                FOREIGN KEY(product_id) REFERENCES products(id)
            );

            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                payment_date TEXT,
                amount REAL DEFAULT 0,
                method TEXT DEFAULT 'Nakit',
                maturity_months INTEGER DEFAULT 0,
                maturity_date TEXT DEFAULT '',
                note TEXT DEFAULT '',
                created_at TEXT,
                FOREIGN KEY(order_id) REFERENCES orders(id)
            );
            """
        )
        if not c.execute("SELECT 1 FROM users WHERE username=?", (ADMIN_DEFAULT[0],)).fetchone():
            c.execute("INSERT INTO users(username,password,role,created_at) VALUES(?,?,?,?)", (ADMIN_DEFAULT[0], ADMIN_DEFAULT[1], "Admin", now_iso()))
        c.commit()

    # Safety migrations for older DBs
    for table, defs in {
        "firms": {"active": "INTEGER DEFAULT 1", "created_at": "TEXT", "note": "TEXT DEFAULT ''"},
        "products": {"active": "INTEGER DEFAULT 1", "created_at": "TEXT", "note": "TEXT DEFAULT ''", "stock": "INTEGER DEFAULT 0"},
        "orders": {"note": "TEXT DEFAULT ''", "created_by": "TEXT DEFAULT 'admin'", "created_at": "TEXT"},
        "payments": {"maturity_months": "INTEGER DEFAULT 0", "maturity_date": "TEXT DEFAULT ''", "note": "TEXT DEFAULT ''", "created_at": "TEXT"},
    }.items():
        if table_exists(table):
            for col, spec in defs.items():
                add_col(table, col, spec)


def df(sql: str, params: tuple = ()) -> pd.DataFrame:
    with conn() as c:
        return pd.read_sql_query(sql, c, params=params)


def next_order_no() -> str:
    year = datetime.now().year
    rows = q("SELECT order_no FROM orders WHERE order_no LIKE ? ORDER BY id DESC LIMIT 1", (f"GH-{year}-%",))
    if not rows:
        return f"GH-{year}-0001"
    last = rows[0]["order_no"].split("-")[-1]
    try:
        n = int(last) + 1
    except Exception:
        n = 1
    return f"GH-{year}-{n:04d}"


def get_order_total(order_id: int) -> float:
    rows = q("SELECT COALESCE(SUM(line_total),0) total FROM order_items WHERE order_id=?", (order_id,))
    return float(rows[0]["total"] or 0)


def get_paid_total(order_id: int) -> float:
    rows = q("SELECT COALESCE(SUM(amount),0) total FROM payments WHERE order_id=?", (order_id,))
    return float(rows[0]["total"] or 0)


def payment_status(total: float, paid: float) -> str:
    if total <= 0:
        return "Tutar Yok"
    if paid <= 0:
        return "Bekliyor"
    if paid + 0.01 < total:
        return "Kısmi Ödendi"
    return "Ödendi"


def safe_show(data: pd.DataFrame, height: int = 320) -> None:
    if data is None or data.empty:
        st.info("Henüz kayıt yok.")
        return
    st.dataframe(data.fillna(""), use_container_width=True, hide_index=True, height=height)


def login() -> None:
    st.markdown("<div class='login-wrap'>", unsafe_allow_html=True)
    st.title(APP_TITLE)
    st.caption("Firma, ürün ve sipariş yönetimini tek panelden takip edin.")
    with st.form("login_form"):
        st.subheader("Yönetim Paneli Girişi")
        username = st.text_input("Kullanıcı adı")
        password = st.text_input("Şifre", type="password")
        ok = st.form_submit_button("Giriş yap", use_container_width=True)
    if ok:
        rows = q("SELECT * FROM users WHERE username=? AND password=?", (username.strip(), password.strip()))
        if rows:
            st.session_state.user = rows[0]["username"]
            st.session_state.role = rows[0].get("role", "Admin") if isinstance(rows[0], dict) else "Admin"
            st.rerun()
        st.error("Kullanıcı adı veya şifre hatalı.")
    st.info("İlk giriş: admin / admin123")
    st.markdown("</div>", unsafe_allow_html=True)


def menu() -> str:
    with st.sidebar:
        st.markdown("### Günday's Home")
        st.caption(f"Kullanıcı: {st.session_state.get('user','admin')}")
        pages = ["Dashboard", "Firmalar", "Ürünler", "Yeni Sipariş", "Siparişler", "Yedek / Ayarlar"]
        page = st.radio("", pages, label_visibility="collapsed")
        st.markdown("---")
        if st.button("Çıkış yap", use_container_width=True):
            st.session_state.clear()
            st.rerun()
    return page


def dashboard_page() -> None:
    st.title("Dashboard")
    st.caption("Siparişlerin genel özeti")

    orders = order_summary_df()
    active = orders[~orders["Durum"].isin(["Teslim Edildi", "İptal"])] if not orders.empty else orders
    total_orders = len(orders)
    active_orders = len(active)
    total_revenue = float(orders["Toplam"].sum()) if not orders.empty else 0.0
    remaining = float(orders["Kalan"].sum()) if not orders.empty else 0.0

    c1, c2, c3, c4 = st.columns(4)
    metric_card(c1, "Toplam Sipariş", str(total_orders), "Tüm kayıtlar")
    metric_card(c2, "Aktif Sipariş", str(active_orders), "Teslim/iptal hariç")
    metric_card(c3, "Ciro", money(total_revenue), "Sipariş toplamı")
    metric_card(c4, "Kalan Ödeme", money(remaining), "Alınmamış tutar")

    st.markdown("---")
    left, right = st.columns([1.2, 1])
    with left:
        st.subheader("Son Siparişler")
        show_cols = ["Sipariş No", "Firma", "Şube", "Sipariş Tarihi", "Teslim Tarihi", "Durum", "Ödeme", "Toplam", "Kalan"]
        if not orders.empty:
            recent = orders.sort_values("ID", ascending=False).head(8)[show_cols].copy()
            recent["Toplam"] = recent["Toplam"].map(money)
            recent["Kalan"] = recent["Kalan"].map(money)
            safe_show(recent, 320)
        else:
            st.info("Henüz sipariş yok.")
    with right:
        st.subheader("Durum Dağılımı")
        if not orders.empty:
            chart = orders.groupby("Durum", as_index=False).size().rename(columns={"size": "Adet"})
            st.bar_chart(chart, x="Durum", y="Adet", use_container_width=True)
        else:
            st.info("Grafik için veri yok.")

    st.subheader("Yaklaşan Teslimatlar")
    due = due_orders_df()
    if due.empty:
        st.success("3 gün içinde teslimi yaklaşan açık sipariş yok.")
    else:
        safe_show(due, 280)


def metric_card(col, label: str, value: str, hint: str) -> None:
    with col:
        st.markdown(
            f"""
            <div class="metric-card">
                <div class="metric-label">{label}</div>
                <div class="metric-value">{value}</div>
                <div class="metric-hint">{hint}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def firms_df(active_only: bool = False) -> pd.DataFrame:
    where = "WHERE active=1" if active_only else ""
    return df(f"SELECT id ID, name Firma, branch Şube, contact Yetkili, phone Telefon, address Adres, tax_no 'Vergi No', tax_office 'Vergi Dairesi', note Not, CASE active WHEN 1 THEN 'Aktif' ELSE 'Pasif' END Durum, created_at 'Kayıt Tarihi' FROM firms {where} ORDER BY id DESC")


def products_df(active_only: bool = False) -> pd.DataFrame:
    where = "WHERE active=1" if active_only else ""
    return df(f"SELECT id ID, name Ürün, category Kategori, model Model, base_price 'Ana Fiyat', stock Stok, note Not, CASE active WHEN 1 THEN 'Aktif' ELSE 'Pasif' END Durum, created_at 'Kayıt Tarihi' FROM products {where} ORDER BY id DESC")


def order_summary_df() -> pd.DataFrame:
    orders = df(
        """
        SELECT o.id ID, o.order_no 'Sipariş No', f.name Firma, f.branch Şube, o.order_date 'Sipariş Tarihi',
               o.delivery_date 'Teslim Tarihi', o.status Durum, o.note Not
        FROM orders o JOIN firms f ON f.id=o.firm_id
        ORDER BY o.id DESC
        """
    )
    if orders.empty:
        return orders
    totals = []
    paids = []
    balances = []
    statuses = []
    for oid in orders["ID"].tolist():
        total = get_order_total(int(oid))
        paid = get_paid_total(int(oid))
        totals.append(total)
        paids.append(paid)
        balances.append(max(total - paid, 0))
        statuses.append(payment_status(total, paid))
    orders["Toplam"] = totals
    orders["Ödenen"] = paids
    orders["Kalan"] = balances
    orders["Ödeme"] = statuses
    return orders


def due_orders_df() -> pd.DataFrame:
    orders = order_summary_df()
    if orders.empty:
        return pd.DataFrame()
    today = date.today()
    rows = []
    for _, r in orders.iterrows():
        if r["Durum"] in ["Teslim Edildi", "İptal"]:
            continue
        try:
            d = datetime.strptime(str(r["Teslim Tarihi"]), "%Y-%m-%d").date()
        except Exception:
            continue
        days = (d - today).days
        if days <= 3:
            rows.append({
                "Sipariş No": r["Sipariş No"],
                "Firma": r["Firma"],
                "Şube": r["Şube"],
                "Teslim Tarihi": r["Teslim Tarihi"],
                "Kalan Gün": days,
                "Durum": r["Durum"],
                "Toplam": money(r["Toplam"]),
            })
    return pd.DataFrame(rows)


def firms_page() -> None:
    st.title("Firmalar")
    st.caption("Müşteri/firma kartlarını yönetin")

    with st.expander("+ Yeni firma ekle", expanded=True):
        with st.form("add_firm"):
            c1, c2, c3 = st.columns(3)
            name = c1.text_input("Firma adı *")
            branch = c2.text_input("Şube")
            contact = c3.text_input("Yetkili kişi")
            c4, c5 = st.columns(2)
            phone = c4.text_input("Telefon")
            tax_no = c5.text_input("Vergi No / VKN")
            c6, c7 = st.columns(2)
            tax_office = c6.text_input("Vergi Dairesi")
            address = c7.text_area("Adres", height=90)
            note = st.text_area("Not", height=70)
            submitted = st.form_submit_button("Firmayı kaydet", use_container_width=True)
        if submitted:
            if not name.strip():
                st.error("Firma adı zorunlu.")
            else:
                exec_sql(
                    "INSERT INTO firms(name,branch,contact,phone,address,tax_no,tax_office,note,active,created_at) VALUES(?,?,?,?,?,?,?,?,1,?)",
                    (name.strip(), branch.strip(), contact.strip(), phone.strip(), address.strip(), tax_no.strip(), tax_office.strip(), note.strip(), now_iso()),
                )
                st.success("Firma kaydedildi.")
                st.rerun()

    st.subheader("Kayıtlı Firmalar")
    fdf = firms_df()
    safe_show(fdf.drop(columns=["ID"], errors="ignore"), 320)

    st.subheader("Firma Düzelt / Sil")
    if fdf.empty:
        st.info("Düzenlenecek firma yok.")
        return
    options = {f"{r['ID']} - {r['Firma']} / {r['Şube']}": int(r["ID"]) for _, r in fdf.iterrows()}
    selected_label = st.selectbox("Firma seç", list(options.keys()))
    selected_id = options[selected_label]
    row = q("SELECT * FROM firms WHERE id=?", (selected_id,))[0]
    with st.form("edit_firm"):
        c1, c2, c3 = st.columns(3)
        name = c1.text_input("Firma adı", value=row["name"] or "")
        branch = c2.text_input("Şube", value=row["branch"] or "")
        contact = c3.text_input("Yetkili", value=row["contact"] or "")
        c4, c5 = st.columns(2)
        phone = c4.text_input("Telefon", value=row["phone"] or "")
        tax_no = c5.text_input("Vergi No / VKN", value=row["tax_no"] or "")
        c6, c7 = st.columns(2)
        tax_office = c6.text_input("Vergi Dairesi", value=row["tax_office"] or "")
        active = c7.selectbox("Durum", ["Aktif", "Pasif"], index=0 if row["active"] else 1)
        address = st.text_area("Adres", value=row["address"] or "", height=80)
        note = st.text_area("Not", value=row["note"] or "", height=70)
        save = st.form_submit_button("Değişiklikleri kaydet", use_container_width=True)
    if save:
        exec_sql(
            "UPDATE firms SET name=?,branch=?,contact=?,phone=?,address=?,tax_no=?,tax_office=?,note=?,active=? WHERE id=?",
            (name.strip(), branch.strip(), contact.strip(), phone.strip(), address.strip(), tax_no.strip(), tax_office.strip(), note.strip(), 1 if active == "Aktif" else 0, selected_id),
        )
        st.success("Firma güncellendi.")
        st.rerun()

    st.warning("Silme işlemi geri alınamaz. Bu firmaya sipariş varsa kalıcı silme yerine pasife alınır.")
    if st.button("Firmayı sil / pasife al", type="secondary"):
        used = q("SELECT COUNT(*) c FROM orders WHERE firm_id=?", (selected_id,))[0]["c"]
        if used:
            exec_sql("UPDATE firms SET active=0 WHERE id=?", (selected_id,))
            st.success("Firma geçmiş siparişlerde kullanıldığı için pasife alındı.")
        else:
            exec_sql("DELETE FROM firms WHERE id=?", (selected_id,))
            st.success("Firma silindi.")
        st.rerun()


def get_product_colors(product_id: int) -> pd.DataFrame:
    return df("SELECT id ID, color Renk, extra_price 'Ek Ücret', CASE active WHEN 1 THEN 'Aktif' ELSE 'Pasif' END Durum FROM product_colors WHERE product_id=? ORDER BY color", (product_id,))


def insert_product_colors(product_id: int, colors: list[str], extras: dict[str, float]) -> None:
    for color in colors:
        clean = color.strip().title()
        if not clean:
            continue
        exists = q("SELECT id FROM product_colors WHERE product_id=? AND lower(color)=lower(?)", (product_id, clean))
        if exists:
            exec_sql("UPDATE product_colors SET active=1, extra_price=? WHERE id=?", (float(extras.get(color, 0)), exists[0]["id"]))
        else:
            exec_sql("INSERT INTO product_colors(product_id,color,extra_price,active) VALUES(?,?,?,1)", (product_id, clean, float(extras.get(color, 0))))


def products_page() -> None:
    st.title("Ürünler")
    st.caption("Ürünleri ve renk seçeneklerini yönetin")

    with st.expander("+ Yeni ürün ekle", expanded=True):
        with st.form("add_product"):
            c1, c2, c3 = st.columns(3)
            name = c1.text_input("Ürün adı *")
            category = c2.text_input("Kategori", placeholder="Dilsiz Uşak, Oyuncu Koltuğu, Sehpa...")
            model = c3.text_input("Model")
            c4, c5 = st.columns(2)
            base_price = c4.number_input("Ana fiyat", min_value=0.0, step=50.0, format="%.2f")
            stock = c5.number_input("Stok", min_value=0, step=1)
            product_type = st.selectbox("Renk şablonu", ["Mobilya renkleri", "Oyuncu koltuğu renkleri", "Renk istemiyorum"])
            note = st.text_area("Not", height=70)
            submitted = st.form_submit_button("Ürünü kaydet", use_container_width=True)
        if submitted:
            if not name.strip():
                st.error("Ürün adı zorunlu.")
            else:
                exec_sql(
                    "INSERT INTO products(name,category,model,base_price,stock,note,active,created_at) VALUES(?,?,?,?,?,?,1,?)",
                    (name.strip(), category.strip(), model.strip(), float(base_price), int(stock), note.strip(), now_iso()),
                )
                product_id = q("SELECT last_insert_rowid() id")[0]["id"]
                if product_type == "Oyuncu koltuğu renkleri":
                    insert_product_colors(product_id, GAMER_COLORS, {c: 0 for c in GAMER_COLORS})
                elif product_type == "Mobilya renkleri":
                    insert_product_colors(product_id, FURNITURE_COLORS, {"Lake Beyaz": 300, "Siyah": 300})
                st.success("Ürün kaydedildi.")
                st.rerun()

    st.subheader("Kayıtlı Ürünler")
    pdf = products_df()
    shown = pdf.drop(columns=["ID"], errors="ignore").copy()
    if not shown.empty:
        shown["Ana Fiyat"] = shown["Ana Fiyat"].map(money)
    safe_show(shown, 320)

    st.subheader("Ürün Düzelt / Renk Yönet / Sil")
    if pdf.empty:
        st.info("Düzenlenecek ürün yok.")
        return
    options = {f"{r['ID']} - {r['Ürün']} / {r['Model']}": int(r["ID"]) for _, r in pdf.iterrows()}
    selected_label = st.selectbox("Ürün seç", list(options.keys()))
    product_id = options[selected_label]
    row = q("SELECT * FROM products WHERE id=?", (product_id,))[0]

    with st.form("edit_product"):
        c1, c2, c3 = st.columns(3)
        name = c1.text_input("Ürün adı", value=row["name"] or "")
        category = c2.text_input("Kategori", value=row["category"] or "")
        model = c3.text_input("Model", value=row["model"] or "")
        c4, c5, c6 = st.columns(3)
        base_price = c4.number_input("Ana fiyat", min_value=0.0, step=50.0, value=float(row["base_price"] or 0), format="%.2f")
        stock = c5.number_input("Stok", min_value=0, step=1, value=int(row["stock"] or 0))
        active = c6.selectbox("Durum", ["Aktif", "Pasif"], index=0 if row["active"] else 1)
        note = st.text_area("Not", value=row["note"] or "", height=70)
        save = st.form_submit_button("Ürünü güncelle", use_container_width=True)
    if save:
        exec_sql("UPDATE products SET name=?,category=?,model=?,base_price=?,stock=?,note=?,active=? WHERE id=?", (name.strip(), category.strip(), model.strip(), float(base_price), int(stock), note.strip(), 1 if active == "Aktif" else 0, product_id))
        st.success("Ürün güncellendi.")
        st.rerun()

    st.markdown("#### Renk Seçenekleri")
    cdf = get_product_colors(product_id)
    safe_show(cdf.drop(columns=["ID"], errors="ignore"), 220)
    with st.form("add_color"):
        c1, c2 = st.columns(2)
        color = c1.text_input("Renk adı")
        extra = c2.number_input("Ek ücret", min_value=0.0, step=50.0, format="%.2f")
        add = st.form_submit_button("Renk ekle/güncelle", use_container_width=True)
    if add and color.strip():
        insert_product_colors(product_id, [color], {color: float(extra)})
        st.success("Renk eklendi/güncellendi.")
        st.rerun()

    if cdf is not None and not cdf.empty:
        color_options = {f"{r['Renk']} (+{money(r['Ek Ücret'])})": int(r["ID"]) for _, r in cdf.iterrows()}
        sel_color = st.selectbox("Silinecek/pasif yapılacak renk", list(color_options.keys()))
        if st.button("Seçili rengi pasife al"):
            exec_sql("UPDATE product_colors SET active=0 WHERE id=?", (color_options[sel_color],))
            st.success("Renk pasife alındı.")
            st.rerun()

    st.warning("Silme işlemi geri alınamaz. Bu ürün siparişte kullanıldıysa kalıcı silme yerine pasife alınır.")
    if st.button("Ürünü sil / pasife al"):
        used = q("SELECT COUNT(*) c FROM order_items WHERE product_id=?", (product_id,))[0]["c"]
        if used:
            exec_sql("UPDATE products SET active=0 WHERE id=?", (product_id,))
            st.success("Ürün geçmiş siparişlerde kullanıldığı için pasife alındı.")
        else:
            exec_sql("DELETE FROM product_colors WHERE product_id=?", (product_id,))
            exec_sql("DELETE FROM products WHERE id=?", (product_id,))
            st.success("Ürün silindi.")
        st.rerun()


def new_order_page() -> None:
    st.title("Yeni Sipariş")
    st.caption("Firma seç, ürünleri ekle, siparişi kaydet")

    firms = firms_df(active_only=True)
    products = products_df(active_only=True)
    if firms.empty:
        st.warning("Önce en az bir firma eklemelisin.")
        return
    if products.empty:
        st.warning("Önce en az bir ürün eklemelisin.")
        return

    if "cart" not in st.session_state:
        st.session_state.cart = []

    firm_options = {f"{r['Firma']} / {r['Şube']}".strip(" / "): int(r["ID"]) for _, r in firms.iterrows()}
    product_options = {f"{r['Ürün']} / {r['Model']} - {money(r['Ana Fiyat'])}": int(r["ID"]) for _, r in products.iterrows()}

    st.subheader("Sipariş Bilgileri")
    c1, c2, c3 = st.columns(3)
    firm_label = c1.selectbox("Firma / Şube", list(firm_options.keys()))
    order_date = c2.date_input("Sipariş tarihi", value=date.today())
    delivery_date = c3.date_input("Teslim tarihi", value=date.today() + timedelta(days=7))
    c4, c5 = st.columns(2)
    status = c4.selectbox("Sipariş durumu", ORDER_STATUSES, index=0)
    note = c5.text_area("Sipariş notu", height=80)

    st.subheader("Ürün Kalemi Ekle")
    pc1, pc2, pc3, pc4 = st.columns([2.5, 1.4, 1, 1.2])
    prod_label = pc1.selectbox("Ürün", list(product_options.keys()))
    prod_id = product_options[prod_label]
    prod = q("SELECT * FROM products WHERE id=?", (prod_id,))[0]
    colors = q("SELECT color, extra_price FROM product_colors WHERE product_id=? AND active=1 ORDER BY color", (prod_id,))
    if colors:
        color_label = pc2.selectbox("Renk", [f"{r['color']} (+{money(r['extra_price'])})" for r in colors])
        color_index = [f"{r['color']} (+{money(r['extra_price'])})" for r in colors].index(color_label)
        color = colors[color_index]["color"]
        color_extra = float(colors[color_index]["extra_price"] or 0)
    else:
        color = pc2.text_input("Renk", value="")
        color_extra = 0.0
    qty = pc3.number_input("Adet", min_value=1, step=1, value=1)
    suggested = float(prod["base_price"] or 0) + color_extra
    unit_price = pc4.number_input("Birim fiyat", min_value=0.0, step=50.0, value=float(suggested), format="%.2f")
    line_note = st.text_input("Kalem notu")
    st.metric("Satır toplamı", money(unit_price * qty))
    if st.button("+ Sepete ekle", use_container_width=True):
        st.session_state.cart.append({
            "product_id": prod_id,
            "product_name": prod["name"],
            "color": color,
            "qty": int(qty),
            "unit_base_price": float(prod["base_price"] or 0),
            "color_extra": float(color_extra),
            "unit_price": float(unit_price),
            "line_total": float(unit_price) * int(qty),
            "note": line_note.strip(),
        })
        st.success("Ürün sepete eklendi.")
        st.rerun()

    st.subheader("Sipariş Sepeti")
    cart = pd.DataFrame(st.session_state.cart)
    if cart.empty:
        st.info("Sepette ürün yok.")
    else:
        show = cart.rename(columns={"product_name": "Ürün", "color": "Renk", "qty": "Adet", "unit_price": "Birim Fiyat", "line_total": "Satır Toplamı", "note": "Not"})[["Ürün", "Renk", "Adet", "Birim Fiyat", "Satır Toplamı", "Not"]]
        show["Birim Fiyat"] = show["Birim Fiyat"].map(money)
        show["Satır Toplamı"] = show["Satır Toplamı"].map(money)
        safe_show(show, 250)
        total = sum(float(x["line_total"]) for x in st.session_state.cart)
        st.metric("Sipariş toplamı", money(total))
        cols = st.columns(2)
        if cols[0].button("Sepeti temizle", use_container_width=True):
            st.session_state.cart = []
            st.rerun()
        if cols[1].button("Siparişi kaydet", type="primary", use_container_width=True):
            order_no = next_order_no()
            firm_id = firm_options[firm_label]
            exec_sql("INSERT INTO orders(order_no,firm_id,order_date,delivery_date,status,note,created_by,created_at) VALUES(?,?,?,?,?,?,?,?)", (order_no, firm_id, order_date.isoformat(), delivery_date.isoformat(), status, note.strip(), st.session_state.get("user", "admin"), now_iso()))
            order_id = q("SELECT last_insert_rowid() id")[0]["id"]
            for item in st.session_state.cart:
                exec_sql(
                    """
                    INSERT INTO order_items(order_id,product_id,product_name,color,qty,unit_base_price,color_extra,unit_price,line_total,note)
                    VALUES(?,?,?,?,?,?,?,?,?,?)
                    """,
                    (order_id, item["product_id"], item["product_name"], item["color"], item["qty"], item["unit_base_price"], item["color_extra"], item["unit_price"], item["line_total"], item["note"]),
                )
            st.session_state.cart = []
            st.success(f"Sipariş kaydedildi: {order_no}")
            st.rerun()


def orders_page() -> None:
    st.title("Siparişler")
    st.caption("Siparişleri filtreleyin, durum ve ödeme bilgilerini yönetin")
    orders = order_summary_df()
    if orders.empty:
        st.info("Henüz sipariş yok.")
        return

    c1, c2, c3 = st.columns(3)
    firm_search = c1.text_input("Firma ara")
    status_filter = c2.selectbox("Durum filtresi", ["Tümü"] + ORDER_STATUSES)
    pay_filter = c3.selectbox("Ödeme filtresi", ["Tümü", "Bekliyor", "Kısmi Ödendi", "Ödendi"])
    view = orders.copy()
    if firm_search.strip():
        view = view[view["Firma"].astype(str).str.contains(firm_search.strip(), case=False, na=False)]
    if status_filter != "Tümü":
        view = view[view["Durum"] == status_filter]
    if pay_filter != "Tümü":
        view = view[view["Ödeme"] == pay_filter]

    table = view[["Sipariş No", "Firma", "Şube", "Sipariş Tarihi", "Teslim Tarihi", "Durum", "Ödeme", "Toplam", "Ödenen", "Kalan"]].copy()
    for col in ["Toplam", "Ödenen", "Kalan"]:
        table[col] = table[col].map(money)
    safe_show(table, 360)

    st.subheader("Sipariş Detayı / Güncelleme")
    options = {f"{r['Sipariş No']} - {r['Firma']} / {money(r['Toplam'])}": int(r["ID"]) for _, r in orders.iterrows()}
    selected = st.selectbox("Sipariş seç", list(options.keys()))
    order_id = options[selected]
    order = q("SELECT * FROM orders WHERE id=?", (order_id,))[0]
    total = get_order_total(order_id)
    paid = get_paid_total(order_id)
    bal = max(total - paid, 0)

    m1, m2, m3, m4 = st.columns(4)
    metric_card(m1, "Sipariş Toplamı", money(total), order["order_no"])
    metric_card(m2, "Ödenen", money(paid), "Alınan toplam")
    metric_card(m3, "Kalan", money(bal), "Açık tutar")
    metric_card(m4, "Ödeme Durumu", payment_status(total, paid), "Sipariş bazlı")

    items = df("SELECT product_name Ürün, color Renk, qty Adet, unit_price 'Birim Fiyat', line_total 'Satır Toplamı', note Not FROM order_items WHERE order_id=?", (order_id,))
    if not items.empty:
        items["Birim Fiyat"] = items["Birim Fiyat"].map(money)
        items["Satır Toplamı"] = items["Satır Toplamı"].map(money)
    safe_show(items, 250)

    with st.form("update_order"):
        c1, c2, c3 = st.columns(3)
        status = c1.selectbox("Durum", ORDER_STATUSES, index=ORDER_STATUSES.index(order["status"]) if order["status"] in ORDER_STATUSES else 0)
        order_date = c2.date_input("Sipariş tarihi", value=datetime.strptime(order["order_date"], "%Y-%m-%d").date() if order["order_date"] else date.today())
        delivery_date = c3.date_input("Teslim tarihi", value=datetime.strptime(order["delivery_date"], "%Y-%m-%d").date() if order["delivery_date"] else date.today())
        note = st.text_area("Not", value=order["note"] or "", height=80)
        save = st.form_submit_button("Siparişi güncelle", use_container_width=True)
    if save:
        exec_sql("UPDATE orders SET status=?,order_date=?,delivery_date=?,note=? WHERE id=?", (status, order_date.isoformat(), delivery_date.isoformat(), note.strip(), order_id))
        st.success("Sipariş güncellendi.")
        st.rerun()

    st.markdown("#### Ödeme Ekle")
    with st.form("add_payment"):
        c1, c2, c3 = st.columns(3)
        amount = c1.number_input("Ödeme tutarı", min_value=0.0, step=100.0, value=0.0, format="%.2f")
        method = c2.selectbox("Ödeme yöntemi", PAYMENT_METHODS)
        payment_date = c3.date_input("Ödeme tarihi", value=date.today())
        m1, m2 = st.columns(2)
        maturity_months = m1.number_input("Çek/Senet vade ayı", min_value=0, step=1, value=0)
        maturity_date = m2.date_input("Vade tarihi", value=date.today())
        note = st.text_input("Ödeme notu")
        add = st.form_submit_button("Ödemeyi kaydet", use_container_width=True)
    if add:
        if amount <= 0:
            st.error("Ödeme tutarı 0'dan büyük olmalı.")
        else:
            exec_sql("INSERT INTO payments(order_id,payment_date,amount,method,maturity_months,maturity_date,note,created_at) VALUES(?,?,?,?,?,?,?,?)", (order_id, payment_date.isoformat(), float(amount), method, int(maturity_months), maturity_date.isoformat(), note.strip(), now_iso()))
            st.success("Ödeme kaydedildi.")
            st.rerun()

    st.markdown("#### Ödeme Geçmişi")
    pays = df("SELECT id ID, payment_date Tarih, amount Tutar, method Yöntem, maturity_months 'Vade Ayı', maturity_date 'Vade Tarihi', note Not FROM payments WHERE order_id=? ORDER BY id DESC", (order_id,))
    if not pays.empty:
        show = pays.drop(columns=["ID"]).copy()
        show["Tutar"] = show["Tutar"].map(money)
        safe_show(show, 220)
        pay_options = {f"{r['Tarih']} - {r['Yöntem']} - {money(r['Tutar'])}": int(r["ID"]) for _, r in pays.iterrows()}
        sel_pay = st.selectbox("Silinecek ödeme", list(pay_options.keys()))
        if st.button("Seçili ödemeyi sil"):
            exec_sql("DELETE FROM payments WHERE id=?", (pay_options[sel_pay],))
            st.success("Ödeme silindi.")
            st.rerun()
    else:
        st.info("Bu sipariş için ödeme kaydı yok.")

    st.error("Sipariş silme işlemi geri alınamaz.")
    if st.button("Siparişi kalıcı sil", type="secondary"):
        exec_sql("DELETE FROM payments WHERE order_id=?", (order_id,))
        exec_sql("DELETE FROM order_items WHERE order_id=?", (order_id,))
        exec_sql("DELETE FROM orders WHERE id=?", (order_id,))
        st.success("Sipariş silindi.")
        st.rerun()


def settings_page() -> None:
    st.title("Yedek / Ayarlar")
    st.caption("Yedek alın, geri yükleyin, şifre değiştirin")

    st.subheader("Yedek İndir")
    excel = export_excel()
    st.download_button("Excel yedeği indir", excel, file_name=f"gundays_siparis_yedek_{date.today().isoformat()}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
    if DB_PATH.exists():
        st.download_button("SQLite veritabanı yedeği indir", DB_PATH.read_bytes(), file_name=f"gundays_home_orders_{date.today().isoformat()}.db", mime="application/octet-stream", use_container_width=True)

    st.subheader("Veritabanı Geri Yükle")
    up = st.file_uploader(".db yedeği yükle", type=["db", "sqlite", "sqlite3"])
    if up and st.button("Yedeği geri yükle"):
        DB_PATH.write_bytes(up.read())
        init_db()
        st.success("Yedek geri yüklendi.")
        st.rerun()

    st.subheader("Şifre Değiştir")
    with st.form("change_pass"):
        old = st.text_input("Mevcut şifre", type="password")
        new = st.text_input("Yeni şifre", type="password")
        new2 = st.text_input("Yeni şifre tekrar", type="password")
        ok = st.form_submit_button("Şifreyi değiştir", use_container_width=True)
    if ok:
        user = st.session_state.get("user", "admin")
        rows = q("SELECT * FROM users WHERE username=? AND password=?", (user, old))
        if not rows:
            st.error("Mevcut şifre hatalı.")
        elif not new or new != new2:
            st.error("Yeni şifreler eşleşmiyor.")
        else:
            exec_sql("UPDATE users SET password=? WHERE username=?", (new, user))
            st.success("Şifre değiştirildi.")

    st.subheader("Bakım")
    if st.button("Veritabanını onar / kolonları tamamla", use_container_width=True):
        init_db()
        st.success("Veritabanı kontrol edildi.")
        st.rerun()


def export_excel() -> bytes:
    output = BytesIO()
    sheets = {
        "Firmalar": firms_df(),
        "Urunler": products_df(),
        "Siparisler": order_summary_df(),
        "Siparis_Kalemleri": df("SELECT * FROM order_items ORDER BY id"),
        "Odemeler": df("SELECT * FROM payments ORDER BY id"),
    }
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for name, data in sheets.items():
            data.to_excel(writer, sheet_name=name[:31], index=False)
    return output.getvalue()


def css() -> None:
    st.markdown(
        """
        <style>
        .stApp { background: radial-gradient(circle at 20% 0%, #132039 0%, #070B13 42%, #05070D 100%); }
        section[data-testid="stSidebar"] { background: linear-gradient(180deg, #0C1527 0%, #070B13 100%); border-right: 1px solid rgba(216,170,71,.25); }
        h1, h2, h3 { letter-spacing: -0.02em; }
        .metric-card { padding: 22px; border: 1px solid rgba(216,170,71,.45); border-radius: 18px; background: linear-gradient(135deg, rgba(15,25,43,.96), rgba(8,12,22,.96)); box-shadow: 0 12px 40px rgba(0,0,0,.28); min-height: 135px; }
        .metric-label { color: #F2E6C9; font-weight: 800; font-size: .92rem; }
        .metric-value { color: #FFFFFF; font-weight: 900; font-size: 2rem; margin-top: 12px; }
        .metric-hint { color: #D8AA47; font-size: .86rem; font-weight: 700; margin-top: 12px; }
        .stButton>button, .stDownloadButton>button { border: 1px solid rgba(216,170,71,.65) !important; border-radius: 12px !important; background: linear-gradient(135deg, rgba(216,170,71,.20), rgba(20,28,45,.90)) !important; color: white !important; font-weight: 800 !important; }
        .stTextInput input, .stTextArea textarea, .stNumberInput input, .stDateInput input, div[data-baseweb="select"] > div { background-color: #202333 !important; border-color: rgba(255,255,255,.12) !important; color: #FFFFFF !important; }
        div[data-testid="stDataFrame"] { border: 1px solid rgba(255,255,255,.10); border-radius: 14px; overflow: hidden; }
        .login-wrap { max-width: 760px; margin: 8vh auto; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    st.set_page_config(page_title=APP_TITLE, page_icon="🏠", layout="wide")
    css()
    init_db()
    if "user" not in st.session_state:
        login()
        return
    page = menu()
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
