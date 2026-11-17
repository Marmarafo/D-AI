# D-AI PR2 planı

Durum: **PR2-A (üç kavramın ayrılması) bitti**, diğer kalemler sırada.

## Değişmez kural: üç kavram asla karışmaz

| Kavram | Soru | Alan | Nerede |
|---|---|---|---|
| Kaynak güvenilirliği | Kaynağa genel olarak ne kadar güvenilebilir? | `source_reliability` | referans başına (`trust/score.py`) |
| Kanıt gücü | Bu alıntı bu ifadeyi ne kadar destekliyor? | `evidence_strength` (+ `strength_signals`) | alıntı başına (`synthesis/strength.py`) |
| İddia değerlendirmesi | Eldeki kanıtlar iddia hakkında ne gösteriyor? | `evidence_balance`, `status` | ifade başına (`synthesis/confidence.py`) |

- Birleştirme tek yerde yapılır: bağımsız grup ağırlığı = `source_reliability × evidence_strength`,
  sonra `evidence_balance`. Çıktıda üçü ayrı kalır.
- `evidence_balance` doğruluk olasılığı **değildir**. Eski `confidence` ve `trust` alanları kaldırıldı.
- JSON şeması `dai.result/2`. Eski (`/1`) denetim kayıtları `dai audit` ile hâlâ okunur.
- `evidence_strength` sezgiseldir (iddia türü × soru ilgisi × konum cümlesine yakınlık), kalibre edilmedi.

## Sıradaki kalemler

| Öncelik | Kalem | Not |
|---|---|---|
| Kritik | Termux'ta gerçek çalıştırma | Cihazda sen çalıştırmalısın; ben ağa/Termux'a erişemiyorum |
| Kritik | Gerçek internet kaynaklarıyla test | Aynı sebep; test sonuçlarını bana yapıştır |
| Yüksek | Türkçe iddia çıkarımı, gerçek metin | `stem()` 5 karakterlik önek; en zayıf halka |
| Yüksek | Kaynak puanı kalibrasyonu | Etiketli küçük küme gerekir |
| Orta | Farklı ifadeli aynı iddialar | Şu an sözcüksel eşleşme |
| Orta | Lisans seçimi | Karar sende |

v0.2 hedefleri (arama alaklılığı, bağımsız kaynak gruplama, sayısal bağlam) bu kalemlerin içine dağılır.
