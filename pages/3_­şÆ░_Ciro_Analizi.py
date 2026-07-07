import pandas as pd
import plotly.express as px
import streamlit as st
from datetime import date, timedelta

from utils.sheets import load_orders
from utils.styles import inject_custom_css, render_header, themed_plotly, turkce_ay_etiketi, CHART_PALETTE

st.set_page_config(page_title="Ciro Analizi | Gündays", page_icon="💰", layout="wide")
inject_custom_css()
render_header("💰 Ciro Analizi", "Gelirlerini firma, ürün ve zaman bazında incele")

try:
    df = load_orders()
except Exception as e:
    st.error("⚠️ Veriler yüklenemedi.")
    with st.expander("Hata detayı"):
        st.exception(e)
    st.stop()

df = df.dropna(subset=["Siparis_Tarihi"])

if df.empty:
    st.info("Henüz analiz edilecek sipariş yok.")
    st.stop()

secim = st.selectbox("Dönem", ["Bu Ay", "Geçen Ay", "Bu Yıl", "Tüm Zamanlar", "Özel Aralık"])
today = date.today()

if secim == "Bu Ay":
    mask = (df["Siparis_Tarihi"].dt.month == today.month) & (df["Siparis_Tarihi"].dt.year == today.year)
elif secim == "Geçen Ay":
    ay_basi = today.replace(day=1)
    gecen_ay_son_gun = ay_basi - timedelta(days=1)
    mask = (
        (df["Siparis_Tarihi"].dt.month == gecen_ay_son_gun.month)
        & (df["Siparis_Tarihi"].dt.year == gecen_ay_son_gun.year)
    )
elif secim == "Bu Yıl":
    mask = df["Siparis_Tarihi"].dt.year == today.year
elif secim == "Özel Aralık":
    dc1, dc2 = st.columns(2)
    baslangic = dc1.date_input("Başlangıç", value=today.replace(day=1))
    bitis = dc2.date_input("Bitiş", value=today)
    mask = (df["Siparis_Tarihi"].dt.date >= baslangic) & (df["Siparis_Tarihi"].dt.date <= bitis)
else:
    mask = pd.Series(True, index=df.index)

secili = df[mask]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Toplam Ciro", f"₺{secili['Toplam_Tutar'].sum():,.0f}")
c2.metric("Sipariş Sayısı", f"{len(secili)}")
ort = secili["Toplam_Tutar"].mean() if len(secili) else 0
c3.metric("Ortalama Sipariş", f"₺{ort:,.0f}")
if len(secili) and secili["Firma"].astype(bool).any():
    en_cok_firma = secili.groupby("Firma")["Toplam_Tutar"].sum().idxmax()
else:
    en_cok_firma = "-"
c4.metric("En Çok Ciro Yapan Firma", en_cok_firma)

st.divider()

if secili.empty:
    st.info("Seçilen dönemde veri yok.")
else:
    cc1, cc2 = st.columns(2)
    with cc1:
        st.markdown("#### Aylık Ciro")
        aylik = secili.copy()
        aylik["Ay"] = aylik["Siparis_Tarihi"].dt.to_period("M").astype(str)
        aylik_g = aylik.groupby("Ay")["Toplam_Tutar"].sum().reset_index().sort_values("Ay")
        aylik_g["AyEtiket"] = aylik_g["Ay"].apply(turkce_ay_etiketi)
        fig = px.bar(
            aylik_g, x="AyEtiket", y="Toplam_Tutar",
            category_orders={"AyEtiket": aylik_g["AyEtiket"].tolist()},
        )
        fig.update_traces(marker_color=CHART_PALETTE[0])
        st.plotly_chart(themed_plotly(fig), use_container_width=True)

    with cc2:
        st.markdown("#### Firma Bazında Dağılım")
        firma_g = secili.groupby("Firma")["Toplam_Tutar"].sum().sort_values(ascending=False).reset_index()
        fig2 = px.pie(
            firma_g, names="Firma", values="Toplam_Tutar", hole=0.5,
            color_discrete_sequence=CHART_PALETTE,
        )
        st.plotly_chart(themed_plotly(fig2), use_container_width=True)

    st.markdown("#### Ürün Bazında Satış")
    urun_g = (
        secili.groupby("Urun")
        .agg(Adet=("Miktar", "sum"), Ciro=("Toplam_Tutar", "sum"))
        .sort_values("Ciro", ascending=False)
        .reset_index()
    )
    fig3 = px.bar(urun_g, x="Urun", y="Ciro")
    fig3.update_traces(marker_color=CHART_PALETTE[1])
    st.plotly_chart(themed_plotly(fig3), use_container_width=True)

    st.markdown("#### Detaylı Döküm")
    st.dataframe(
        secili.sort_values("Siparis_Tarihi", ascending=False),
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

    csv = secili.to_csv(index=False).encode("utf-8-sig")
    st.download_button("⬇️ CSV olarak indir", csv, file_name="ciro_analizi.csv", mime="text/csv")
