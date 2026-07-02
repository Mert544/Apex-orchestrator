# Vizyon Spec — Apex'in İçinde Yaşayan Akıllı Otonom Asistan

> Patron yönü (2026-07-02): *"dreaming, obsidian ve diğer bir çok yeteneğini akıllı,
> otonom ve Apex'e zeka vererek Apex'i kendi içinde yaşayan bir asistana dönüştürmeliyiz."*
> Bu belge o vizyonu **North-Star sınırları içinde** (zero-token, deterministik,
> proof-carrying, asla sahte-yeşil) inşa edilebilir dalgalara böler. Devralınan
> 6-FAZ programının Faz-4 (dreaming) ve Faz-5 (obsidian-tüketim) hatlarını kapsar
> ve genişletir.

---

## 1. "Yaşayan asistan" ne demek — davranış sözleşmesi

Bugünkü Apex **çağrılınca** çalışır (assist/develop/dream birer komuttur). Yaşayan
asistan, projenin içinde **kalıcı bir zihinle** oturur ve üç şeyi kendiliğinden yapar:

1. **Gündem üretir** — "bu projede şimdi en değerli 3 mekanik iş şu; 2'sini kanıtla
   indirebilirim, 1'i insan-kararı" (dream + move_value + readiness sentezi).
2. **Hatırlar ve öğrenir** — hangi objektif bu projede tuttu/tutmadı, hangi modül
   nazik, hangi kapı sıkılaştı (IdeaMemory + dream_gate_learn + value_reliability
   zaten VAR; eksik olan bunların TEK bilgi-kasasında birleşmesi ve oturumlar-arası
   gündem'e dönüşmesi).
3. **Anlatır** — teknik olmayan sahibe owner-report dilinde, geliştiriciye diff+proof
   dilinde; her ikisi de mevcut motorların çıktısından türetilir (yeni analiz yok).

**Değişmezler:** hiçbir kendiliğinden İNİŞ yok — gündem her zaman preview-first;
`--commit`/`--land` yine covered-only + auto-rollback + proof-of-fix'e bağlı.
Asistanın "zekası" = deterministik sinyallerin sentezi; LLM yok, token yok.

## 2. Mimari: üç mevcut ayağın üstüne bir çatı

```
        ┌───────────── apex agenda (YENİ, çatı) ─────────────┐
        │  gündem = f(dream digest, IdeaMemory, move_value,  │
        │            readiness, hotspots, trackrecord)       │
        └───────┬──────────────┬───────────────┬─────────────┘
   dream çekirdeği      bilgi-kasası        anlatım katmanı
   (dream --land,       (.apex/vault/ →     (owner-report,
   confluence, gate-    IdeaMemory +        proof, explain,
   learn, chain)        dream digest +      canvas/Obsidian
                        proof history)      export'ları)
```

- **Bilgi-kasası (Faz-5 / "obsidian"):** `.apex/` altındaki dağınık kalıcı durumu
  (idea-memory, dream digest, proof-of-fix, trackrecord, gate-learn) tek şemalı bir
  **vault**'ta toplar; `apex canvas` zaten Obsidian-uyumlu JSONCanvas veriyor —
  vault, canvas'ın OKUDUĞU tek doğruluk kaynağı olur. Obsidian entegrasyonunun
  doğru yönü (denetçi kararıyla sabit): **görselleştirme değil, döngüye tüketim** —
  vault'taki her not bir sonraki gündem hesabının girdisidir.
- **Gündem (`apex agenda`, YENİ komut):** read-only; "şimdi ne yapmalı"yı üç
  şeritte basar: (a) kanıtla-inebilir (objektif + hedef modül + beklenen değer),
  (b) insan-kararı (design_task'lar, gerekçeli), (c) izlenen (gate-learn'ün
  sıkılaştırdığı/retire ettiği yollar). Deterministik sıralama = move_value ×
  feasibility × reliability (hepsi mevcut motorlar).
- **Yaşama biçimi:** `apex daemon` zaten var (supervised). Asistan modu = daemon'un
  her uyanışta agenda'yı tazelemesi + değişiklik varsa vault'a not düşmesi;
  landing yine yalnız açık `--land/--commit` ile.

## 3. Dalga planı (her biri tek-gate'lik, bağımsız inebilir)

| Dalga | İçerik | Kanıt ölçütü |
|---|---|---|
| **V1 — vault** ✅ | `.apex/vault/` şeması + mevcut 5 kalıcı deponun tek-yazarlı birleşimi (migration: idempotent, kayıpsız) | round-trip testleri; eski yollar okumaya devam eder (geri-uyum) |
| **V2 — agenda** ✅ | `apex agenda` (read-only sentez) + owner-dili özeti | agenda determinizmi (aynı repo → bayt-aynı); boş-proje dürüst-boş |
| **V3 — canlı döngü** ✅ | daemon uyanışında agenda-tazele + vault-notu; `assist`'e "gündemden 1 numarayı uygula" kısayolu (preview-first) | daemon superviser testleri; hiçbir otonom yazma yok |
| **V4 — öğrenme derinliği** ✅ | gate-learn/reliability sinyallerinin agenda'ya geri-beslemesi (demote-only); "bu projede şu objektif 3 kez rollback yedi → gündemden düşür, notunu vault'a yaz" | monotonluk testleri (asla gevşetme); açıklanabilirlik (neden düştü notu) |
| **V5 — Obsidian köprüsü** ✅ | vault → canvas/markdown export'un çift-yönlü OKUMASI: kullanıcının vault'a el-yazdığı `#apex-hedef` notları agenda'ya aday girer (yine preview-first) | el-notu → aday → preview zinciri e2e; kötü-biçimli not dürüst-reddedilir |

## 4. İlk adım (bir sonraki oturum için dispatch-hazır)

V1 vault şeması: `vault/schema.md` + `app/memory/vault.py` (tek-yazar, JSON, bayt-
deterministik dump); mevcut `IdeaMemory.load/save`'in vault'a delege eden ince
adaptörü. Riski düşük, her şeyi açar. (6-FAZ Faz-5 spec'iyle birleşik.)

---

*Sınır notu: "akıllı" burada her zaman = deterministik sinyal sentezi. LLM'li bir
sohbet asistanı bu ürünün İÇİNDE değil, olsa olsa YANINDA durur (Claude bugün bu
repo için tam da o roldedir) — Apex'in kendisi zero-token kalır; moat budur.*
