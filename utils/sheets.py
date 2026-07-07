"""
Google Sheets baglanti ve veri okuma/yazma islemleri.

Tum siparis verisi tek bir 'Siparisler' sekmesinde tutulur; uygulamanin
diger sayfalari (Teslimatlar, Ciro Analizi) ayni veriyi farkli sekillerde
filtreleyip gosterir. Sekme yoksa uygulama ilk acilista otomatik olusturur.
"""
import gspread
import pandas as pd
import streamlit as st

SHEET_NAME = "Siparisler"

COLUMNS = [
    "Siparis_ID",
    "Firma",
    "Urun",
    "Miktar",
    "Birim_Fiyat",
    "Toplam_Tutar",
    "Siparis_Tarihi",
    "Teslimat_Tarihi",
    "Durum",
    "Notlar",
]

DURUM_SECENEKLERI = ["Beklemede", "Hazirlaniyor", "Yolda", "Teslim Edildi", "Iptal Edildi"]


@st.cache_resource(show_spinner=False)
def get_client():
    if "gcp_service_account" not in st.secrets:
        raise RuntimeError(
            "Secrets ayarlanmamış görünüyor. Streamlit Cloud'da "
            "'Settings > Secrets' kısmına gerekli bilgileri ekle (bkz. README.md)."
        )
    creds_dict = dict(st.secrets["gcp_service_account"])
    return gspread.service_account_from_dict(creds_dict)


@st.cache_resource(show_spinner=False)
def get_spreadsheet():
    if "SPREADSHEET_ID" not in st.secrets:
        raise RuntimeError("SPREADSHEET_ID secrets içinde tanımlı değil.")
    client = get_client()
    return client.open_by_key(st.secrets["SPREADSHEET_ID"])


def get_or_create_worksheet():
    sh = get_spreadsheet()
    try:
        ws = sh.worksheet(SHEET_NAME)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=SHEET_NAME, rows=1000, cols=len(COLUMNS))
        ws.update(values=[COLUMNS], range_name="A1")
        return ws

    first_row = ws.row_values(1)
    if not first_row:
        ws.update(values=[COLUMNS], range_name="A1")
    return ws


@st.cache_data(ttl=45, show_spinner="Veriler yükleniyor...")
def load_orders() -> pd.DataFrame:
    ws = get_or_create_worksheet()
    records = ws.get_all_records()
    df = pd.DataFrame(records)

    for col in COLUMNS:
        if col not in df.columns:
            df[col] = None
    df = df[COLUMNS].copy()

    df["Miktar"] = pd.to_numeric(df["Miktar"], errors="coerce").fillna(0)
    df["Birim_Fiyat"] = pd.to_numeric(df["Birim_Fiyat"], errors="coerce").fillna(0)
    df["Toplam_Tutar"] = df["Miktar"] * df["Birim_Fiyat"]
    df["Siparis_Tarihi"] = pd.to_datetime(df["Siparis_Tarihi"], errors="coerce", dayfirst=True)
    df["Teslimat_Tarihi"] = pd.to_datetime(df["Teslimat_Tarihi"], errors="coerce", dayfirst=True)
    df["Durum"] = (
        df["Durum"].astype(str)
        .replace({"": "Beklemede", "nan": "Beklemede", "None": "Beklemede"})
    )
    df["Notlar"] = df["Notlar"].fillna("").astype(str).replace("nan", "")
    df["Firma"] = df["Firma"].fillna("").astype(str)
    df["Urun"] = df["Urun"].fillna("").astype(str)
    df["Siparis_ID"] = df["Siparis_ID"].astype(str)

    return df.reset_index(drop=True)


def _sonraki_id(df: pd.DataFrame) -> str:
    if df.empty:
        return "SP-0001"
    nums = pd.to_numeric(df["Siparis_ID"].astype(str).str.extract(r"(\d+)")[0], errors="coerce")
    max_num = int(nums.max()) if nums.notna().any() else 0
    return f"SP-{max_num + 1:04d}"


def append_order(firma, urun, miktar, birim_fiyat, siparis_tarihi, teslimat_tarihi, durum, notlar=""):
    ws = get_or_create_worksheet()
    df = load_orders()
    new_id = _sonraki_id(df)
    toplam = float(miktar) * float(birim_fiyat)
    values = [
        new_id, firma, urun, miktar, birim_fiyat, toplam,
        siparis_tarihi.strftime("%Y-%m-%d"),
        teslimat_tarihi.strftime("%Y-%m-%d"),
        durum, notlar,
    ]
    ws.append_row(values, value_input_option="USER_ENTERED")
    st.cache_data.clear()
    return new_id


def save_all_orders(df: pd.DataFrame):
    """data_editor'den donen tam tabloyu sheet'e geri yazar (tam guncelleme)."""
    ws = get_or_create_worksheet()
    out = df.copy().reset_index(drop=True)

    # Bos/eksik Siparis_ID'leri doldur (data_editor'de yeni eklenen satirlar icin)
    mevcut = out["Siparis_ID"].astype(str)
    nums = pd.to_numeric(mevcut.str.extract(r"(\d+)")[0], errors="coerce")
    sonraki = int(nums.max()) + 1 if nums.notna().any() else 1
    for idx in out.index:
        sid = str(out.at[idx, "Siparis_ID"]).strip()
        if sid == "" or sid.lower() in ("nan", "none"):
            out.at[idx, "Siparis_ID"] = f"SP-{sonraki:04d}"
            sonraki += 1

    out["Miktar"] = pd.to_numeric(out["Miktar"], errors="coerce").fillna(0)
    out["Birim_Fiyat"] = pd.to_numeric(out["Birim_Fiyat"], errors="coerce").fillna(0)
    out["Toplam_Tutar"] = out["Miktar"] * out["Birim_Fiyat"]
    out["Siparis_Tarihi"] = pd.to_datetime(out["Siparis_Tarihi"], errors="coerce").dt.strftime("%Y-%m-%d")
    out["Teslimat_Tarihi"] = pd.to_datetime(out["Teslimat_Tarihi"], errors="coerce").dt.strftime("%Y-%m-%d")
    out["Durum"] = out["Durum"].fillna("Beklemede").replace("", "Beklemede")
    out["Notlar"] = out["Notlar"].fillna("")

    out = out[COLUMNS].fillna("")
    out = out.astype(str).replace("NaT", "").replace("nan", "")

    ws.clear()
    ws.update(values=[COLUMNS] + out.values.tolist(), range_name="A1")
    st.cache_data.clear()
