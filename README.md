# Günday's Home Sipariş Takip - Temiz Başlangıç V2 Fix

Bu sürüm Google Sheets kullanmaz. Veriler uygulamanın kendi SQLite veritabanına kaydedilir.

## İlk giriş

- Kullanıcı adı: `admin`
- Şifre: `admin123`

## Bu sürümde düzelen kritik konu

Bazı eski/yarım kurulmuş Streamlit veritabanlarında firma ve ürün tablolarında eksik kolon kalabiliyordu. Bu sürüm açılışta veritabanı şemasını kontrol eder, eksik kolonları tamamlar ve firma/ürün tablolarında KeyError oluşmasını engeller.

## GitHub'a yüklenecek dosyalar

- `streamlit_app.py`
- `requirements.txt`
- `runtime.txt`
- `README.md`
- `.streamlit/config.toml` varsa yüklenebilir.
