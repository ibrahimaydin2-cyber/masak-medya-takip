import json
import os
import smtplib
import time
import urllib.parse
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import feedparser
from google import genai
from google.genai import types

# --- AYARLAR ---
RECIPIENT_EMAIL = os.environ.get("RECIPIENT_EMAIL", "ibrahim.aydin2@turkcell.com.tr")
SMTP_USER = os.environ["SMTP_USER"]
SMTP_PASSWORD = os.environ["SMTP_PASSWORD"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

SEEN_FILE = "seen_news.json"
TR_TZ = timezone(timedelta(hours=3))

# Hedef 20 Haber Sitesi
TARGET_DOMAINS = [
    "aa.com.tr", "dha.com.tr", "iha.com.tr", "hurriyet.com.tr", "sozcu.com.tr",
    "milliyet.com.tr", "sabah.com.tr", "haberturk.com", "ntv.com.tr", "cnnturk.com",
    "trthaber.com", "t24.com.tr", "cumhuriyet.com.tr", "ensonhaber.com", "mynet.com",
    "haberler.com", "ekonomim.com", "bloomberght.com", "odatv.com", "halktv.com.tr"
]

# Paycell için Kırmızı Alarm (Yüksek Öncelik) Kategorileri
HIGH_PRIORITY_CODES = {"SK-02", "SK-22", "SK-23", "SK-28", "SK-29", "SK-30", "SK-35", "SK-37"}

# 38 MASAK Kategorisini Kapsayan Gruplanmış RSS Arama Sorguları
# (Adli tetikleyicilerle birleştirilerek gürültü azaltılır)
SEARCH_QUERIES = [
    # SK-01, SK-02, SK-28, SK-29, SK-30 (Ödeme Kuruluşu Kritik Riskleri)
    '("pos tefeciliği" OR "tefeci operasyonu" OR "lisanssız ödeme" OR "hesap kiralama" OR "IBAN kiralama" OR "yasa dışı fatura ödeme" OR "hawala") when:1d',
    # SK-22 (Yasa Dışı Bahis ve Kumar)
    '("yasa dışı bahis" OR "yasadışı bahis" OR "sanal bahis" OR "bahis operasyonu" OR "7258 sayılı kanun") when:1d',
    # SK-23, SK-35, SK-36 (Terörizmin Finansmanı, Malvarlığı Dondurma, KİS)
    '("terörizmin finansmanı" OR "terörün finansmanı" OR "mal varlığı donduruldu" OR "malvarlığı dondurma" OR "kitle imha silahı" OR "7262 sayılı kanun") when:1d',
    # SK-37, SK-11, SK-12, SK-21, SK-26 (MASAK, Kara Para, Vergi, SPK, Bankacılık, Hileli İflas)
    '("MASAK" OR "kara para aklama" OR "suç gelirlerini aklama" OR "naylon fatura" OR "borsa manipülasyonu" OR "SPK suç duyurusu" OR "hileli iflas" OR "BDDK") when:1d',
    # SK-10, SK-17, SK-32 (Bilişim, Dolandırıcılık, Saadet Zinciri)
    '("nitelikli dolandırıcılık" OR "siber operasyon" OR "sibergöz" OR "sazan sarmalı" OR "saadet zinciri" OR "ponzi" OR "kripto para vurgunu") when:1d',
    # SK-13, SK-14, SK-15, SK-16, SK-24, SK-25 (Yolsuzluk, Sahtecilik, İhale, SGK, Sigorta)
    '("rüşvet operasyonu" OR "zimmet" OR "ihaleye fesat" OR "evrakta sahtecilik" OR "sahte para operasyonu" OR "sigorta dolandırıcılığı" OR "SGK dolandırıcılığı") when:1d',
    # SK-03, SK-04, SK-05, SK-18, SK-38 (Fuhuş, Göçmen, Uyuşturucu, Organ, Müstehcenlik)
    '("uyuşturucu operasyonu" OR "göçmen kaçakçılığı" OR "insan ticareti" OR "fuhuş operasyonu" OR "organ ticareti" OR "müstehcenlik operasyonu" OR "çocuk müstehcenliği" OR "TCK 226") when:1d',
    # SK-06, SK-07, SK-08, SK-09, SK-27, SK-31 (Kaçakçılık Türleri)
    '("silah kaçakçılığı" OR "tarihi eser kaçakçılığı" OR "gümrük kaçakçılığı" OR "hayali ihracat" OR "altın kaçakçılığı" OR "akaryakıt kaçakçılığı" OR "kaçak sigara") when:1d',
    # SK-19, SK-20, SK-33, SK-34 (Organize Suç, Yağma, STK Suiistimali, İzinsiz Bağış)
    '("organize suç örgütü" OR "şantaj çetesi" OR "yağma çetesi" OR "dernek yolsuzluğu" OR "izinsiz yardım toplama" OR "sahte bağış") when:1d',
]

MASAK_CATEGORIES_TEXT = """
SK-01: Tefecilik
SK-02: POS tefeciliği
SK-03: Fuhuşa teşvik veya aracılık etmek
SK-04: Göçmen kaçakçılığı / insan ticareti
SK-05: Uyuşturucu madde ticareti
SK-06: Silah ve mühimmat kaçakçılığı
SK-07: Tarihi eser kaçakçılığı
SK-08: Gümrük kaçakçılığı / hayali ihracat
SK-09: Kıymetli maden ve taşların kaçakçılığı
SK-10: Bilişim suçları
SK-11: Vergi kaçakçılığı ve vergi kaçırma
SK-12: Sermaye piyasalarına ilişkin suçlar
SK-13: Yolsuzluk ve kamu görevlileriyle ilgili suçlar (rüşvet, irtikap, zimmet)
SK-14: Resmî / özel evrakta sahtecilik
SK-15: Para ve kıymetli evrak dolandırıcılığı / sahteciliği
SK-16: Sigorta dolandırıcılığı / poliçe sahteciliği
SK-17: Dolandırıcılık
SK-18: Organ ve doku ticareti
SK-19: Tehdit / şantaj / cebir ve adam kaçırma / organize suç örgütü
SK-20: Mal varlığına karşı suçlar (hırsızlık, yağma)
SK-21: Hileli iflas
SK-22: Yasa dışı bahis ve kumar oynatma/oynanmasına aracılık etme
SK-23: Terörizmin finansmanı
SK-24: İhaleye fesat karıştırma
SK-25: Sosyal güvenlik mevzuatına aykırılıklar
SK-26: Bankacılık mevzuatına ilişkin suçlar
SK-27: Akaryakıt kaçakçılığı
SK-28: Yasa dışı fatura ödeme merkezi faaliyetleri
SK-29: Lisanssız ödeme ve elektronik para hizmetlerinde bulunma
SK-30: Başkası hesabına işlem yapıldığının beyan edilmemesi (hesap/IBAN kiralama)
SK-31: Sigara, alkol ve tütün mamulleri kaçakçılığı
SK-32: Piramit satış sistemleri (saadet zincirleri)
SK-33: Sivil toplum kuruluşlarının suiistimali
SK-34: Yasadışı yardım ve bağış toplama
SK-35: Mal varlığının dondurulması kararının ihlali
SK-36: Kitle imha silahlarının yayılmasının finansmanı
SK-37: Yükümlülüklere Aykırı Hareket Edilmesi / Kara Para Aklama
SK-38: Müstehcenlik
"""


def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"urls": [], "last_run": ""}


def save_seen(seen_data):
    # Dosyanın büyümesini önlemek için son 1500 linki tut
    seen_data["urls"] = seen_data["urls"][-1500:]
    seen_data["last_run"] = datetime.now(TR_TZ).strftime("%Y-%m-%d %H:%M:%S")
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(seen_data, f, ensure_ascii=False, indent=2)


def fetch_candidate_news(seen_urls):
    candidates = []
    seen_in_run = set(seen_urls)

    for query in SEARCH_QUERIES:
        encoded_q = urllib.parse.quote(query)
        rss_url = f"https://news.google.com/rss/search?q={encoded_q}&hl=tr&gl=TR&ceid=TR:tr"
        feed = feedparser.parse(rss_url)

        for entry in feed.entries:
            source_href = getattr(entry, "source", {}).get("href", "").lower()
            source_title = getattr(entry, "source", {}).get("title", "Bilinmiyor")
            link = entry.get("link", "")
            title = entry.get("title", "")

            # Sadece belirlenen 20 haber sitesinden gelenleri al
            if not any(domain in source_href for domain in TARGET_DOMAINS):
                continue

            if link in seen_in_run:
                continue

            seen_in_run.add(link)
            candidates.append({
                "id": len(candidates) + 1,
                "source": source_title,
                "title": title,
                "link": link,
                "published": entry.get("published", "")
            })

        time.sleep(1)  # Google RSS hız limitine takılmamak için kısa bekleme

    return candidates


def analyze_with_gemini(candidates):
    if not candidates:
        return []

    client = genai.Client(api_key=GEMINI_API_KEY)
    results = []

    # Haberleri 40'arlı paketler halinde Gemini'ye analiz ettir
    batch_size = 40
    for i in range(0, len(candidates), batch_size):
        batch = candidates[i:i + batch_size]
        news_text = "\n".join(
            [f"[{c['id']}] Kaynak: {c['source']} | Başlık: {c['title']}" for c in batch]
        )

        prompt = f"""
Sen bir Ödeme ve Elektronik Para Kuruluşunda (Paycell) çalışan kıdemli MASAK Uyum (Compliance) Uzmanısın.
Aşağıdaki haber başlıklarını incele. Amacımız müşteri kabul (KYC) ve şüpheli işlem (ŞİB) süreçlerinde risk teşkil eden, hakkında operasyon, gözaltı, tutuklama, soruşturma, malvarlığı dondurma, adli/idari yaptırım veya ciddi suç iddiası bulunan GERÇEK veya TÜZEL kişileri tespit etmektir.

ELEME KURALLARI:
- Siyasi polemikler, genel ekonomik yorumlar, spor/magazin dedikoduları, sadece yasa tasarısı tartışmaları veya somut adli/suç vakası içermeyen genel haberleri KESİNLİKLE ELE (çıktıya dahil etme).
- Aynı olayı anlatan birden fazla haber varsa sadece en kapsamlı olan 1 tanesini seç.
- Sadece somut bir suç operasyonu, adli işlem, yaptırım veya kara para/suç geliri riski barındıran haberleri seç.

MASAK KATEGORİLERİ:
{MASAK_CATEGORIES_TEXT}

HABERLER:
{news_text}

Çıktıyı SADECE aşağıdaki JSON formatında bir liste olarak döndür:
[
  {{
    "id": 1,
    "sk_code": "SK-22",
    "sk_name": "Yasa dışı bahis ve kumar oynatma/oynanmasına aracılık etme",
    "entities": "Haberde geçen şüpheli şahıs veya şirket adları (başlıkta açık isim yoksa 'Başlıkta isim belirtilmemiş - Detay incelenmeli' yaz)",
    "reason": "1 cümlelik uyum riski özeti"
  }}
]
Eğer riskli haber yoksa boş liste [] döndür.
"""
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1,
            ),
        )

        try:
            parsed = json.loads(response.text)
            id_map = {c["id"]: c for c in batch}
            for item in parsed:
                orig = id_map.get(item.get("id"))
                if orig:
                    item["source"] = orig["source"]
                    item["title"] = orig["title"]
                    item["link"] = orig["link"]
                    item["is_high_priority"] = item.get("sk_code") in HIGH_PRIORITY_CODES
                    results.append(item)
        except Exception as e:
            print(f"JSON parse hatası: {e}")

    return results


def build_email_html(findings, total_scanned):
    today_str = datetime.now(TR_TZ).strftime("%d.%m.%Y")
    high_prio = [f for f in findings if f["is_high_priority"]]
    normal_prio = [f for f in findings if not f["is_high_priority"]]

    def make_rows(items, badge_color):
        rows = ""
        for item in items:
            rows += f"""
            <tr>
                <td style="padding:10px; border:1px solid #ddd; white-space:nowrap;">
                    <span style="background:{badge_color}; color:#fff; padding:3px 7px; border-radius:4px; font-weight:bold; font-size:12px;">
                        {item['sk_code']}
                    </span><br>
                    <small style="color:#555;">{item['sk_name']}</small>
                </td>
                <td style="padding:10px; border:1px solid #ddd;">
                    <strong>{item['entities']}</strong>
                </td>
                <td style="padding:10px; border:1px solid #ddd;">
                    <a href="{item['link']}" style="color:#0056b3; text-decoration:none; font-weight:bold;">{item['title']}</a><br>
                    <small style="color:#666;">Kaynak: {item['source']} — {item['reason']}</small>
                </td>
            </tr>
            """
        return rows

    body_content = ""
    if not findings:
        body_content = "<p style='color:#2e7d32; font-weight:bold;'>Son 24 saatte taranan 20 haber sitesinde MASAK uyum riski taşıyan yeni bir vaka tespit edilmedi.</p>"
    else:
        if high_prio:
            body_content += f"""
            <h3 style="color:#c62828; border-bottom:2px solid #c62828; padding-bottom:5px;">
                Yüksek Öncelikli / Kırmızı Alarm ({len(high_prio)} Haber)
            </h3>
            <table style="border-collapse:collapse; width:100%; font-size:13px; margin-bottom:25px;">
                <thead>
                    <tr style="background:#fdecea; text-align:left;">
                        <th style="padding:10px; border:1px solid #ddd;">MASAK Kodu</th>
                        <th style="padding:10px; border:1px solid #ddd;">Geçen Şahıs / Kurum</th>
                        <th style="padding:10px; border:1px solid #ddd;">Haber ve Uyum Özeti</th>
                    </tr>
                </thead>
                <tbody>{make_rows(high_prio, '#c62828')}</tbody>
            </table>
            """
        if normal_prio:
            body_content += f"""
            <h3 style="color:#1565c0; border-bottom:2px solid #1565c0; padding-bottom:5px;">
                Diğer Şüphe Kategorileri ({len(normal_prio)} Haber)
            </h3>
            <table style="border-collapse:collapse; width:100%; font-size:13px;">
                <thead>
                    <tr style="background:#e8f0fe; text-align:left;">
                        <th style="padding:10px; border:1px solid #ddd;">MASAK Kodu</th>
                        <th style="padding:10px; border:1px solid #ddd;">Geçen Şahıs / Kurum</th>
                        <th style="padding:10px; border:1px solid #ddd;">Haber ve Uyum Özeti</th>
                    </tr>
                </thead>
                <tbody>{make_rows(normal_prio, '#1565c0')}</tbody>
            </table>
            """

    return f"""
    <html>
    <body style="font-family: Arial, sans-serif; color:#222; line-height:1.5;">
        <h2 style="color:#0b3d91;">Günlük MASAK Olumsuz Medya (Adverse Media) Raporu — {today_str}</h2>
        <p style="font-size:13px; color:#555;">
            Taranan kaynak: <strong>20 Haber Sitesi</strong> | İncelenen aday haber: <strong>{total_scanned}</strong> | Raporlanan riskli vaka: <strong>{len(findings)}</strong>
        </p>
        {body_content}
        <hr style="margin-top:30px; border:none; border-top:1px solid #eee;">
        <p style="font-size:11px; color:#888;">
            Bu rapor MASAK ŞİB Rehberi (MSK-RHB-ŞİB-006-2) Tablo 8 kategorileri baz alınarak otomatik oluşturulmuştur.
        </p>
    </body>
    </html>
    """


def send_email(html_content, findings_count):
    today_str = datetime.now(TR_TZ).strftime("%d.%m.%Y")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[MASAK Medya Tarama] {today_str} — {findings_count} Riskli Haber Tespit Edildi"
    msg["From"] = SMTP_USER
    msg["To"] = RECIPIENT_EMAIL
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    # Gmail SMTP (Kurumsal SMTP kullanılacaksa sunucu/port buradan değiştirilebilir)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_USER, RECIPIENT_EMAIL, msg.as_string())
    print(f"E-posta başarıyla gönderildi -> {RECIPIENT_EMAIL}")


def main():
    seen_data = load_seen()
    candidates = fetch_candidate_news(seen_data["urls"])
    print(f"Toplam aday haber sayısı: {len(candidates)}")

    findings = analyze_with_gemini(candidates)
    print(f"Yapay zekâ elemesi sonrası riskli haber sayısı: {len(findings)}")

    html = build_email_html(findings, len(candidates))
    send_email(html, len(findings))

    # Taranan linkleri kaydet ki ertesi gün tekrar gelmesin
    seen_data["urls"].extend([c["link"] for c in candidates])
    save_seen(seen_data)


if __name__ == "__main__":
    main()
