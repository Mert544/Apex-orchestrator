# Apex — Ar-Ge 4 Raporu (≈38. tur · 2026-07-03)

> **Kıyas ekseni:** Ar-Ge 3 (≈36. tur, 2026-07-02) → **bugün (≈38. tur)**. Bir önceki rapor
> kapsam-katlama dönemini anlatıyordu; bu rapor tek günde beş push'luk bir **güven-derinleşme +
> geliştirme-hızı** dönemini anlatır. Tüm sayılar bu oturumda koşulmuş komutlardan
> (grade / north-star / readiness ölçümü / pytest collect / gate logları); origin doğrulamalı.

---

## 0. Tek cümle

Ar-Ge 3 "kapsam katlandı, A+ 100 ilk kez" demişti; **Ar-Ge 4'ün cümlesi:** aynı disiplin bir güne
sıkıştı — 96. objektif + dört actionability flip'i + **yayında canlı-doğrulanmış 8 gizli hatanın
çekişmeli süreçle bulunup kapanması** + dalga-döngüsünün kendisinin ürünleşmesi (repo-içi
içerik-anahtarlı kapı) — hepsi tam-yeşil kapılarla origin'de, A+ 100/100 hiç düşmeden.

---

## 1. Manşet KPI'lar — Ar-Ge 3'ten bugüne delta

| Metrik | Ar-Ge 3 (≈36. tur) | **Bugün (≈38. tur)** | Delta |
|---|---:|---:|---|
| **CONCRETE objektif** | 50 | **50** | sabit (bu dönem derinleşme dönemiydi) |
| **Toplam objektif** | 95 | **96** (`dedup-guarded-return`) | +1 — TIDY 45→46 |
| Çevrimdışı test (collect) | 26.421 | **26.695** | +274 (rails/fix0/W100/P4/araç testleri) |
| Öz-not | A+ 100 (ilk kez) | **A+ 100 — korunuyor** | dalga ortası 95'e düştü, dedup ailesine `_load_and_resolve` çıkarımıyla geri kazanıldı |
| **Actionability (fix_actionability)** | 14/44 (%31.8) | **18/44 (%40.9)** | W98: 4 design_task satırı kanıtlı lander'lara — spec tahminiyle BİREBİR |
| Denetçi (north-star) | PASS 50/95 | **PASS 50/96, drift=False** | korundu |
| Yayında bilinen sessiz-bozulma yolu | bilinmiyordu | **0** (8 bulundu, 8'i kapandı) | fix0 — aşağıda |
| Tam kapı maliyeti (restart) | ~35-60 dk baştan | **yalnız değişen chunk (~4 dk)** | içerik-anahtarlı checkpoint |
| Push başına kapı sayısı | 1 dalga = 1 kapı | **1 batch (3-4 iş kolu) = 1 kapı** | yeni kadans (patron direktifi) |

---

## 2. Ar-Ge 3'ten bu yana inen bloklar (5 push, tek gün)

**(a) 96. objektif — `dedup-guarded-return` (sentinel projeksiyonu):** dedup ailesinin SON
kontrol-akışı basamağı (guard-return + canlı düşüş; Ar-Ge 3 tablo satırı "dedup return-aralığı
reddi" BÖYLECE KAPANDI). Kesin-atama rayı, super/__class__ reddi, 26+6 test, 30 bilinçli pin.

**(b) W97 — 9 çekişmeli-doğrulanmış soundness rail'i:** 23-ajanlık kırmızı-takım workflow'u
dedup ailesinde 9 gerçek delik doğruladı (yapısal kimlik, cross-module rebind, çok-satır string,
closure, görünmez binding, builtin gölgeleme ×2, sentinel kaçışı, async) → hepsi refuse-yönlü
kapandı, 36+5 regresyon testi. Hiçbir iddia çürütülmedi.

**(c) W98 — actionability flip'leri:** `_FACT_ACTIONS`'ta 4 satır design_task→kanıtlı lander
(dependency-hub/symbol-hub→cover_gaps, entrypoint/confluence→strengthen_tests), plan-zamanı
`_covergaps_unserviceable` dürüstlük probu; ölçülen 14/44→18/44. Apex'in KENDİSİNDE 2
anında-inebilir somut katkı çıktı (objectives/_base.py + stub_synthesis.py karakterizasyonu).

**(d) Verim+hızlandırma paketi (patron isteği, ürünleşen süreç):** repo-içi `scripts/gate_runner.py`
(içerik-anahtarlı checkpoint: app+scripts+conftest+chunk'ın kendi test dosyaları; --tip self-heal;
push-on-green), `scripts/preflight.py` (yalnız etkilenen testler: 1.122 test 7,5 dk — tam kapının
~%20'si), `scripts/session_pulse.py` (oturum-açılış tek bakış), context-fragile-tests raporu.
32 testli; **gate21 bu runner'ın ilk canlı koşusuydu ve uçtan uca çalıştı.**

**(e) BATCH-1 (yeni kadans ilk meyvesi) — W99-fix0 + W100 + P4, TEK kapı:**
- **fix0 (GÜVEN-TEMELİ):** W99 spec süreci (7-ajan keşif + 6-ajan onarım; çift-şüpheci refute-default
  ×2 tur) spec'i iki kez reddederken YAYINDAKİ kodda **8 gerçek hata** canlı probe'la doğruladı —
  hepsi önce/sonra kanıtıyla kapandı: örtüşen span sessiz bozulması (P0: `f(0)` 7→None, blockers
  boş!), `case p0:` yakalama deseni (P0), global/nonlocal store sapması, bayat-şablon operatör
  drift'i, çok-satır bytes VE near-dup şeridinde str re-indent bozulması, docstring silinmesi,
  çok-baytlı karakter dilimleme (GERÇEK ONARIM: eski yanlış-red artık doğru iniyor). 30 test.
- **W100:** guarded-return kesin-atama rayında ses-koruyan daraltma — inşacı ajan brief'in yanlış
  öncülünü (`live_in ⇒ kesin-bağlı`) yakalayıp sağlam formu (`live_in ∩ (param ∪ prelude-kesin)`)
  uyguladı; sınır çekişmeli pinli.
- **P4:** 8 duvar-saati-kırılgan testin 7'si deterministik invariant'a (işlem sayacı / Event/join /
  utime-pin); 8 CPU-yakıcı altında yeşil; asla-zayıflatma mutasyon kontrolü canlı.

---

## 3. Ar-Ge yöntemi olarak kanıtlanan: çekişmeli spec hattı

Bu dönemin metodolojik bulgusu: **keşif→spec→çift-şüpheci-refute→onarım→tekrar** hattı yalnız
spec kalitesi değil, **yayındaki gizli hataların en verimli avcısı** çıktı — 8 hatanın 8'i de bir
YENİ özellik spec'ine şüphecilerin saldırısı sırasında, canlı repro zorunluluğuyla bulundu.
Maliyet: ~1.3M subagent token / 13 ajan; getiri: müşteri projesini sessizce bozabilecek 2 P0 dahil
8 kapanış. Bu hat artık standart: W99a spec v3 şu an aynı hattan geçiyor (3. tur).

---

## 4. Dürüst eksik yönler — güncel tablo (Ar-Ge 3 satırlarının akıbetiyle)

| Eksik | Durum / Kanıt | Yön |
|---|---|---|
| **Actionability %40.9** (Ar-Ge 3: %32 → kısmen kapandı) | 44 adımın 18'i otonom; 17 design_task kaldı (operatör satırları kanıtlı recommend-only) | A39 devamı: kalan satırlar için W98 deseni (probe + honest-downgrade); tavan ~%50-55 civarı dürüst sınır olabilir |
| **dedup return-reddi** (Ar-Ge 3 satırı) | ✅ KAPANDI — 96. objektif | W99a/b: Constant-only parameterized × {total, guarded} (spec v3 şüpheci turunda); W99c: Name-hole'lar (açıkça ertelendi) |
| **Soğuk-başlangıç görünürlüğü** (Ar-Ge 3'ten taşınan, DOKUNULMADI) | taze klonda trackrecord/proof boş | `apex quickstart` tek-komut demosu — hâlâ en kısa go-to-market işi |
| **%6 analiz-dışı** (taşınan) | ts_driver.js 1551 LOC + ApexJavaDriver.java 1249 LOC kendi analizinin dışında | JS/Java profilleyicileri kendi sürücülerine çevirmek (dogfood) |
| **protocol_scaffold hotspot** (taşınan) | complexity 69, test-linkage 0 görünüyor | test_linker'ı objective-suite'lere genişlet |
| **3 test-siz modül** | bugünkü grade: 3/~618 (W98'in bulduğu 2 aday dahil — anında inebilir) | W98'in kendi çıktısı: cover_gaps ile kapat (dogfood fırsatı) |
| **YENİ: near-dup şeridi kısmi-ray paritesi** | fix0 near-dup'a 4 rail kabloladı; ailenin TAM per-run seti (`occurrence_rail_reason`) orada koşmuyor | W99a matcher taşınırken tek-kaynak ray seti (spec v3 kapsamında) |
| **YENİ: apply_rename bayatlık ön-koşulu** | şüpheci kalıntısı: çok-uygulamalı kampanya dizilerinde plan-bayatlığı tam denetlenmedi | hedefli denetim + gerekiyorsa plan-fingerprint ön-koşulu |
| **AÇIK KARAR: refs/backup sigorta-ref push'u** | `--insurance` bayrağı hazır, VARSAYILAN KAPALI | patron onayı bekliyor (reset-kayıplarının kesin kapanışı) |

---

## 5. Süreç-verimi bulguları (patronun sorusuna ölçülü cevap)

- **İsraf kaynağı test değil, kapı-tekrarıydı:** bu oturumda 21 tam kapı koşusunun çoğu reset/kırmızı
  restart'ıydı. İçerik-anahtarlı checkpoint + preflight + titrek-test kurutması üçlüsü tekrar
  maliyetini yapısal olarak düşürdü (restart ~35-60 dk → ~4 dk; dalga-arası doğrulama ~7,5 dk).
- **Batch kadansı:** BATCH-1'de 4 iş kolu tek kapıyla çıktı (eski usulle 3-4 kapı). Push başına
  kapı=1 kuralı (asla sahte yeşil yok) DEĞİŞMEDİ — kapı sayısı değil, kapı-başına-iş arttı.
- **Kapı iki kez gerçek hata yakaladı** (yerel süpürmelerin kaçırdığı pin'ler) — kapının kendisi
  Ar-Ge kalite enstrümanı olarak çalışıyor; kaldırılacak yağ değil.

---

## 6. Sıradaki önemli işler (öncelik sırasıyla)

1. **W99a** — `dedup-parameterized-total-return` (96→97): Constant-only paylaşılan matcher —
   spec v3 çift-şüpheci turunda; sağ çıkarsa inşa hazır. Değer: fark-yalnız-sabit near-dup'lar
   (en yaygın sınıf) return'lü bloklarda da inebilir olur.
2. **W99b** — guarded varyantı (97→98); W99c — Name-hole'lar (tam kapsam analiziyle, ayrı dalga).
3. **Soğuk-başlangıç `apex quickstart`** — go-to-market'in en kısa yolu; Ar-Ge 3'ten beri açık.
4. **3 test-siz modülü W98'in kendi cover_gaps çıktısıyla kapatmak** — Apex-kendine-iniş dogfood'u.
5. **%6 analiz-dışı** — kendi sürücülerini analiz kapsamına almak.
6. Eski erteliler: #21 add-override, #23 pin-cli-help, #94 impact-scope mutabakatı.

---

## 7. Tek cümle kapanış

Ar-Ge 3 "Apex kendi bulduğu son borcu kendi disipliniyle kapattı" demişti; **Ar-Ge 4'ün cümlesi:**
Apex'in geliştirme süreci kendi kendini hızlandırır hale geldi — çekişmeli spec hattı yayındaki
8 gizli hatayı yeni özellik gelmeden yakaladı, kapı kendi checkpoint'iyle ucuzladı, ve tüm bunlar
tek günde, tek notluk düşüş olmadan (A+ 100/100), beş tam-yeşil push'la origin'e işlendi.
