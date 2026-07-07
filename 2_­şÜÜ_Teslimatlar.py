import pandas as pd
import streamlit as st
from datetime import date, timedelta

from utils.sheets import load_orders, save_all_orders, DURUM_SECENEKLERI
from utils.styles import inject_custom_css, render_header, durum_badge_html, DURUM_RENK, turkce_tarih

st.set_page_config(page_title="Teslimatlar | Gündays", page_icon="🚚", layout="wide")
inject_custom_css()
render_header("🚚 Teslimat Takvimi", "Hangi firmaya hangi gün teslimat yapacağını takip et")

try:
    df = load_orders()
except Exception as e:
    st.error("⚠️ Veriler yüklenemedi.")
    with st.expander("Hata detayı"):
        st.exception(e)
    st.stop()

if df.empty:
    st.info("Henüz sipariş yok.")
    st.stop()

aktif = df[(df["Durum"] != "Iptal Edildi") & df["Teslimat_Tarihi"].notna()]

secim = st.radio("Görünüm", ["Bugün", "Bu Hafta", "Bu Ay", "Tümü"], horizontal=True)
today = date.today()

if secim == "Bugün":
    gosterilecek = aktif[aktif["Teslimat_Tarihi"].dt.date == today]
elif secim == "Bu Hafta":
    hafta_sonu = today + timedelta(days=7)
    gosterilecek = aktif[
        (aktif["Teslimat_Tarihi"].dt.date >= today) & (aktif["Teslimat_Tarihi"].dt.date <= hafta_sonu)
    ]
elif secim == "Bu Ay":
    gosterilecek = aktif[
        (aktif["Teslimat_Tarihi"].dt.month == today.month) & (aktif["Teslimat_Tarihi"].dt.year == today.year)
    ]
else:
    gosterilecek = aktif

gosterilecek = gosterilecek.sort_values("Teslimat_Tarihi")

if gosterilecek.empty:
    st.info("Bu aralıkta planlanmış teslimat yok. 🎉")
else:
    for gun, grup in gosterilecek.groupby(gosterilecek["Teslimat_Tarihi"].dt.date):
        st.markdown(f"#### {turkce_tarih(gun)}")
        for _, row in grup.iterrows():
            renk = DURUM_RENK.get(row["Durum"], "#8992AC")
            miktar_str = f"{row['Miktar']:g}" if pd.notna(row["Miktar"]) else "-"
            st.markdown(
                f"""
                <div style="background:#171C33; border-left:3px dashed {renk};
                            border-radius:8px; padding:12px 16px; margin-bottom:10px;">
                    <strong>{row['Firma']}</strong> — {row['Urun']} ({miktar_str} adet)
                    &nbsp;{durum_badge_html(row['Durum'])}
                    <div style="color:#8992AC; font-size:0.85rem; margin-top:4px;">
                        Sipariş: {row['Siparis_ID']} · ₺{row['Toplam_Tutar']:,.2f}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

st.divider()
st.subheader("✏️ Durum / Teslimat Tarihi Güncelle")
st.caption("Firma ve ürün burada salt-okunurdur. Yeni sipariş eklemek için **Siparişler** sayfasını kullan.")

duzenle_cols = ["Siparis_ID", "Firma", "Urun", "Teslimat_Tarihi", "Durum"]
duzenlenen = st.data_editor(
    df[duzenle_cols],
    use_container_width=True,
    hide_index=True,
    column_config={
        "Siparis_ID": st.column_config.TextColumn("Sipariş ID", disabled=True),
        "Firma": st.column_config.TextColumn("Firma", disabled=True),
        "Urun": st.column_config.TextColumn("Ürün", disabled=True),
        "Teslimat_Tarihi": st.column_config.DateColumn("Teslimat Tarihi", format="DD.MM.YYYY"),
        "Durum": st.column_config.SelectboxColumn("Durum", options=DURUM_SECENEKLERI),
    },
    key="teslimat_editor",
)

if st.button("💾 Güncellemeleri Kaydet", type="primary"):
    tam_df = df.copy().set_index("Siparis_ID")
    guncel = duzenlenen.set_index("Siparis_ID")
    tam_df.update(guncel)
    tam_df = tam_df.reset_index()
    save_all_orders(tam_df)
    st.success("Güncellendi ✅")
    st.rerun()
