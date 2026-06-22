# Apex — Oturum Devri & İlerleme (LIVING HANDOFF)

> Bu dosya **oturumlar arası hafızadır**: bir önceki oturumda ne yapıldığını, kanıt
> duruşunu ve **sıradaki işleri** taşır. Yeni oturum (özellikle **yerel**) buradan
> kaldığı yerden devam edebilsin diye yazıldı. North Star/`CLAUDE.md` **kilitli
> misyon**; bu dosya **operasyonel durum**dur (misyonu yeniden tartışmaz).
>
> **Branch:** `claude/apex-market-positioning-eyml1y` · **Son güncelleme:** 2026-06-22

---

## 1. Bu oturumda inen geliştirme (hepsi `origin`'de, A+99, gated, never-fake-green)

**Sentez gövde aileleri (Apex'in artık yazabildiği yeni kod):**
- `370e1c0` **GAP #1** — reduction/join: `max(a)`/`min(a)`/`min(a,default=k)`/`sep.join(a)`
- `a78c990` **GAP #2** — affine f-string: `return f"{prefix}{a}{suffix}"` (≥2-witness floor + off-witness canary)
- `24c4315` **GAP #3** — aynı-test **yerel-değişken** literal bağlamlarını witness'a çözme (`prefix="item-"; label(3)==prefix+"3"`), straight-line + constant-fold, hiçbir şey çalıştırılmaz
- `b148bad` GAP #3 karmaşıklık düzeltmesi (`_fold_sequence` çıkarımı → öz-not A+99)

**Tip çıkarımı (Apex'in artık koyabildiği SAĞLAM anotasyonlar):**
- `09c9d66` sağlam dönüş-tipi: str/f-string→str, bool, int/float, list/dict/set/tuple display+comprehension
- `539ca9b` **soundness düzeltmesi** — yalnız `is/is not/in/not in` + `not x` kesin-bool; `==`/`!=`/`<`/`<=`/`>`/`>=` **reddedilir** (override edilebilir dunder → yalan anotasyon). Kapı bunu yakaladı.
- `64d287c` kesin-str **kök** metot çağrıları → `-> str` (`','.join(x)`, `f"a{n}".strip()`, `"{}".format(x)`, zincirler `','.join(x).upper()`); **`name.strip()` (Name alıcı) reddedilir**

**Auto-rollback / moat sertleştirme (yeni özelliklerin sağlamlık zemini):**
- `f022cd6` baseline-diff auto-rollback backstop (transitif regresyon deliği)
- `3dc4c58` collection-interrupt bypass + parametrize id-shift over-rollback düzeltmesi
- `7e5a4ed` str/float ambiguity fake-green + set-arg list/tuple withhold

**Araçlar:**
- `64ef1ac` **paralel kapı** — `python scripts/verify.py --chunks 16 -j 8` (opt-in; varsayılan sıralı/güvenli kalır)

**Develop UX / dürüstlük (ne indiği DEĞİŞMEZ — yalnız ek açıklama):**
- `436e51b` **belirsizlik açıklaması** — bir stub belirsiz witness yüzünden reddedilince
  artık NEDEN'i ve nasıl düzeltileceğini söyler (`plan.blockers` → `CompileResult.blocked`):
  ör. `lowest_price: ambiguous: \`min(prices)\` ve \`prices[-1]\` ikisi de testleri geçer ama
  prices=[2,9,3]'te ayrışır (2 vs 3)… ayırt edici test ekle`. Reddetme kararı birebir aynı.

**Ar-Ge paketi:** `docs/rnd/` (APEX-ARGE.md, apex-arge-sunum.html, README.md) — rakip analizi, pazar, yatırımcı tezi, geliştirme yönleri.

---

## 2. Kanıt duruşu (next session bunlara güvenebilir)

- **Kapı:** `python scripts/verify.py` → full green (~21.490 test + ruff), öz-not **A+99**.
  - **HIZLI (yerel, 32GB/Core Ultra 9):** `python scripts/verify.py --chunks 16 -j 8` (~6-10 dk).
  - Burada (4 çekirdek/15GB) `-j 2` ile ~30 dk, tepe RAM 2.8GB. Varsayılan sıralı = OOM-güvenli.
- **Öz-not invaryantı A+99:** grader karmaşıklık tavanı **12** (`app.tools.code_metrics.function_complexities`, ruff C901'den FARKLI/daha sıkı). Yeni fonksiyonu >12 bırakırsan `test_*_self_grade*` / `*a_plus_99` KIRILIR. Kontrol:
  `python -c "from app.tools.code_metrics import function_complexities as f; print([(n,cx) for n,l,cx in f(open('<dosya>').read()) if cx>12])"` → `[]` olmalı.
- **Buyer-proof saha testi:** bağımsız bir projede tüm yetenekler **gerçek kod indirdi**; determinism (byte-byte), çevrimdışı (`unshare -n`), sıfır-token doğrulandı; `==`→bool reddi sahada teyit edildi.
- **Denetçi:** `apex self-audit --north-star` → **PASS, drift=False** (somut=16, güvenlik=0). ON-MISSION.

---

## 3. SIRADAKİ İŞLER (öncelik sırası — saha testi gaplerine dayalı)

1. ✅ **(TAMAM — `436e51b`) Reduction belirsizlik açıklaması.** Stub belirsiz witness yüzünden reddedilince neden+nasıl-düzelt bildiriliyor. **Kalan 1-satır follow-up:** SADECE belirsiz stub'ı olan bir modül honest-fitness ile move-enumerasyonundan eleniyor (`module_has_fillable_stub`→False), o yüzden all-ambiguous modülde sebep uçtan-uca yönlenmiyor; `objective_compiler.py`/`develop_session.py`'de bir disclosure-only refuse-move veya `render_session_markdown`'da `obj.blocked` render'ı gerekir.
2. **Idea-motoru erişimi** (Ar-Ge yönü #3) — daha zengin sinyaller / daha derin fraktal. **← SIRADAKİ ÖNCELİK**
3. **Düz-paket import edilemezliği tespiti + pythonpath/conftest probe-shim** (saha gap #5). Student repo'ları sık sık pyproject/pythonpath'siz → her şey `no-suite`'a düşüyor. **DİKKAT:** geniş/hassas yüzey (`run_tests.py`, `cli_autonomy.py`, `develop_session.py`, `objective_compiler.py`, `proof_of_fix.py`). Ayrıca dry-run vs apply `no-suite` dürüstlük tutarsızlığı (küçük).
4. **JS/TS gerçek lander** (Ar-Ge #2) — şu an yalnız öneri-modu (`idea_seeder`); güvenliği sulandırmadan ilk gerçek adım.

**SAĞLAM-DEĞİL diye REDDEDİLDİ (YAPMA):** default/call-site'tan parametre-tipi veya dataclass alan-tipi çıkarımı; param-alıcılı `name.strip()→str`. Bir değer/varsayılan bir **tip sınırı değildir** — Apex'in soundness duruşunu ihlal eder (`type_annotations.py` docstring bunu açıklıyor).

**Kuyruktaki küçük işler:**
- `nan` float-canary `sorted` determinizmini bozuyor → `math.isfinite` filtresi (stub_synthesis).
- `north_star_audit.py` `_CONCRETE_SCOPES` idea-* scope'larını az sayıyor (yalnız precision, muhafazakâr — denetçi flag'ledi, düşük öncelik, **fix etme** demişti).

**Parke WIP (kaybolmasın diye patch'lendi — `docs/wip/`):** iki eski "scope-honesty"
raporlama stash'i (project_profile/dashboard). **Stale + büyük olasılıkla aşılmış**
(analysis-scope dürüstlüğü zaten branch'te). Drift-bitişik (raporlama/honesty) —
North Star bunu öncelemez. Yalnız referans; gerekirse HEAD üzerine **yeniden** yaz.

---

## 4. Operasyon disiplini (DEĞİŞMEZ — `AGENTS.md`/`CLAUDE.md`)

- **Push öncesi full-green kapı**; asla sahte-yeşil, testi zayıflatma yok.
- Proof-carrying + **auto-rollback** her uygulanan değişiklikte.
- Commit `mertelgul@gmail.com`, **explicit pathspec** (paylaşılan dosya/registry başına tek yazar/dalga), **git geçmişini asla yeniden yazma**.
- **≤3 ağır (pytest koşan) mühendis** aynı anda (OOM tavanı; 5 = OOM); read-only denetçiler hafif; kapıyı **yalnız** çalıştır.
- Geçici tehlikeleri temizle: `app/orchestrator/*_scratch.py`, `tests/_inline_orig_blob.py`; `pydantic>=2`.
- Ritim: ≤3 ayrık-dosya mühendisi + /tmp saha-testi + read-only denetçi → birleşik kapı → yeşilde push → bulgular bir sonraki dalgayı sürer. **Geliştirme-öncelikli kal** (denetçinin sabit flag'i).

---

## 5. Yerel başlatma (PowerShell — 32GB / Core Ultra 9)

```powershell
cd Apex-orchestrator
git checkout claude/apex-market-positioning-eyml1y
git pull origin claude/apex-market-positioning-eyml1y      # mevcut klon güncelleme

# veya sıfırdan:
# git clone https://github.com/Mert544/Apex-orchestrator.git ; cd Apex-orchestrator ; git checkout claude/apex-market-positioning-eyml1y

python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -e ".[dev]"                 # pydantic + PyYAML + pytest + ruff (LLM yok, CUDA yok)

python scripts/verify.py --chunks 16 -j 8     # hızlı paralel kapı (~6-10 dk)
```
- **Python ≥ 3.10.** GPU/CUDA **kullanılmaz** (Apex saf-Python AST).
- Gerçek bir projeye kod indir: `apex develop session --target <yol> --apply`, sonra `python scripts/verify.py -j 8` ile doğrula.
