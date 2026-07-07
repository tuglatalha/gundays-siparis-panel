"""
Gorsel tema ve yardimci goruntuleme fonksiyonlari.

Tasarim yonu: "ticaret defteri / manifesto" hissi - lacivert zemin + pirinc/altin
vurgu rengi. Basliklarda serif (Fraunces), govde ve verilerde sans-serif (Inter).
"""
import pandas as pd
import streamlit as st

# --- Renk paleti -----------------------------------------------------------
BG = "#0E1220"
CARD_BG = "#171C33"
PRIMARY = "#C99A45"       # pirinc/altin - imza rengi
TEXT = "#EAE7DD"          # sicak beyaz (parsomen)
MUTED = "#8992AC"         # soguk gri-mavi

DURUM_RENK = {
    "Beklemede": "#7C87A8",
    "Hazirlaniyor": "#3FA8B8",
    "Yolda": "#C99A45",
    "Teslim Edildi": "#6FA98A",
    "Iptal Edildi": "#B85C56",
}

CHART_PALETTE = ["#C99A45", "#3FA8B8", "#6FA98A", "#7C87A8", "#B85C56"]

AYLAR_TR = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
            "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
AYLAR_KISA_TR = ["Oca", "Şub", "Mar", "Nis", "May", "Haz",
                 "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"]
GUNLER_TR = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]


def inject_custom_css():
    st.markdown(f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700&family=Inter:wght@400;500;600;700&display=swap');

    html, body, [class*="css"] {{
        font-family: 'Inter', sans-serif;
    }}
    h1, h2, h3, h4, .app-header h1 {{
        font-family: 'Fraunces', serif !important;
        letter-spacing: -0.3px;
    }}

    div[data-testid="stMetric"] {{
        background: {CARD_BG};
        border: 1px solid rgba(201,154,69,0.18);
        border-radius: 12px;
        padding: 18px 20px 14px 20px;
        box-shadow: 0 4px 20px rgba(0,0,0,0.28);
    }}
    div[data-testid="stMetricLabel"] {{
        color: {MUTED} !important;
        font-size: 0.82rem;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }}
    div[data-testid="stMetricValue"] {{
        font-weight: 700;
        color: {TEXT};
    }}

    .app-header {{
        padding: 4px 0 18px 0;
        border-bottom: 1px solid rgba(201,154,69,0.28);
        margin-bottom: 24px;
    }}
    .app-header h1 {{
        font-weight: 700;
        margin-bottom: 2px;
        font-size: 2rem;
    }}
    .app-header p {{
        color: {MUTED};
        margin-top: 0;
        font-size: 0.95rem;
    }}

    .badge {{
        display: inline-block;
        padding: 3px 12px;
        border-radius: 6px;
        font-size: 0.72rem;
        font-weight: 700;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        vertical-align: middle;
    }}

    section[data-testid="stSidebar"] {{
        border-right: 1px solid rgba(201,154,69,0.15);
    }}
    section[data-testid="stSidebar"] h2 {{
        font-size: 1.3rem;
    }}

    div[data-testid="stForm"] {{
        background: {CARD_BG};
        border: 1px solid rgba(201,154,69,0.15);
        border-radius: 14px;
        padding: 8px 6px;
    }}
    </style>
    """, unsafe_allow_html=True)


def render_header(title: str, subtitle: str = ""):
    st.markdown(
        f'<div class="app-header"><h1>{title}</h1><p>{subtitle}</p></div>',
        unsafe_allow_html=True,
    )


def durum_badge_html(durum: str) -> str:
    renk = DURUM_RENK.get(durum, MUTED)
    return (
        f'<span class="badge" style="background:{renk}22; color:{renk}; '
        f'border:1px solid {renk}55;">{durum}</span>'
    )


def themed_plotly(fig):
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font_color=TEXT,
        font_family="Inter, sans-serif",
        margin=dict(l=10, r=10, t=36, b=10),
        legend=dict(bgcolor="rgba(0,0,0,0)"),
        title_font_size=15,
        title_font_family="Fraunces, serif",
    )
    fig.update_xaxes(gridcolor="rgba(255,255,255,0.06)", title=None)
    fig.update_yaxes(gridcolor="rgba(255,255,255,0.06)", title=None)
    return fig


def turkce_tarih(gun) -> str:
    """date/Timestamp -> '6 Temmuz 2026, Pazartesi' formatinda Turkce metin."""
    ts = pd.Timestamp(gun)
    return f"{ts.day} {AYLAR_TR[ts.month - 1]} {ts.year}, {GUNLER_TR[ts.weekday()]}"


def turkce_ay_etiketi(period_str: str) -> str:
    """'2026-07' -> 'Tem 2026'"""
    yil, ay = period_str.split("-")
    return f"{AYLAR_KISA_TR[int(ay) - 1]} {yil}"
