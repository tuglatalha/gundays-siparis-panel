# Gündays — Sipariş & Ciro Takip Sistemi

Google Sheets'e bağlı, Streamlit ile çalışan sipariş / teslimat / ciro takip paneli.

## Bu sistem ne yapar?
- Yeni sipariş girişi (firma, ürün, miktar, fiyat, sipariş/teslimat tarihi, durum)
- Hangi firmaya hangi gün teslimat yapılacağını gün gün gösteren bir takvim görünümü
- Ciro/gelir analizini firma ve ürün bazında grafiklerle gösterme
- Tüm veriler senin Google Sheets dosyanda saklanır — uygulama sadece bir arayüz

## ⚠️ Önemli güvenlik notu
Bu klasörde **gerçek Google servis hesabı anahtarı bulunmuyor** — bilerek koymadık.
`.streamlit/secrets.toml.example` sadece formatı gösteren bir şablondur. Gerçek anahtar
GitHub'a asla yüklenmemeli; aksi halde botlar tarafından dakikalar içinde bulunup
kötüye kullanılabilir. Gerçek değerleri Claude ile sohbetinde ayrıca verdik — onları
sadece **Streamlit Cloud'un Secrets bölümüne** yapıştıracaksın (adım 5).

## Klasör yapısı
```
gundays/
├── app.py                      # Ana sayfa (Genel Bakış)
├── pages/
│   ├── 1_📦_Siparisler.py      # Sipariş ekleme, arama, toplu düzenleme
│   ├── 2_🚚_Teslimatlar.py     # Teslimat takvimi
│   └── 3_💰_Ciro_Analizi.py    # Gelir analizi ve grafikler
├── utils/
│   ├── sheets.py                # Google Sheets okuma/yazma mantığı
│   └── styles.py                # Görsel tema
├── .streamlit/
│   ├── config.toml              # Renk teması
│   └── secrets.toml.example     # Şablon (gerçek anahtar YOK)
├── requirements.txt
├── .gitignore
└── README.md
```

## Kurulum adımları

### 1) Google Sheet'i servis hesabına paylaş
1. "Gündays sipariş takip" sheet'ini aç
2. Sağ üstten **Paylaş (Share)** butonuna tıkla
3. Şu e-postayı **Düzenleyen (Editor)** yetkisiyle ekle:
   ```
   gundays-streamlit@effective-fire-501612-q8.iam.gserviceaccount.com
   ```
4. Kaydet

Bu adım atlanırsa uygulama sheet'ine erişemez ve hata verir.

### 2) Google Cloud'da API'lerin açık olduğundan emin ol
Proje: `effective-fire-501612-q8` — Google Cloud Console'da şu iki API'nin
etkin olduğunu kontrol et (genelde zaten açıktır):
- Google Sheets API
- Google Drive API

### 3) GitHub'a yükle
1. GitHub'da yeni bir repository oluştur (Public veya Private, ikisi de olur —
   Private biraz daha güvenli)
2. Bu zip'i açtığında çıkan **tüm dosya ve klasörleri** (gizli `.streamlit` ve
   `.gitignore` dahil) repo'ya sürükle-bırak ile yükle
   - `.streamlit/secrets.toml` diye bir dosya zaten yok, endişelenme —
     `secrets.toml.example` var, o farklı ve zararsız bir şablon

### 4) Streamlit Cloud'da yayına al
1. https://share.streamlit.io adresine git, GitHub hesabınla giriş yap
2. "Create app" / "New app" → deponu seç → Main file path: `app.py`
3. Deploy etmeden önce **Advanced settings > Secrets** kısmına gel

### 5) Secrets'i yapıştır
Claude ile sohbette sana ayrıca verdiğimiz gerçek TOML içeriğini (gerçek
anahtarınla birlikte) buraya olduğu gibi yapıştır, sonra **Deploy**'a bas.
Uygulama zaten yayındaysa: app ayarları (sağ alt "⋮" menüsü) → Settings →
Secrets → içeriği yapıştır → Save (uygulama otomatik yeniden başlar).

### 6) Kontrol et
Uygulama birkaç dakika içinde açılır. **Siparişler** sayfasından bir test
siparişi ekleyip Google Sheet'ine "Siparisler" adında bir sekme düşüp
düşmediğini kontrol edebilirsin (ilk çalıştırmada otomatik oluşur).

## Temayı değiştirmek istersen
`.streamlit/config.toml` içindeki renk kodlarını değiştirmen yeterli.
`utils/styles.py` içindeki `DURUM_RENK` sözlüğü durum renklerini (Beklemede,
Yolda, Teslim Edildi vb.) kontrol eder.

## Nasıl çalışıyor (kısaca)
Tüm veriler tek bir **"Siparisler"** sekmesinde tutulur — Teslimatlar ve Ciro
Analizi sayfaları aynı veriyi farklı açılardan (tarihe göre gruplanmış, ciroya
göre özetlenmiş) gösterir. Bu sayede veri her yerde tutarlı kalır.

## Bir güvenlik hatırlatması (opsiyonel)
Bu private key Claude ile sohbet üzerinden paylaşıldığı için, sistemi kurduktan
sonra istersen Google Cloud Console → IAM & Admin → Service Accounts → ilgili
hesap → Keys kısmından yeni bir anahtar oluşturup eskisini silebilirsin. Zorunlu
değil ama iyi bir alışkanlıktır.
