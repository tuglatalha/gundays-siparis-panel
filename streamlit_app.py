import hashlib
import io
import os
import shutil
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st
import requests
import re
import unicodedata


APP_TITLE = "Günday's Home Sipariş Paneli"
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
PAYMENT_METHODS = ["Nakit", "Kredi Kartı", "Havale/EFT", "Çek", "Senet", "Diğer"]

# Genel ürün renkleri ve oyuncu koltuğu renk grubu.
# Oyuncu koltuklarında aşağıdaki OYUNCU_KOLTUGU_COLORS listesinin tamamı görünür.
OYUNCU_KOLTUGU_COLORS = [
    "Siyah",
    "Antrasit",
    "Mavi",
    "Kırmızı",
    "Pembe",
    "Yeşil",
    "Turuncu",
    "Beyaz",
    "Sarı",
]

DEFAULT_COLORS = [
    ("Naturel", 0),
    ("Ceviz", 0),
    ("Lake Beyaz", 300),
    ("Siyah", 300),
    ("Antrasit", 0),
    ("Mavi", 0),
    ("Kırmızı", 0),
    ("Pembe", 0),
    ("Yeşil", 0),
    ("Turuncu", 0),
    ("Beyaz", 0),
    ("Sarı", 0),
]


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


def add_months(d: date, months: int) -> date:
    # Dış kütüphane kullanmadan basit ay ekleme.
    month = d.month - 1 + int(months or 0)
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return date(year, month, day)


def qident(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def db_connect():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def table_columns(conn, table: str) -> set:
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({qident(table)})").fetchall()}
    except Exception:
        return set()


def ensure_column(conn, table: str, column: str, definition: str):
    if table_columns(conn, table) and column not in table_columns(conn, table):
        conn.execute(f"ALTER TABLE {qident(table)} ADD COLUMN {qident(column)} {definition}")


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

            CREATE TABLE IF NOT EXISTS product_colors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                color_name TEXT UNIQUE NOT NULL,
                price_modifier REAL NOT NULL DEFAULT 0,
                active INTEGER NOT NULL DEFAULT 1,
                note TEXT DEFAULT '',
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
                color_extra REAL NOT NULL DEFAULT 0,
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
                check_months INTEGER NOT NULL DEFAULT 0,
                check_due_date TEXT DEFAULT '',
                note TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE
            );
            """
        )
        migrate_schema(conn)
        exists = conn.execute("SELECT COUNT(*) AS c FROM users WHERE username='admin'").fetchone()["c"]
        if not exists:
            conn.execute(
                "INSERT INTO users (username, password_hash, role, active, created_at) VALUES (?, ?, ?, ?, ?)",
                ("admin", hash_password("admin123"), "Admin", 1, now_str()),
            )
        # Varsayılan renkler yoksa ekle.
        for color, extra in DEFAULT_COLORS:
            exists = conn.execute("SELECT COUNT(*) AS c FROM product_colors WHERE color_name=?", (color,)).fetchone()["c"]
            if not exists:
                conn.execute(
                    "INSERT INTO product_colors (color_name, price_modifier, active, note, created_at) VALUES (?, ?, 1, ?, ?)",
                    (color, float(extra), "Varsayılan renk", now_str()),
                )
        conn.commit()


def migrate_schema(conn):
    specs = {
        "users": [
            ("username", "TEXT DEFAULT ''"),
            ("password_hash", "TEXT DEFAULT ''"),
            ("role", "TEXT DEFAULT 'Admin'"),
            ("active", "INTEGER NOT NULL DEFAULT 1"),
            ("created_at", "TEXT DEFAULT ''"),
        ],
        "firms": [
            ("firm_name", "TEXT DEFAULT ''"),
            ("branch", "TEXT DEFAULT ''"),
            ("contact_name", "TEXT DEFAULT ''"),
            ("phone", "TEXT DEFAULT ''"),
            ("address", "TEXT DEFAULT ''"),
            ("tax_no", "TEXT DEFAULT ''"),
            ("tax_office", "TEXT DEFAULT ''"),
            ("note", "TEXT DEFAULT ''"),
            ("active", "INTEGER NOT NULL DEFAULT 1"),
            ("created_at", "TEXT DEFAULT ''"),
        ],
        "products": [
            ("product_name", "TEXT DEFAULT ''"),
            ("model", "TEXT DEFAULT ''"),
            ("color", "TEXT DEFAULT ''"),
            ("category", "TEXT DEFAULT ''"),
            ("unit_price", "REAL NOT NULL DEFAULT 0"),
            ("stock", "INTEGER NOT NULL DEFAULT 0"),
            ("note", "TEXT DEFAULT ''"),
            ("active", "INTEGER NOT NULL DEFAULT 1"),
            ("created_at", "TEXT DEFAULT ''"),
        ],
        "product_colors": [
            ("color_name", "TEXT DEFAULT ''"),
            ("price_modifier", "REAL NOT NULL DEFAULT 0"),
            ("active", "INTEGER NOT NULL DEFAULT 1"),
            ("note", "TEXT DEFAULT ''"),
            ("created_at", "TEXT DEFAULT ''"),
        ],
        "orders": [
            ("order_no", "TEXT DEFAULT ''"),
            ("firm_id", "INTEGER"),
            ("firm_name_snapshot", "TEXT DEFAULT ''"),
            ("branch_snapshot", "TEXT DEFAULT ''"),
            ("order_date", "TEXT DEFAULT ''"),
            ("delivery_date", "TEXT DEFAULT ''"),
            ("status", "TEXT DEFAULT 'Sipariş Alındı'"),
            ("payment_status", "TEXT DEFAULT 'Bekliyor'"),
            ("shipping_note", "TEXT DEFAULT ''"),
            ("general_note", "TEXT DEFAULT ''"),
            ("created_by", "TEXT DEFAULT 'admin'"),
            ("total_amount", "REAL NOT NULL DEFAULT 0"),
            ("created_at", "TEXT DEFAULT ''"),
        ],
        "order_items": [
            ("order_id", "INTEGER"),
            ("product_id", "INTEGER"),
            ("product_name_snapshot", "TEXT DEFAULT ''"),
            ("model_snapshot", "TEXT DEFAULT ''"),
            ("color_snapshot", "TEXT DEFAULT ''"),
            ("color_extra", "REAL NOT NULL DEFAULT 0"),
            ("quantity", "INTEGER NOT NULL DEFAULT 1"),
            ("unit_price", "REAL NOT NULL DEFAULT 0"),
            ("line_total", "REAL NOT NULL DEFAULT 0"),
            ("note", "TEXT DEFAULT ''"),
        ],
        "payments": [
            ("order_id", "INTEGER"),
            ("payment_date", "TEXT DEFAULT ''"),
            ("amount", "REAL NOT NULL DEFAULT 0"),
            ("method", "TEXT DEFAULT ''"),
            ("check_months", "INTEGER NOT NULL DEFAULT 0"),
            ("check_due_date", "TEXT DEFAULT ''"),
            ("note", "TEXT DEFAULT ''"),
            ("created_at", "TEXT DEFAULT ''"),
        ],
    }
    for table, columns in specs.items():
        if table_columns(conn, table):
            for col, definition in columns:
                ensure_column(conn, table, col, definition)
    for table in ["users", "firms", "products", "product_colors", "orders", "payments"]:
        if "created_at" in table_columns(conn, table):
            conn.execute(f"UPDATE {qident(table)} SET created_at=? WHERE created_at IS NULL OR created_at=''", (now_str(),))
    conn.commit()


def safe_table(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    out = df.copy()
    for col in columns:
        if col not in out.columns:
            out[col] = ""
    return out[columns]


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
    try:
        number = int(str(rows[0]["order_no"]).split("-")[-1]) + 1
    except Exception:
        number = 1
    return f"{prefix}{number:04d}"


def firm_label(row) -> str:
    branch = (row.get("branch") or "").strip()
    return f"{row.get('firm_name','')} / {branch}" if branch else row.get("firm_name", "")


def product_label(row) -> str:
    parts = [row.get("product_name", "")]
    if row.get("model"):
        parts.append(row["model"])
    if row.get("category"):
        parts.append(row["category"])
    return " - ".join([str(p) for p in parts if str(p).strip()])


def color_label(row) -> str:
    extra = float(row.get("price_modifier", 0) or 0)
    return f"{row.get('color_name','')} (+{money(extra)})" if extra else str(row.get("color_name", ""))


def read_firms(active_only=False) -> pd.DataFrame:
    sql = """
        SELECT id, firm_name, branch, contact_name, phone, address, tax_no, tax_office, note, active, created_at
        FROM firms
    """
    if active_only:
        sql += " WHERE active=1"
    sql += " ORDER BY firm_name, branch, id"
    return df_query(sql)


def read_products(active_only=False) -> pd.DataFrame:
    sql = """
        SELECT id, product_name, model, color, category, unit_price, stock, note, active, created_at
        FROM products
    """
    if active_only:
        sql += " WHERE active=1"
    sql += " ORDER BY product_name, model, id"
    return df_query(sql)


def read_colors(active_only=False) -> pd.DataFrame:
    sql = "SELECT id, color_name, price_modifier, active, note, created_at FROM product_colors"
    if active_only:
        sql += " WHERE active=1"
    sql += " ORDER BY active DESC, color_name"
    return df_query(sql)


def read_orders() -> pd.DataFrame:
    return df_query(
        """
        SELECT o.id, o.order_no, o.firm_id, o.firm_name_snapshot AS firm_name, o.branch_snapshot AS branch,
               o.order_date, o.delivery_date, o.status, o.payment_status, o.total_amount,
               IFNULL((SELECT SUM(amount) FROM payments p WHERE p.order_id=o.id), 0) AS paid_amount,
               MAX(o.total_amount - IFNULL((SELECT SUM(amount) FROM payments p WHERE p.order_id=o.id), 0), 0) AS remaining_amount,
               o.shipping_note, o.general_note, o.created_by, o.created_at
        FROM orders o
        ORDER BY o.id DESC
        """
    )


def read_order_items(order_id: int) -> pd.DataFrame:
    return df_query(
        """
        SELECT product_name_snapshot AS product_name, model_snapshot AS model, color_snapshot AS color,
               color_extra, quantity, unit_price, line_total, note
        FROM order_items
        WHERE order_id=?
        ORDER BY id
        """,
        (int(order_id),),
    )


def read_payments(order_id: int | None = None, firm_id: int | None = None) -> pd.DataFrame:
    sql = """
        SELECT p.id, p.order_id, o.order_no, o.firm_id, o.firm_name_snapshot AS firm_name,
               p.payment_date, p.amount, p.method, p.check_months, p.check_due_date, p.note, p.created_at
        FROM payments p
        JOIN orders o ON o.id=p.order_id
    """
    params = []
    where = []
    if order_id is not None:
        where.append("p.order_id=?")
        params.append(int(order_id))
    if firm_id is not None:
        where.append("o.firm_id=?")
        params.append(int(firm_id))
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY p.payment_date DESC, p.id DESC"
    return df_query(sql, tuple(params))


def update_order_payment_status(order_id: int):
    rows = run_sql(
        """
        SELECT total_amount, IFNULL((SELECT SUM(amount) FROM payments WHERE order_id=orders.id), 0) AS paid
        FROM orders WHERE id=?
        """,
        (int(order_id),),
        fetch=True,
    )
    if not rows:
        return
    total = float(rows[0]["total_amount"] or 0)
    paid = float(rows[0]["paid"] or 0)
    if paid <= 0:
        status = "Bekliyor"
    elif paid + 0.01 >= total:
        status = "Ödendi"
    else:
        status = "Kısmi Ödendi"
    run_sql("UPDATE orders SET payment_status=? WHERE id=?", (status, int(order_id)))


def create_order(firm_id: int, order_date: str, delivery_date: str, status: str, payment_status: str,
                 shipping_note: str, general_note: str, created_by: str, cart: list[dict]):
    if not cart:
        raise ValueError("Siparişe en az bir ürün kalemi eklemelisin.")
    rows = run_sql("SELECT * FROM firms WHERE id=?", (int(firm_id),), fetch=True)
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
                order_no, int(firm_id), firm["firm_name"], firm["branch"], order_date, delivery_date,
                status, payment_status, shipping_note, general_note, created_by, total, now_str()
            ),
        )
        order_id = cur.lastrowid
        for item in cart:
            conn.execute(
                """
                INSERT INTO order_items (order_id, product_id, product_name_snapshot, model_snapshot, color_snapshot,
                                         color_extra, quantity, unit_price, line_total, note)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order_id, item.get("product_id"), item.get("product_name", ""), item.get("model", ""),
                    item.get("color", ""), float(item.get("color_extra", 0)), int(item.get("quantity", 1)),
                    float(item.get("unit_price", 0)), float(item.get("line_total", 0)), item.get("note", "")
                ),
            )
            if item.get("product_id"):
                conn.execute("UPDATE products SET stock = MAX(stock - ?, 0) WHERE id=?", (int(item.get("quantity", 1)), int(item.get("product_id"))))
        conn.commit()
    return order_no


def delete_order(order_id: int):
    run_sql("DELETE FROM orders WHERE id=?", (int(order_id),))


def firm_used(firm_id: int) -> bool:
    rows = run_sql("SELECT COUNT(*) AS c FROM orders WHERE firm_id=?", (int(firm_id),), fetch=True)
    return rows[0]["c"] > 0


def product_used(product_id: int) -> bool:
    rows = run_sql("SELECT COUNT(*) AS c FROM order_items WHERE product_id=?", (int(product_id),), fetch=True)
    return rows[0]["c"] > 0


def add_payment(order_id: int, payment_date: str, amount: float, method: str, check_months: int, check_due_date: str, note: str):
    run_sql(
        """
        INSERT INTO payments (order_id, payment_date, amount, method, check_months, check_due_date, note, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (int(order_id), payment_date, float(amount), method, int(check_months or 0), check_due_date or "", note.strip(), now_str()),
    )
    update_order_payment_status(int(order_id))


def delete_payment(payment_id: int):
    rows = run_sql("SELECT order_id FROM payments WHERE id=?", (int(payment_id),), fetch=True)
    order_id = int(rows[0]["order_id"]) if rows else None
    run_sql("DELETE FROM payments WHERE id=?", (int(payment_id),))
    if order_id:
        update_order_payment_status(order_id)


def backup_excel_bytes() -> bytes:
    output = io.BytesIO()
    sheets = {
        "Firmalar": read_firms(False),
        "Urunler": read_products(False),
        "Renkler": read_colors(False),
        "Siparisler": read_orders(),
        "Odemeler": read_payments(),
    }
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for name, df in sheets.items():
            df.to_excel(writer, index=False, sheet_name=name)
        items = df_query(
            """
            SELECT o.order_no, oi.product_name_snapshot AS product_name, oi.model_snapshot AS model, oi.color_snapshot AS color,
                   oi.color_extra, oi.quantity, oi.unit_price, oi.line_total, oi.note
            FROM order_items oi
            JOIN orders o ON o.id=oi.order_id
            ORDER BY o.id DESC, oi.id
            """
        )
        items.to_excel(writer, index=False, sheet_name="Siparis_Kalemleri")
    return output.getvalue()



# -----------------------------
# Toplu cari / ürün aktarımı
# -----------------------------
TR_MONTHS = {
    "ocak": 1, "subat": 2, "şubat": 2, "mart": 3, "nisan": 4, "mayıs": 5, "mayis": 5,
    "haziran": 6, "temmuz": 7, "ağustos": 8, "agustos": 8, "eylül": 9, "eylul": 9,
    "ekim": 10, "kasım": 11, "kasim": 11, "aralık": 12, "aralik": 12,
}
KNOWN_COLORS = {
    "NATUREL", "CEVİZ", "CEVIZ", "SİYAH", "SIYAH", "LAKE", "LAKE BEYAZ", "BEYAZ",
    "KIRMIZI", "SARI", "MAVİ", "MAVI", "ANTRASİT", "ANTRASIT", "TURUNCU", "PEMBE", "YEŞİL", "YESIL",
    "GRİ", "GRI", "KREM", "LACİVERT", "LACIVERT", "KAHVERENGİ", "KAHVERENGI",
}
IGNORE_SHEETS = {"dashboard", "özet", "ozet", "listeler", "kullanim", "kullanım", "ürünler", "urunler", "firmalar", "renkler"}


def tr_upper(text: str) -> str:
    text = str(text or "").strip()
    trans = str.maketrans({"i":"İ", "ı":"I"})
    return text.translate(trans).upper()

KNOWN_COLORS.update({tr_upper(c) for c in OYUNCU_KOLTUGU_COLORS})


def norm_text(text: str) -> str:
    text = tr_upper(text)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def is_gaming_chair_text(text: str) -> bool:
    """Oyuncu koltuğu ürünlerini marka/model fark etmeden yakalar."""
    nt = norm_text(text)
    return ("OYUNCU" in nt and "KOLTUK" in nt) or "OYUNCU KOLTUGU" in nt or "GAMER" in nt or "GAMING" in nt


def gaming_color_norms() -> set:
    return {norm_text(c) for c in OYUNCU_KOLTUGU_COLORS}


def parse_money_value(value) -> float:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s or s.lower() in ["nan", "none", "null"]:
        return 0.0
    s = s.replace("₺", "").replace("TL", "").replace("tl", "").replace(" ", "")
    s = re.sub(r"[^0-9,\.\-]", "", s)
    if not s or s in ["-", ",", "."]:
        return 0.0
    # Türkçe format: 12.500,000 -> 12500.000
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except Exception:
        try:
            return float(re.sub(r"[^0-9\.-]", "", s))
        except Exception:
            return 0.0


def parse_int_value(value, default=0) -> int:
    try:
        return int(round(parse_money_value(value)))
    except Exception:
        return int(default)


def parse_date_value(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return today_str()
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    s = str(value).strip()
    if not s or s.lower() in ["nan", "none"]:
        return today_str()
    parsed = pd.to_datetime(s, dayfirst=True, errors="coerce")
    if pd.notna(parsed):
        return parsed.date().isoformat()
    m = re.search(r"(\d{1,2})\s+([A-Za-zÇĞİÖŞÜçğıöşü]+)\s+(\d{2,4})", s)
    if m:
        day = int(m.group(1)); month = TR_MONTHS.get(m.group(2).lower(), date.today().month); year = int(m.group(3))
        if year < 100:
            year += 2000
        try:
            return date(year, month, day).isoformat()
        except Exception:
            return today_str()
    return today_str()


def find_col(df: pd.DataFrame, candidates: list[str]):
    normalized = {norm_text(c): c for c in df.columns}
    for cand in candidates:
        nc = norm_text(cand)
        if nc in normalized:
            return normalized[nc]
    for col in df.columns:
        ncol = norm_text(col)
        for cand in candidates:
            nc = norm_text(cand)
            if nc and (nc in ncol or ncol in nc):
                return col
    return None


def read_import_workbook(source, is_url=False) -> dict[str, pd.DataFrame]:
    if is_url:
        url = str(source).strip()
        m = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", url)
        if not m:
            raise ValueError("Google Sheet linki okunamadı. Linkin /spreadsheets/d/... formatında olması lazım.")
        file_id = m.group(1)
        export_url = f"https://docs.google.com/spreadsheets/d/{file_id}/export?format=xlsx"
        resp = requests.get(export_url, timeout=45)
        if resp.status_code != 200 or len(resp.content) < 5000:
            raise ValueError("Google Sheet indirilemedi. Paylaşım ayarı 'Bağlantıya sahip olan herkes görüntüleyebilir' olmalı. Olmazsa Excel indirip yükle.")
        return pd.read_excel(io.BytesIO(resp.content), sheet_name=None, header=None, engine="openpyxl")
    return pd.read_excel(source, sheet_name=None, header=None, engine="openpyxl")


def detect_header_and_table(raw: pd.DataFrame):
    if raw is None or raw.empty:
        return None
    raw = raw.dropna(how="all")
    if raw.empty:
        return None
    header_idx = None
    for i in range(min(20, len(raw))):
        values = [norm_text(x) for x in raw.iloc[i].tolist()]
        joined = " ".join(values)
        if ("TARIH" in joined and "ADET" in joined and ("CINSI" in joined or "URUN" in joined)):
            header_idx = raw.index[i]
            break
    if header_idx is None:
        return None
    header = [str(x).strip() if not pd.isna(x) else f"Sütun_{j+1}" for j, x in enumerate(raw.loc[header_idx].tolist())]
    df = raw.loc[raw.index > header_idx].copy()
    df.columns = header
    df = df.dropna(how="all")
    df = df.loc[:, ~pd.Index(df.columns).duplicated()]
    return df


def split_product_color(text: str):
    t = str(text or "").strip()
    t = re.sub(r"\s+", " ", t)
    if not t:
        return "", "Standart"
    if " - " in t:
        left, right = t.rsplit(" - ", 1)
        color = right.strip()
        return left.strip(), color or "Standart"
    # Son kelime renk ise ayır.
    parts = t.split()
    if len(parts) > 1 and norm_text(parts[-1]) in {norm_text(x) for x in KNOWN_COLORS}:
        return " ".join(parts[:-1]).strip(), parts[-1].strip()
    return t, "Standart"


def color_extra_for(color: str) -> float:
    nc = norm_text(color)
    if "SIYAH" in nc or "LAKE" in nc:
        return 300.0
    return 0.0


def get_or_create_firm(conn, firm_name: str, branch: str = "") -> int:
    firm_name = str(firm_name or "").strip() or "Bilinmeyen Firma"
    branch = str(branch or "").strip()
    row = conn.execute("SELECT id FROM firms WHERE UPPER(firm_name)=UPPER(?) AND UPPER(branch)=UPPER(?) LIMIT 1", (firm_name, branch)).fetchone()
    if row:
        return int(row["id"])
    cur = conn.execute(
        "INSERT INTO firms (firm_name, branch, active, note, created_at) VALUES (?, ?, 1, ?, ?)",
        (firm_name, branch, "Toplu cari aktarımı", now_str()),
    )
    return int(cur.lastrowid)


def get_or_create_color(conn, color_name: str) -> int:
    color_name = str(color_name or "Standart").strip() or "Standart"
    row = conn.execute("SELECT id FROM product_colors WHERE UPPER(color_name)=UPPER(?) LIMIT 1", (color_name,)).fetchone()
    if row:
        return int(row["id"])
    cur = conn.execute(
        "INSERT INTO product_colors (color_name, price_modifier, active, note, created_at) VALUES (?, ?, 1, ?, ?)",
        (color_name, color_extra_for(color_name), "Toplu aktarımda tespit edildi", now_str()),
    )
    return int(cur.lastrowid)


def get_or_create_product(conn, product_name: str, unit_price: float) -> int:
    product_name = str(product_name or "").strip()
    if not product_name:
        product_name = "İsimsiz Ürün"
    norm = norm_text(product_name)
    rows = conn.execute("SELECT id, product_name, unit_price FROM products WHERE active=1").fetchall()
    for r in rows:
        if norm_text(r["product_name"]) == norm:
            # Ana fiyat 0 ise ilk görülen gerçek fiyatla güncelle.
            if float(r["unit_price"] or 0) <= 0 and float(unit_price or 0) > 0:
                conn.execute("UPDATE products SET unit_price=? WHERE id=?", (float(unit_price), int(r["id"])))
            return int(r["id"])
    category = "Oyuncu Koltuğu" if is_gaming_chair_text(product_name) else "Aktarılan Ürün"
    note = "Cari Excel aktarımı ile açıldı"
    if is_gaming_chair_text(product_name):
        note += " | Oyuncu koltuğu renk grubu: " + ", ".join(OYUNCU_KOLTUGU_COLORS)
    cur = conn.execute(
        "INSERT INTO products (product_name, model, category, unit_price, stock, note, active, created_at) VALUES (?, ?, ?, ?, 0, ?, 1, ?)",
        (product_name, "", category, float(unit_price or 0), note, now_str()),
    )
    return int(cur.lastrowid)


def import_records_from_workbook(workbook: dict[str, pd.DataFrame], dry_run=True):
    parsed = []
    ignored = 0
    issues = []
    for sheet_name, raw in workbook.items():
        if norm_text(sheet_name).lower() in IGNORE_SHEETS:
            continue
        table = detect_header_and_table(raw)
        if table is None:
            continue
        date_col = find_col(table, ["TARİH", "TARIH", "SİPARİŞ TARİHİ", "SIPARIS TARIHI"])
        qty_col = find_col(table, ["ADET", "MİKTAR", "MIKTAR"])
        prod_col = find_col(table, ["CİNSİ", "CINSI", "ÜRÜN", "URUN", "ÜRÜN ADI", "URUN ADI"])
        price_col = find_col(table, ["FİYAT", "FIYAT", "BİRİM FİYAT", "BIRIM FIYAT"])
        total_col = find_col(table, ["TUTAR", "TOPLAM", "SATIR TOPLAMI"])
        pdate_col = find_col(table, ["ÖDEME TARİHİ", "ODEME TARIHI", "TAHSİLAT TARİHİ", "TAHSILAT TARIHI"])
        card_col = find_col(table, ["KART", "KREDİ KARTI", "KREDI KARTI"])
        cash_col = find_col(table, ["NAKİT", "NAKIT"])
        remain_col = find_col(table, ["KALAN", "AÇIK", "ACIK", "BAKİYE", "BAKIYE"])
        note_col = find_col(table, ["NOT", "AÇIKLAMA", "ACIKLAMA"])
        if not prod_col or not total_col:
            issues.append(f"{sheet_name}: ürün/tutar kolonu bulunamadı, sekme atlandı.")
            continue
        firm_name = str(sheet_name).strip()
        for _, row in table.iterrows():
            product_raw = row.get(prod_col, "")
            total = parse_money_value(row.get(total_col))
            qty = parse_int_value(row.get(qty_col), 1) if qty_col else 1
            if qty <= 0:
                qty = 1
            price = parse_money_value(row.get(price_col)) if price_col else 0
            if price <= 0 and total > 0:
                price = total / qty
            if total <= 0 or not str(product_raw or "").strip():
                ignored += 1
                continue
            product_name, color_name = split_product_color(str(product_raw))
            card = parse_money_value(row.get(card_col)) if card_col else 0
            cash = parse_money_value(row.get(cash_col)) if cash_col else 0
            remain = parse_money_value(row.get(remain_col)) if remain_col else max(total - card - cash, 0)
            parsed.append({
                "firm_name": firm_name,
                "order_date": parse_date_value(row.get(date_col)) if date_col else today_str(),
                "payment_date": parse_date_value(row.get(pdate_col)) if pdate_col else "",
                "quantity": qty,
                "product_name": product_name,
                "color_name": color_name,
                "unit_price": float(price),
                "line_total": float(total),
                "card_paid": float(card),
                "cash_paid": float(cash),
                "remaining": float(remain),
                "note": str(row.get(note_col, "") or "").strip() if note_col else "",
                "source_sheet": firm_name,
            })
    result = {"parsed": parsed, "ignored": ignored, "issues": issues}
    if dry_run:
        return result
    imported_orders = 0; imported_items = 0; imported_payments = 0
    with closing(db_connect()) as conn:
        migrate_schema(conn)
        for rec in parsed:
            firm_id = get_or_create_firm(conn, rec["firm_name"])
            color_id = get_or_create_color(conn, rec["color_name"])
            product_id = get_or_create_product(conn, rec["product_name"], rec["unit_price"])
            order_no = next_order_no()
            paid = rec["card_paid"] + rec["cash_paid"]
            pay_status = "Bekliyor" if paid <= 0 else ("Ödendi" if paid + 0.01 >= rec["line_total"] else "Kısmi Ödendi")
            cur = conn.execute(
                """
                INSERT INTO orders (order_no, firm_id, firm_name_snapshot, branch_snapshot, order_date, delivery_date,
                                    status, payment_status, shipping_note, general_note, created_by, total_amount, created_at)
                VALUES (?, ?, ?, '', ?, '', 'Teslim Edildi', ?, '', ?, 'toplu_aktarim', ?, ?)
                """,
                (order_no, firm_id, rec["firm_name"], rec["order_date"], pay_status, f"Toplu aktarım: {rec['source_sheet']} | {rec['note']}", rec["line_total"], now_str()),
            )
            order_id = int(cur.lastrowid)
            conn.execute(
                """
                INSERT INTO order_items (order_id, product_id, product_name_snapshot, model_snapshot, color_snapshot,
                                         color_extra, quantity, unit_price, line_total, note)
                VALUES (?, ?, ?, '', ?, ?, ?, ?, ?, ?)
                """,
                (order_id, product_id, rec["product_name"], rec["color_name"], color_extra_for(rec["color_name"]), int(rec["quantity"]), rec["unit_price"], rec["line_total"], rec["note"]),
            )
            imported_orders += 1; imported_items += 1
            pdate = rec["payment_date"] or rec["order_date"]
            if rec["card_paid"] > 0:
                conn.execute("INSERT INTO payments (order_id, payment_date, amount, method, check_months, check_due_date, note, created_at) VALUES (?, ?, ?, 'Kredi Kartı', 0, '', ?, ?)", (order_id, pdate, rec["card_paid"], "Cari Excel aktarımı", now_str()))
                imported_payments += 1
            if rec["cash_paid"] > 0:
                conn.execute("INSERT INTO payments (order_id, payment_date, amount, method, check_months, check_due_date, note, created_at) VALUES (?, ?, ?, 'Nakit', 0, '', ?, ?)", (order_id, pdate, rec["cash_paid"], "Cari Excel aktarımı", now_str()))
                imported_payments += 1
        conn.commit()
    result.update({"imported_orders": imported_orders, "imported_items": imported_items, "imported_payments": imported_payments})
    return result


def importer_page():
    st.title("Cari / Ürün Toplu Aktarım")
    st.caption("Google Sheets veya Excel'deki cari kayıtları sisteme toplu işler; 0 TL satırları atlar ve aynı ürünleri otomatik eşler.")
    st.warning("Aktarım yapmadan önce Yedek / Ayarlar ekranından veritabanı yedeği indirmen önerilir.")
    mode = st.radio("Veri kaynağı", ["Excel yükle", "Google Sheet linkinden dene"], horizontal=True)
    workbook = None
    if mode == "Excel yükle":
        uploaded = st.file_uploader("Google Sheet'i Excel olarak indirip buraya yükle (.xlsx)", type=["xlsx"])
        if uploaded:
            try:
                workbook = read_import_workbook(uploaded, is_url=False)
            except Exception as exc:
                st.error(f"Excel okunamadı: {exc}")
    else:
        url = st.text_input("Google Sheet linki")
        if url and st.button("Linkten oku", use_container_width=True):
            try:
                workbook = read_import_workbook(url, is_url=True)
                st.session_state["import_workbook"] = workbook
            except Exception as exc:
                st.error(f"Google Sheet okunamadı: {exc}")
        workbook = st.session_state.get("import_workbook")
    if not workbook:
        st.info("En sağlam yöntem: Google Sheets > Dosya > İndir > Microsoft Excel (.xlsx), sonra buraya yükle.")
        return
    result = import_records_from_workbook(workbook, dry_run=True)
    parsed = result["parsed"]
    if result["issues"]:
        st.warning("Bazı sekmeler atlandı: " + " | ".join(result["issues"][:8]))
    if not parsed:
        st.error("Aktarılacak geçerli satır bulunamadı. 0 TL satırlar ve boş ürünler otomatik atlandı.")
        return
    df = pd.DataFrame(parsed)
    st.success(f"Ön izleme hazır: {len(df)} satış satırı bulundu, {result['ignored']} adet 0 TL/boş satır yok sayıldı.")
    c1, c2, c3, c4 = st.columns(4)
    with c1: card("Firma", str(df["firm_name"].nunique()), "Sekme/firma sayısı")
    with c2: card("Ürün", str(df["product_name"].map(norm_text).nunique()), "Aynı isimler eşlendi")
    with c3: card("Satış Satırı", str(len(df)), "0 TL hariç")
    with c4: card("Toplam Tutar", money(df["line_total"].sum()), "Aktarılacak ciro")
    preview = df[["source_sheet", "order_date", "product_name", "color_name", "quantity", "unit_price", "line_total", "card_paid", "cash_paid", "remaining", "note"]].copy()
    for col in ["unit_price", "line_total", "card_paid", "cash_paid", "remaining"]:
        preview[col] = preview[col].apply(money)
    st.dataframe(preview.head(300), use_container_width=True, hide_index=True, height=420)
    st.markdown("#### Ürün eşleştirme özeti")
    products = df.groupby([df["product_name"].map(norm_text), "product_name"], dropna=False).agg(
        adet=("quantity", "sum"), toplam=("line_total", "sum"), min_fiyat=("unit_price", "min"), max_fiyat=("unit_price", "max")
    ).reset_index(drop=False)
    product_view = products[["product_name", "adet", "min_fiyat", "max_fiyat", "toplam"]].copy()
    for col in ["min_fiyat", "max_fiyat", "toplam"]:
        product_view[col] = product_view[col].apply(money)
    st.dataframe(product_view, use_container_width=True, hide_index=True, height=250)
    confirm = st.checkbox("Ön izlemeyi kontrol ettim, bu kayıtları sisteme aktar")
    if confirm and st.button("Aktarımı Başlat", use_container_width=True):
        try:
            final = import_records_from_workbook(workbook, dry_run=False)
            st.success(f"Aktarım tamamlandı. Sipariş: {final.get('imported_orders',0)}, Kalem: {final.get('imported_items',0)}, Ödeme: {final.get('imported_payments',0)}")
            st.info("Dashboard / Firma Cari / Raporlar ekranlarından sonuçları kontrol edebilirsin.")
        except Exception as exc:
            st.error(f"Aktarım sırasında hata oluştu: {exc}")


def css():
    st.markdown(
        """
        <style>
        .stApp {
            background:
                radial-gradient(circle at top left, rgba(191, 149, 63, .18), transparent 30%),
                radial-gradient(circle at top right, rgba(47, 85, 151, .22), transparent 32%),
                linear-gradient(135deg, #05070d 0%, #07111f 46%, #0a1326 100%) !important;
            color: #f8fafc !important;
        }
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #0b1220 0%, #05070d 100%) !important;
            border-right: 1px solid rgba(212, 175, 55, .25);
        }
        h1, h2, h3, h4, label, p, span, div { color: #f8fafc; }
        h1 { font-size: 2.35rem !important; letter-spacing: -.04em; }
        .gh-subtitle { color:#b6c1d5; margin-top:-.6rem; margin-bottom:1.2rem; }
        .gh-card {
            border: 1px solid rgba(212,175,55,.46);
            background: linear-gradient(145deg, rgba(15,23,42,.96), rgba(7,10,17,.98));
            border-radius: 22px;
            padding: 24px;
            box-shadow: 0 22px 55px rgba(0,0,0,.42), inset 0 1px 0 rgba(255,255,255,.04);
            min-height: 132px;
        }
        .gh-card-title { color: #f4d67a; font-size:.92rem; font-weight:900; }
        .gh-card-value { color:#ffffff; font-size:2.1rem; font-weight:950; margin-top:.55rem; }
        .gh-card-note { color:#aab3c5; font-size:.86rem; margin-top:.3rem; }
        .gh-chip {
            display:inline-block; border:1px solid rgba(212,175,55,.42); border-radius:999px;
            padding:.35rem .7rem; background:rgba(212,175,55,.08); color:#f4d67a; font-weight:800;
        }
        div[data-testid="stMetricValue"] { color:#fff !important; }
        .stButton>button, .stDownloadButton>button {
            border: 1px solid rgba(212,175,55,.72) !important;
            background: linear-gradient(90deg, rgba(70,52,24,.98), rgba(10,17,31,.98)) !important;
            color: #fff !important;
            border-radius: 13px !important;
            font-weight: 800 !important;
            min-height: 2.75rem;
        }
        .stButton>button:hover, .stDownloadButton>button:hover { border-color:#f4d67a !important; filter:brightness(1.12); }
        .stTextInput input, .stTextArea textarea, .stNumberInput input, .stDateInput input,
        .stSelectbox div[data-baseweb="select"] > div {
            background: #272a35 !important;
            color: #fff !important;
            border-color: rgba(255,255,255,.13) !important;
        }
        .stDataFrame { border-radius: 16px; overflow:hidden; }
        [data-testid="stAlert"] { border-radius: 14px; }
        section[data-testid="stMain"] .block-container { padding-top: 3.5rem; max-width: 1540px; }
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
    st.markdown('<div class="gh-subtitle">Sipariş, cari, ödeme, ürün ve raporları tek panelden yönetin.</div>', unsafe_allow_html=True)
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
        pages = ["Dashboard", "Yeni Sipariş", "Siparişler", "Firmalar", "Ürünler", "Ödemeler", "Firma Cari", "Cari Aktarım", "Raporlar", "Yedek / Ayarlar"]
        page = st.radio("", pages, label_visibility="collapsed")
        st.divider()
        if st.button("Çıkış yap", use_container_width=True):
            st.session_state.clear()
            st.rerun()
    return page


def dashboard_page():
    st.title("Dashboard")
    st.markdown('<div class="gh-subtitle">Günday\'s Home genel sipariş ve tahsilat özeti</div>', unsafe_allow_html=True)
    orders = read_orders()
    total_orders = len(orders)
    active_orders = len(orders[~orders["status"].isin(["Teslim Edildi", "İptal Edildi"])]) if not orders.empty else 0
    valid = orders[orders["status"] != "İptal Edildi"].copy() if not orders.empty else pd.DataFrame()
    ciro = float(valid["total_amount"].sum()) if not valid.empty else 0
    tahsilat = float(valid["paid_amount"].sum()) if not valid.empty else 0
    outstanding = float(valid["remaining_amount"].clip(lower=0).sum()) if not valid.empty else 0
    c1, c2, c3, c4 = st.columns(4)
    with c1: card("Toplam Sipariş", str(total_orders), "Tüm kayıtlar")
    with c2: card("Aktif Sipariş", str(active_orders), "Teslim/iptal hariç")
    with c3: card("Ciro", money(ciro), "İptal hariç sipariş toplamı")
    with c4: card("Açık Bakiye", money(outstanding), "Tahsil edilmemiş tutar")
    st.divider()
    col1, col2 = st.columns([1.25, 1])
    with col1:
        st.subheader("Son Siparişler")
        if orders.empty:
            st.info("Henüz sipariş yok.")
        else:
            view = orders[["order_no", "firm_name", "branch", "order_date", "delivery_date", "status", "payment_status", "total_amount", "paid_amount", "remaining_amount"]].head(10).copy()
            for col in ["total_amount", "paid_amount", "remaining_amount"]:
                view[col] = view[col].apply(money)
            st.dataframe(view, use_container_width=True, hide_index=True, height=340)
    with col2:
        st.subheader("Durum Dağılımı")
        if orders.empty:
            st.info("Grafik için veri yok.")
        else:
            chart = orders.groupby("status", dropna=False)["id"].count().reset_index(name="adet")
            st.bar_chart(chart, x="status", y="adet", height=340)

    st.subheader("Vakti Yaklaşan Siparişler")
    if orders.empty:
        st.success("Yaklaşan teslim uyarısı yok.")
    else:
        today = pd.to_datetime(date.today())
        limit = pd.to_datetime(date.today() + timedelta(days=3))
        tmp = orders.copy()
        tmp["delivery_dt"] = pd.to_datetime(tmp["delivery_date"], errors="coerce")
        upcoming = tmp[
            (~tmp["status"].isin(["Teslim Edildi", "İptal Edildi"]))
            & tmp["delivery_dt"].notna()
            & (tmp["delivery_dt"] >= today)
            & (tmp["delivery_dt"] <= limit)
        ].copy()
        overdue = tmp[
            (~tmp["status"].isin(["Teslim Edildi", "İptal Edildi"]))
            & tmp["delivery_dt"].notna()
            & (tmp["delivery_dt"] < today)
        ].copy()
        if overdue.empty and upcoming.empty:
            st.success("Şu an kritik teslim uyarısı yok.")
        if not overdue.empty:
            st.error(f"Teslim tarihi geçmiş {len(overdue)} sipariş var.")
            view = overdue[["order_no", "firm_name", "branch", "delivery_date", "status", "remaining_amount"]].copy()
            view["remaining_amount"] = view["remaining_amount"].apply(money)
            st.dataframe(view, use_container_width=True, hide_index=True, height=200)
        if not upcoming.empty:
            st.warning(f"3 gün içinde teslim tarihi yaklaşan {len(upcoming)} sipariş var.")
            view = upcoming[["order_no", "firm_name", "branch", "delivery_date", "status", "remaining_amount"]].copy()
            view["remaining_amount"] = view["remaining_amount"].apply(money)
            st.dataframe(view, use_container_width=True, hide_index=True, height=220)


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
        return
    view = firms.copy()
    view["active"] = view["active"].map({1: "Aktif", 0: "Pasif"}).fillna("Aktif")
    view = view.rename(columns={"id":"ID", "firm_name":"Firma", "branch":"Şube", "contact_name":"Yetkili", "phone":"Telefon", "address":"Adres", "tax_no":"Vergi No", "tax_office":"Vergi Dairesi", "note":"Not", "active":"Durum", "created_at":"Kayıt Tarihi"})
    st.dataframe(safe_table(view, ["ID","Firma","Şube","Yetkili","Telefon","Adres","Vergi No","Vergi Dairesi","Durum","Kayıt Tarihi"]), use_container_width=True, hide_index=True, height=330)

    st.subheader("Firma Düzelt / Sil")
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
            eact = st.selectbox("Durum", [1, 0], index=0 if int(row["active"] or 1) == 1 else 1, format_func=lambda x: "Aktif" if x == 1 else "Pasif")
        if st.form_submit_button("Firma bilgisini güncelle", use_container_width=True):
            if not ef.strip():
                st.error("Firma adı boş olamaz.")
            else:
                run_sql(
                    "UPDATE firms SET firm_name=?, branch=?, contact_name=?, phone=?, address=?, tax_no=?, tax_office=?, note=?, active=? WHERE id=?",
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
                run_sql("UPDATE firms SET active=0 WHERE id=?", (int(selected),))
                st.warning("Firma geçmiş siparişlerde kullanılmış. Kalıcı silmek yerine pasife alındı.")
            else:
                run_sql("DELETE FROM firms WHERE id=?", (int(selected),))
                st.success("Firma silindi.")
            st.rerun()


def products_page():
    st.title("Ürünler ve Renkler")
    st.caption("Ürün kartlarını tek açın; renk farklarını ayrı yönetin")

    with st.expander("+ Yeni ürün ekle", expanded=True):
        with st.form("product_add"):
            c1, c2, c3 = st.columns(3)
            with c1:
                name = st.text_input("Ürün adı *")
                model = st.text_input("Model")
                category = st.text_input("Kategori")
            with c2:
                price = st.number_input("Ana birim fiyat", min_value=0.0, step=50.0, value=0.0)
                stock = st.number_input("Stok", min_value=0, step=1, value=0)
            with c3:
                note = st.text_area("Not", height=120)
            if st.form_submit_button("Ürünü kaydet", use_container_width=True):
                if not name.strip():
                    st.error("Ürün adı zorunlu.")
                else:
                    run_sql(
                        "INSERT INTO products (product_name, model, category, unit_price, stock, note, active, created_at) VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
                        (name.strip(), model.strip(), category.strip(), float(price), int(stock), note.strip(), now_str()),
                    )
                    st.success("Ürün kaydedildi.")
                    st.rerun()

    st.subheader("Renk Tercihleri ve Fiyat Farkları")
    colors = read_colors(False)
    cadd1, cadd2, cadd3 = st.columns([1.2, .8, 1.4])
    with st.form("color_add"):
        c1, c2, c3 = st.columns([1.2, .8, 1.4])
        with c1:
            color_name = st.text_input("Yeni renk adı")
        with c2:
            price_modifier = st.number_input("Ek ücret", step=50.0, value=0.0)
        with c3:
            color_note = st.text_input("Renk notu")
        if st.form_submit_button("Rengi kaydet", use_container_width=True):
            if not color_name.strip():
                st.error("Renk adı boş olamaz.")
            else:
                try:
                    run_sql(
                        "INSERT INTO product_colors (color_name, price_modifier, active, note, created_at) VALUES (?, ?, 1, ?, ?)",
                        (color_name.strip(), float(price_modifier), color_note.strip(), now_str()),
                    )
                    st.success("Renk kaydedildi.")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("Bu renk zaten kayıtlı.")
    if not colors.empty:
        color_view = colors.copy()
        color_view["active"] = color_view["active"].map({1: "Aktif", 0: "Pasif"}).fillna("Aktif")
        color_view["price_modifier"] = color_view["price_modifier"].apply(money)
        color_view = color_view.rename(columns={"id":"ID", "color_name":"Renk", "price_modifier":"Ek Ücret", "active":"Durum", "note":"Not", "created_at":"Kayıt Tarihi"})
        st.dataframe(safe_table(color_view, ["ID","Renk","Ek Ücret","Durum","Not","Kayıt Tarihi"]), use_container_width=True, hide_index=True, height=220)
        selected_color = st.selectbox("Düzeltilecek renk", list(colors["id"].astype(int)), format_func=lambda x: colors[colors["id"] == x].iloc[0]["color_name"])
        cr = colors[colors["id"] == selected_color].iloc[0]
        with st.form("color_edit"):
            e1, e2, e3, e4 = st.columns([1, .7, .7, 1])
            with e1:
                e_color = st.text_input("Renk adı", value=str(cr["color_name"] or ""))
            with e2:
                e_extra = st.number_input("Ek ücret", step=50.0, value=float(cr["price_modifier"] or 0))
            with e3:
                e_active = st.selectbox("Durum", [1, 0], index=0 if int(cr["active"] or 1) == 1 else 1, format_func=lambda x: "Aktif" if x == 1 else "Pasif")
            with e4:
                e_note = st.text_input("Not", value=str(cr["note"] or ""))
            if st.form_submit_button("Rengi güncelle", use_container_width=True):
                run_sql("UPDATE product_colors SET color_name=?, price_modifier=?, active=?, note=? WHERE id=?", (e_color.strip(), float(e_extra), int(e_active), e_note.strip(), int(selected_color)))
                st.success("Renk güncellendi.")
                st.rerun()

    products = read_products(False)
    st.subheader("Kayıtlı Ürünler")
    if products.empty:
        st.info("Henüz ürün yok.")
        return
    view = products.copy()
    view["active"] = view["active"].map({1: "Aktif", 0: "Pasif"}).fillna("Aktif")
    view["unit_price"] = view["unit_price"].apply(money)
    view = view.rename(columns={"id":"ID", "product_name":"Ürün", "model":"Model", "category":"Kategori", "unit_price":"Ana Fiyat", "stock":"Stok", "note":"Not", "active":"Durum", "created_at":"Kayıt Tarihi"})
    st.dataframe(safe_table(view, ["ID","Ürün","Model","Kategori","Ana Fiyat","Stok","Durum","Not","Kayıt Tarihi"]), use_container_width=True, hide_index=True, height=330)

    st.subheader("Ürün Düzelt / Sil")
    options = {int(r.id): f"U-{int(r.id):04d} - {product_label({'product_name': r.product_name, 'model': r.model, 'category': r.category})}" for r in products.itertuples(index=False)}
    selected = st.selectbox("Ürün seç", list(options.keys()), format_func=lambda x: options[x])
    row = products[products["id"] == selected].iloc[0]
    with st.form("product_edit"):
        c1, c2, c3 = st.columns(3)
        with c1:
            en = st.text_input("Ürün adı", value=str(row["product_name"] or ""))
            em = st.text_input("Model", value=str(row["model"] or ""))
            ecat = st.text_input("Kategori", value=str(row["category"] or ""))
        with c2:
            eprice = st.number_input("Ana birim fiyat", min_value=0.0, step=50.0, value=float(row["unit_price"] or 0))
            estock = st.number_input("Stok", min_value=0, step=1, value=int(row["stock"] or 0))
        with c3:
            enote = st.text_area("Not", value=str(row["note"] or ""), height=92)
            eact = st.selectbox("Durum", [1, 0], index=0 if int(row["active"] or 1) == 1 else 1, format_func=lambda x: "Aktif" if x == 1 else "Pasif")
        if st.form_submit_button("Ürün bilgisini güncelle", use_container_width=True):
            if not en.strip():
                st.error("Ürün adı boş olamaz.")
            else:
                run_sql(
                    "UPDATE products SET product_name=?, model=?, category=?, unit_price=?, stock=?, note=?, active=? WHERE id=?",
                    (en.strip(), em.strip(), ecat.strip(), float(eprice), int(estock), enote.strip(), int(eact), int(selected)),
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
                run_sql("UPDATE products SET active=0 WHERE id=?", (int(selected),))
                st.warning("Ürün geçmiş siparişlerde kullanılmış. Kalıcı silmek yerine pasife alındı.")
            else:
                run_sql("DELETE FROM products WHERE id=?", (int(selected),))
                st.success("Ürün silindi.")
            st.rerun()


def new_order_page():
    st.title("Yeni Sipariş")
    st.caption("Firma seçin, ürünü ve renk farkını belirleyin, siparişi kaydedin")
    firms = read_firms(True)
    products = read_products(True)
    colors = read_colors(True)
    if "cart" not in st.session_state:
        st.session_state["cart"] = []
    if firms.empty:
        st.warning("Sipariş oluşturmak için önce Firmalar bölümünden en az bir firma eklemelisin.")
        return
    if products.empty:
        st.warning("Sipariş oluşturmak için önce Ürünler bölümünden en az bir ürün eklemelisin.")
        return
    if colors.empty:
        st.warning("Sipariş oluşturmak için önce Ürünler > Renk Tercihleri kısmından en az bir renk eklemelisin.")
        return
    firm_options = {int(r.id): firm_label({"firm_name": r.firm_name, "branch": r.branch}) for r in firms.itertuples(index=False)}
    product_options = {int(r.id): product_label({"product_name": r.product_name, "model": r.model, "category": r.category}) for r in products.itertuples(index=False)}
    color_options = {int(r.id): color_label({"color_name": r.color_name, "price_modifier": r.price_modifier}) for r in colors.itertuples(index=False)}
    st.subheader("Sipariş Bilgileri")
    c1, c2, c3 = st.columns(3)
    with c1:
        firm_id = st.selectbox("Firma / Şube", list(firm_options.keys()), format_func=lambda x: firm_options[x])
        order_date_val = st.date_input("Sipariş alış tarihi", value=date.today())
    with c2:
        delivery_date_val = st.date_input("Teslim tarihi", value=date.today())
        status = st.selectbox("Sipariş durumu", STATUSES, index=0)
    with c3:
        payment_status = st.selectbox("Ödeme durumu", PAYMENT_STATUSES, index=0)
        created_by = st.text_input("Oluşturan", value=st.session_state.get("user", {}).get("username", "admin"))
    shipping_note = st.text_area("Sevkiyat notu", height=80)
    general_note = st.text_area("Genel not", height=80)

    st.subheader("Ürün Kalemi Ekle")
    c1, c2, c3, c4, c5 = st.columns([1.8, 1.2, .65, .85, .9])
    with c1:
        product_id = st.selectbox("Ürün", list(product_options.keys()), format_func=lambda x: product_options[x])
    product_row = products[products["id"] == product_id].iloc[0]
    is_gaming_chair = is_gaming_chair_text(" ".join([str(product_row.get("product_name", "")), str(product_row.get("model", "")), str(product_row.get("category", ""))]))
    if is_gaming_chair:
        game_norms = gaming_color_norms()
        filtered_colors = colors[colors["color_name"].apply(lambda x: norm_text(x) in game_norms)].copy()
        # Eksik renk olursa yine tüm renkleri göstererek siparişin bloklanmasını engelle.
        if not filtered_colors.empty:
            colors_for_select = filtered_colors
            st.caption("Bu ürün oyuncu koltuğu olarak algılandı. Renk listesi tüm marka oyuncu koltukları için sabitlendi: " + ", ".join(OYUNCU_KOLTUGU_COLORS))
        else:
            colors_for_select = colors
    else:
        colors_for_select = colors
    color_options = {int(r.id): color_label({"color_name": r.color_name, "price_modifier": r.price_modifier}) for r in colors_for_select.itertuples(index=False)}
    with c2:
        color_id = st.selectbox("Renk", list(color_options.keys()), format_func=lambda x: color_options[x])
    color_row = colors_for_select[colors_for_select["id"] == color_id].iloc[0]
    base_price = float(product_row["unit_price"] or 0)
    color_extra = float(color_row["price_modifier"] or 0)
    suggested_price = base_price + color_extra
    with c3:
        quantity = st.number_input("Adet", min_value=1, step=1, value=1)
    with c4:
        unit_price = st.number_input("Birim fiyat", min_value=0.0, step=50.0, value=float(suggested_price))
    line_total = int(quantity) * float(unit_price)
    with c5:
        st.markdown("**Satır toplamı**")
        st.markdown(f"### {money(line_total)}")
    st.caption(f"Ana fiyat: {money(base_price)} | Renk farkı: {money(color_extra)} | Önerilen fiyat: {money(suggested_price)}")
    item_note = st.text_input("Kalem notu")
    if st.button("+ Kalemi sepete ekle", use_container_width=True):
        st.session_state["cart"].append({
            "product_id": int(product_id),
            "product_name": str(product_row["product_name"]),
            "model": str(product_row["model"] or ""),
            "color": str(color_row["color_name"] or ""),
            "color_extra": float(color_extra),
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
        view = cart_df[["product_name", "model", "color", "color_extra", "quantity", "unit_price", "line_total", "note"]].copy()
        for col in ["color_extra", "unit_price", "line_total"]:
            view[col] = view[col].apply(money)
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


def payment_form_for_order(order_id: int, prefix: str = ""):
    orders = read_orders()
    row = orders[orders["id"] == int(order_id)].iloc[0]
    kalan = max(float(row["remaining_amount"] or 0), 0)
    with st.form(f"payment_form_{prefix}_{order_id}"):
        st.markdown(f"**Sipariş Toplamı:** {money(row['total_amount'])} | **Ödenen:** {money(row['paid_amount'])} | **Kalan:** {money(kalan)}")
        c1, c2, c3, c4 = st.columns([.8, .9, .9, .8])
        with c1:
            pdate = st.date_input("Ödeme tarihi", value=date.today(), key=f"pdate_{prefix}_{order_id}")
        with c2:
            amount = st.number_input("Ödenen tutar", min_value=0.0, step=100.0, value=float(kalan if kalan > 0 else 0), key=f"amount_{prefix}_{order_id}")
        with c3:
            method = st.selectbox("Yöntem", PAYMENT_METHODS, key=f"method_{prefix}_{order_id}")
        with c4:
            check_months = 0
            check_due = ""
            if method in ["Çek", "Senet"]:
                check_months = st.number_input("Vade ay", min_value=0, max_value=36, step=1, value=1, key=f"months_{prefix}_{order_id}")
                check_due = add_months(pdate, int(check_months)).isoformat()
            else:
                st.caption("Çek/senet değil")
        note = st.text_input("Ödeme notu", key=f"note_{prefix}_{order_id}")
        if method in ["Çek", "Senet"]:
            st.info(f"{method} vade tarihi yaklaşık: {check_due}")
        if st.form_submit_button("Ödemeyi kaydet", use_container_width=True):
            if amount <= 0:
                st.error("Ödeme tutarı 0'dan büyük olmalı.")
            else:
                add_payment(int(order_id), pdate.isoformat(), float(amount), method, int(check_months), check_due, note)
                st.success("Ödeme kaydedildi.")
                st.rerun()


def orders_page():
    st.title("Siparişler")
    st.caption("Siparişleri filtreleyin, durumu ve tahsilatı yönetin")
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
    view = filt[["id", "order_no", "firm_name", "branch", "order_date", "delivery_date", "status", "payment_status", "total_amount", "paid_amount", "remaining_amount", "shipping_note"]].copy()
    for col in ["total_amount", "paid_amount", "remaining_amount"]:
        view[col] = view[col].apply(money)
    st.dataframe(view, use_container_width=True, hide_index=True, height=360)

    st.subheader("Sipariş Detayı / Güncelleme / Tahsilat")
    options = {int(r.id): f"{r.order_no} - {r.firm_name} / {r.branch or '-'} - Kalan: {money(r.remaining_amount)}" for r in filt.itertuples(index=False)}
    if not options:
        st.warning("Filtreye uygun sipariş yok.")
        return
    selected = st.selectbox("Sipariş seç", list(options.keys()), format_func=lambda x: options[x])
    row = orders[orders["id"] == selected].iloc[0]
    m1, m2, m3, m4 = st.columns(4)
    with m1: card("Sipariş Toplamı", money(row["total_amount"]), row["order_no"])
    with m2: card("Ödenen", money(row["paid_amount"]), row["payment_status"])
    with m3: card("Kalan", money(row["remaining_amount"]), "Açık bakiye")
    with m4: card("Teslim Tarihi", str(row["delivery_date"] or "-"), row["status"])

    st.markdown("#### Ürün Kalemleri")
    items = read_order_items(int(selected))
    if not items.empty:
        item_view = items.copy()
        for col in ["color_extra", "unit_price", "line_total"]:
            item_view[col] = item_view[col].apply(money)
        st.dataframe(item_view, use_container_width=True, hide_index=True, height=240)

    st.markdown("#### Bu Siparişe Ödeme Gir")
    payment_form_for_order(int(selected), prefix="orders")

    st.markdown("#### Ödeme Geçmişi")
    pays = read_payments(order_id=int(selected))
    if pays.empty:
        st.info("Bu sipariş için ödeme yok.")
    else:
        pay_view = pays.copy()
        pay_view["amount"] = pay_view["amount"].apply(money)
        st.dataframe(pay_view[["id", "payment_date", "amount", "method", "check_months", "check_due_date", "note"]], use_container_width=True, hide_index=True, height=230)

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
    open_orders = orders[orders["status"] != "İptal Edildi"].copy()
    options = {int(r.id): f"{r.order_no} - {r.firm_name} - Kalan: {money(max(float(r.remaining_amount),0))}" for r in open_orders.itertuples(index=False)}
    order_id = st.selectbox("Ödeme yapılacak sipariş", list(options.keys()), format_func=lambda x: options[x])
    payment_form_for_order(int(order_id), prefix="payments")

    payments = read_payments()
    st.subheader("Ödeme Kayıtları")
    if payments.empty:
        st.info("Henüz ödeme yok.")
    else:
        view = payments.copy()
        view["amount"] = view["amount"].apply(money)
        st.dataframe(view[["id", "order_no", "firm_name", "payment_date", "amount", "method", "check_months", "check_due_date", "note"]], use_container_width=True, hide_index=True, height=330)
        opts = {int(r.id): f"{r.order_no} - {money(r.amount)} - {r.method} - {r.payment_date}" for r in payments.itertuples(index=False)}
        sel = st.selectbox("Silinecek ödeme kaydı", list(opts.keys()), format_func=lambda x: opts[x])
        if st.button("Seçili ödemeyi sil", use_container_width=True):
            delete_payment(int(sel))
            st.success("Ödeme silindi.")
            st.rerun()


def firm_cari_page():
    st.title("Firma Cari")
    st.caption("Firmaya ne verilmiş, ne tahsil edilmiş, açık bakiye ve ödeme yöntemleri")
    firms = read_firms(False)
    orders = read_orders()
    payments = read_payments()
    if firms.empty:
        st.info("Cari takip için önce firma eklemelisin.")
        return
    if orders.empty:
        st.info("Cari oluşması için önce sipariş girmelisin.")
        return

    valid = orders[orders["status"] != "İptal Edildi"].copy()
    summary = valid.groupby(["firm_id", "firm_name", "branch"], dropna=False).agg(
        siparis_adedi=("id", "count"), toplam_satis=("total_amount", "sum"), toplam_tahsilat=("paid_amount", "sum"), acik_bakiye=("remaining_amount", "sum")
    ).reset_index()
    if payments.empty:
        method_pivot = pd.DataFrame(columns=["firm_id"] + PAYMENT_METHODS)
    else:
        method_pivot = payments.pivot_table(index="firm_id", columns="method", values="amount", aggfunc="sum", fill_value=0).reset_index()
    cari = summary.merge(method_pivot, on="firm_id", how="left").fillna(0)
    for m in PAYMENT_METHODS:
        if m not in cari.columns:
            cari[m] = 0
    view = cari.copy()
    for col in ["toplam_satis", "toplam_tahsilat", "acik_bakiye"] + PAYMENT_METHODS:
        view[col] = view[col].apply(money)
    view = view.rename(columns={"firm_name":"Firma", "branch":"Şube", "siparis_adedi":"Sipariş", "toplam_satis":"Toplam Satış", "toplam_tahsilat":"Tahsilat", "acik_bakiye":"Açık Bakiye"})
    st.dataframe(view[["Firma", "Şube", "Sipariş", "Toplam Satış", "Tahsilat", "Açık Bakiye"] + PAYMENT_METHODS], use_container_width=True, hide_index=True, height=330)

    st.subheader("Firma Detayı")
    options = {int(r.id): firm_label({"firm_name": r.firm_name, "branch": r.branch}) for r in firms.itertuples(index=False)}
    selected = st.selectbox("Firma seç", list(options.keys()), format_func=lambda x: options[x])
    f_orders = orders[(orders["firm_id"] == int(selected)) & (orders["status"] != "İptal Edildi")].copy()
    f_payments = read_payments(firm_id=int(selected))
    c1, c2, c3, c4 = st.columns(4)
    with c1: card("Toplam Satış", money(f_orders["total_amount"].sum() if not f_orders.empty else 0), "İptal hariç")
    with c2: card("Tahsilat", money(f_orders["paid_amount"].sum() if not f_orders.empty else 0), "Tüm ödeme kayıtları")
    with c3: card("Açık Bakiye", money(f_orders["remaining_amount"].sum() if not f_orders.empty else 0), "Alacak")
    with c4: card("Sipariş Adedi", str(len(f_orders)), "Firma kayıtları")

    st.markdown("#### Firmanın Siparişleri")
    if f_orders.empty:
        st.info("Bu firmaya ait sipariş yok.")
    else:
        oview = f_orders[["order_no", "order_date", "delivery_date", "status", "payment_status", "total_amount", "paid_amount", "remaining_amount"]].copy()
        for col in ["total_amount", "paid_amount", "remaining_amount"]:
            oview[col] = oview[col].apply(money)
        st.dataframe(oview, use_container_width=True, hide_index=True, height=260)

    st.markdown("#### Ödeme Yöntemi Kırılımı")
    if f_payments.empty:
        st.info("Bu firmaya ait ödeme kaydı yok.")
    else:
        method_sum = f_payments.groupby("method", dropna=False)["amount"].sum().reset_index()
        mview = method_sum.copy(); mview["amount"] = mview["amount"].apply(money)
        st.dataframe(mview.rename(columns={"method":"Yöntem", "amount":"Tutar"}), use_container_width=True, hide_index=True, height=220)
        st.bar_chart(method_sum, x="method", y="amount", height=280)
        pay_view = f_payments.copy(); pay_view["amount"] = pay_view["amount"].apply(money)
        st.dataframe(pay_view[["order_no", "payment_date", "amount", "method", "check_months", "check_due_date", "note"]], use_container_width=True, hide_index=True, height=260)


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
    with c3: card("Açık Bakiye", money(valid_orders["remaining_amount"].clip(lower=0).sum()), "Tahsilat farkı")
    st.subheader("Firma Bazlı Satış")
    firm_report = valid_orders.groupby("firm_name", dropna=False).agg(siparis_adedi=("id", "count"), toplam_ciro=("total_amount", "sum"), toplam_tahsilat=("paid_amount", "sum"), acik=("remaining_amount", "sum")).reset_index()
    if not firm_report.empty:
        view = firm_report.copy()
        for col in ["toplam_ciro", "toplam_tahsilat", "acik"]:
            view[col] = view[col].apply(money)
        st.dataframe(view, use_container_width=True, hide_index=True, height=280)
        st.bar_chart(firm_report, x="firm_name", y="toplam_ciro", height=320)
    st.subheader("Ürün Bazlı Satış")
    items = df_query(
        """
        SELECT oi.product_name_snapshot AS product_name, oi.color_snapshot AS color, SUM(oi.quantity) AS toplam_adet, SUM(oi.line_total) AS toplam_tutar
        FROM order_items oi
        JOIN orders o ON o.id=oi.order_id
        WHERE o.status != 'İptal Edildi'
        GROUP BY oi.product_name_snapshot, oi.color_snapshot
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
    st.subheader("Veritabanı Kontrol")
    if st.button("Veritabanını onar / kolonları tamamla", use_container_width=True):
        with closing(db_connect()) as conn:
            migrate_schema(conn)
        st.success("Veritabanı kontrol edildi ve eksik kolonlar tamamlandı.")
        st.rerun()
    st.subheader("Yedek İndir")
    c1, c2 = st.columns(2)
    with c1:
        if DB_PATH.exists():
            st.download_button("SQLite veritabanı yedeğini indir", data=DB_PATH.read_bytes(), file_name=f"gundays_home_db_{today_str()}.db", mime="application/octet-stream", use_container_width=True)
    with c2:
        st.download_button("Excel yedeği indir", data=backup_excel_bytes(), file_name=f"gundays_home_yedek_{today_str()}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
    st.subheader("Veritabanı Geri Yükle")
    st.warning("Geri yükleme mevcut veritabanını değiştirir. Önce mevcut yedeği indirin.")
    uploaded = st.file_uploader(".db yedeği yükle", type=["db"])
    if uploaded and st.button("Yedeği geri yükle", use_container_width=True):
        backup = DATA_DIR / f"onceki_db_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        if DB_PATH.exists():
            shutil.copy(DB_PATH, backup)
        DB_PATH.write_bytes(uploaded.read())
        with closing(db_connect()) as conn:
            migrate_schema(conn)
        st.success("Veritabanı geri yüklendi. Uygulama yenileniyor.")
        st.rerun()
    st.subheader("Şifre Değiştir")
    with st.form("pass_change"):
        current = st.text_input("Mevcut şifre", type="password")
        new = st.text_input("Yeni şifre", type="password")
        new2 = st.text_input("Yeni şifre tekrar", type="password")
        if st.form_submit_button("Şifreyi değiştir", use_container_width=True):
            if not new or len(new) < 6:
                st.error("Yeni şifre en az 6 karakter olmalı.")
            elif new != new2:
                st.error("Yeni şifreler eşleşmiyor.")
            elif update_password(st.session_state["user"]["username"], current, new):
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
    if page == "Dashboard":
        dashboard_page()
    elif page == "Yeni Sipariş":
        new_order_page()
    elif page == "Siparişler":
        orders_page()
    elif page == "Firmalar":
        firms_page()
    elif page == "Ürünler":
        products_page()
    elif page == "Ödemeler":
        payments_page()
    elif page == "Firma Cari":
        firm_cari_page()
    elif page == "Cari Aktarım":
        importer_page()
    elif page == "Raporlar":
        reports_page()
    elif page == "Yedek / Ayarlar":
        settings_page()


if __name__ == "__main__":
    main()
