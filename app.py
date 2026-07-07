import streamlit as st
import plotly.express as px
from datetime import date, timedelta

from utils.sheets import load_orders
from utils.styles import inject_custom_css, render_header, themed_plotly, turkce_ay_etiketi, PRIMARY

st.set_page_config(
    page_title="Gündays | Sipariş & Ciro Sistemi",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_custom_css()

with st.sidebar:
    st.markdown("## 📊 Gündays")
    st.caption("Sipariş, teslimat ve ciro takibi")
    st.divider()
    if st.button("🔄 Verileri Yenile", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

render_header("Genel Bakış", "Siparişlerin, teslimatların ve cironun özeti")

try:
    df = load_orders()
except Exception as e:
    st.error(
        "⚠️ Google Sheets'e bağlanılamadı. `secrets` ayarlarını ve servis "
        "hesabının sheet'e **Düzenleyen (Editor)** olarak eklendiğini kontrol et."
    )
    with st.expander("Hata detayı"):
        st.exception(e)
    st.stop()

if df.empty:
    st.info("👋 Henüz hiç sipariş yok. Soldaki menüden **Siparişler** sayfasına giderek ilk siparişini ekleyebilirsin.")
    st.stop()

today = date.today()
bu_ay = df[
    df["Siparis_Tarihi"].notna()
    & (df["Siparis_Tarihi"].dt.month == today.month)
    & (df["Siparis_Tarihi"].dt.year == today.year)
]
bekleyen = df[df["Durum"].isin(["Beklemede", "Hazirlaniyor", "Yolda"])]
bugun_teslimat = df[df["Teslimat_Tarihi"].dt.date == today]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Bu Ayki Ciro", f"₺{bu_ay['Toplam_Tutar'].sum():,.0f}")
c2.metric("Toplam Sipariş", f"{len(df)}")
c3.metric("Bekleyen Teslimat", f"{len(bekleyen)}")
c4.metric("Bugünkü Teslimat", f"{len(bugun_teslimat)}")

st.write("")
col_chart, col_list = st.columns([3, 2])

with col_chart:
    st.markdown("#### Aylık Ciro Trendi")
    aylik = df.dropna(subset=["Siparis_Tarihi"]).copy()
    if aylik.empty:
        st.caption("Grafik için yeterli veri yok.")
    else:
        aylik["Ay"] = aylik["Siparis_Tarihi"].dt.to_period("M").astype(str)
        aylik_g = aylik.groupby("Ay")["Toplam_Tutar"].sum().reset_index().sort_values("Ay")
        aylik_g["AyEtiket"] = aylik_g["Ay"].apply(turkce_ay_etiketi)
        fig = px.bar(
            aylik_g, x="AyEtiket", y="Toplam_Tutar",
            category_orders={"AyEtiket": aylik_g["AyEtiket"].tolist()},
        )
        fig.update_traces(marker_color=PRIMARY)
        st.plotly_chart(themed_plotly(fig), use_container_width=True)

with col_list:
    st.markdown("#### Yaklaşan Teslimatlar")
    yaklasan = df[
        df["Teslimat_Tarihi"].notna()
        & (df["Teslimat_Tarihi"].dt.date >= today)
        & (df["Teslimat_Tarihi"].dt.date <= today + timedelta(days=7))
        & (~df["Durum"].isin(["Teslim Edildi", "Iptal Edildi"]))
    ].sort_values("Teslimat_Tarihi")

    if yaklasan.empty:
        st.caption("Önümüzdeki 7 günde planlanmış teslimat yok.")
    else:
        st.dataframe(
            yaklasan[["Teslimat_Tarihi", "Firma", "Urun", "Durum"]],
            use_container_width=True,
            hide_index=True,
            column_config={
                "Teslimat_Tarihi": st.column_config.DateColumn("Tarih", format="DD.MM.YYYY"),
                "Firma": "Firma",
                "Urun": "Ürün",
                "Durum": "Durum",
            },
        )
