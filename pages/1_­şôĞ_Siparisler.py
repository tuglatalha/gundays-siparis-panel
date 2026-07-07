import streamlit as st
from datetime import date

from utils.sheets import load_orders, append_order, save_all_orders, DURUM_SECENEKLERI
from utils.styles import inject_custom_css, render_header

st.set_page_config(page_title="Siparişler | Gündays", page_icon="📦", layout="wide")
inject_custom_css()
render_header("📦 Siparişler", "Yeni sipariş ekle, ara ve düzenle")

try:
    df = load_orders()
except Exception as e:
    st.error("⚠️ Veriler yüklenemedi. Sheet bağlantısını kontrol et.")
    with st.expander("Hata detayı"):
        st.exception(e)
    st.stop()

with st.expander("➕ Yeni Sipariş Ekle", expanded=df.empty):
    with st.form("yeni_siparis_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        firma = c1.text_input("Firma Adı *")
        urun = c2.text_input("Ürün *")

        c3, c4, c5 = st.columns(3)
        miktar = c3.number_input("Miktar", min_value=0.0, step=1.0, value=1.0)
        birim_fiyat = c4.number_input("Birim Fiyat (₺)", min_value=0.0, step=1.0, value=0.0)
        durum = c5.selectbox("Durum", DURUM_SECENEKLERI)

        c6, c7 = st.columns(2)
        siparis_tarihi = c6.date_input("Sipariş Tarihi", value=date.today())
        teslimat_tarihi = c7.date_input("Teslimat Tarihi", value=date.today())

        notlar = st.text_area("Notlar (opsiyonel)", height=70)

        st.markdown(f"**Toplam Tutar: ₺{miktar * birim_fiyat:,.2f}**")
        submitted = st.form_submit_button("💾 Siparişi Kaydet", use_container_width=True, type="primary")

        if submitted:
            if not firma.strip() or not urun.strip():
                st.warning("Firma adı ve ürün alanları zorunludur.")
            else:
                new_id = append_order(
                    firma.strip(), urun.strip(), miktar, birim_fiyat,
                    siparis_tarihi, teslimat_tarihi, durum, notlar.strip(),
                )
                st.success(f"✅ Sipariş eklendi: {new_id}")
                st.rerun()

st.divider()
st.subheader("🔍 Ara ve Filtrele")

if df.empty:
    st.caption("Henüz sipariş yok.")
else:
    fc1, fc2, fc3 = st.columns(3)
    firma_secenekleri = sorted([f for f in df["Firma"].dropna().unique().tolist() if f])
    firma_filter = fc1.multiselect("Firma", firma_secenekleri)
    durum_filter = fc2.multiselect("Durum", DURUM_SECENEKLERI)
    arama = fc3.text_input("Ürün / not içinde ara")

    goster = df.copy()
    if firma_filter:
        goster = goster[goster["Firma"].isin(firma_filter)]
    if durum_filter:
        goster = goster[goster["Durum"].isin(durum_filter)]
    if arama:
        m = (
            goster["Urun"].str.contains(arama, case=False, na=False)
            | goster["Notlar"].str.contains(arama, case=False, na=False)
        )
        goster = goster[m]

    st.dataframe(
        goster.sort_values("Siparis_Tarihi", ascending=False),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Siparis_ID": "Sipariş ID",
            "Firma": "Firma",
            "Urun": "Ürün",
            "Miktar": "Miktar",
            "Birim_Fiyat": st.column_config.NumberColumn("Birim Fiyat", format="₺%.2f"),
            "Toplam_Tutar": st.column_config.NumberColumn("Toplam Tutar", format="₺%.2f"),
            "Siparis_Tarihi": st.column_config.DateColumn("Sipariş Tarihi", format="DD.MM.YYYY"),
            "Teslimat_Tarihi": st.column_config.DateColumn("Teslimat Tarihi", format="DD.MM.YYYY"),
            "Durum": "Durum",
            "Notlar": "Notlar",
        },
    )
    st.caption(f"{len(goster)} kayıt gösteriliyor (toplam {len(df)})")

st.divider()
st.subheader("✏️ Toplu Düzenle")
st.caption(
    "Bu tablo **tüm** siparişleri gösterir (filtre uygulanmaz). Satır silmek için satırı "
    "seçip çöp kutusu simgesine, yeni satır eklemek için en alttaki boş satıra tıkla. "
    "Bitince altındaki butonla kaydet."
)

edited = st.data_editor(
    df,
    use_container_width=True,
    hide_index=True,
    num_rows="dynamic",
    column_config={
        "Siparis_ID": st.column_config.TextColumn("Sipariş ID", disabled=True, help="Otomatik atanır"),
        "Firma": st.column_config.TextColumn("Firma"),
        "Urun": st.column_config.TextColumn("Ürün"),
        "Miktar": st.column_config.NumberColumn("Miktar"),
        "Birim_Fiyat": st.column_config.NumberColumn("Birim Fiyat", format="₺%.2f"),
        "Toplam_Tutar": st.column_config.NumberColumn("Toplam Tutar", disabled=True, format="₺%.2f", help="Otomatik hesaplanır"),
        "Siparis_Tarihi": st.column_config.DateColumn("Sipariş Tarihi", format="DD.MM.YYYY"),
        "Teslimat_Tarihi": st.column_config.DateColumn("Teslimat Tarihi", format="DD.MM.YYYY"),
        "Durum": st.column_config.SelectboxColumn("Durum", options=DURUM_SECENEKLERI),
        "Notlar": st.column_config.TextColumn("Notlar"),
    },
    key="siparis_editor",
)

if st.button("💾 Değişiklikleri Google Sheets'e Kaydet", type="primary"):
    save_all_orders(edited)
    st.success("Kaydedildi ✅")
    st.rerun()
