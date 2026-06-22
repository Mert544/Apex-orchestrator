# Apex — Oturum Devri & İlerleme (LIVING HANDOFF)

> Bu dosya **oturumlar arası hafızadır**: bir önceki oturumda ne yapıldığını, kanıt
> duruşunu ve **sıradaki işleri** taşır. Yeni oturum (özellikle **yerel**) buradan
> kaldığı yerden devam edebilsin diye yazıldı. North Star/`CLAUDE.md` **kilitli
> misyon**; bu dosya **operasyonel durum**dur (misyonu yeniden tartışmaz).
>
> **Branch:** `claude/apex-market-positioning-eyml1y` · **Son güncelleme:** 2026-06-22

---

## 1. Bu oturumda inen geliştirme (hepsi `origin`'de, A+99, gated, never-fake-green)

**BU OTURUM — Idea-motoru erişimi: sentez hedefleri artık `apex ideate`'te LANDABLE:**
- `4417d40` **feat(ideate): surface synthesis objectives as executable ideas** — yeni
  `app/engine/idea_synthesis_signals.py` grounding katmanı (lander'ın KENDİ yüklemini
  ÇAĞIRIR: `module_has_fillable_stub`/`rewrite_dataclasses`/`infer_annotations` —
  kopyalamadan; inşa-gereği dürüst: signal == lander'ın yapacağı) + `idea_action_bridge`'e
  additive `_augment_synthesis_steps` (`plan_tree`/`_roadmap_steps`): zaten-mevcut modül
  hedeflerine `implement-stub`/`infer-type-hints`/`dataclassify` **executable** adımı ekler;
  sentez-uygun modül yoksa **byte-identical** (determinizm korunur, seeder'a DOKUNULMADI).
  infer/dataclassify saf `_simplify_dispatch` adaptörü (dataclassify fixture-guard'lı);
  implement-stub develop-çekirdeğine delege (`plan_implement_stub`→`apply_rename(impact_scope=True)`,
  honesty=`bool(plan.new_contents)`). `_generate` üretemezse None → **sahte-yeşil yok**.
- `5d4a086` **test(conftest): byte-identical snapshot reproducibility** — `/tmp/charorig/*`
  artık `1820170^`'ten + relative→absolute import rewrite ile staged; fresh-clone
  collection-error'ı kapandı (conftest stager bunları atlıyordu).
- **Buyer-proof (bağımsız `/tmp` projesi):** 7 doğrulanmış değişiklik indi (4 stub —
  recursion dahil + 8 kanıtlanabilir tip + 1 dataclass), RED süit → GREEN; belirsiz
  stub / real-logic class / unprovable return / güvenlik bulguları **doğru reddedildi**;
  byte-identical, `unshare -rn` offline, zero-token.

**Aynı oturum — develop-core + dürüstlük dalgaları (üçü de birleşik full-gate yeşil, A+99):**
- `13168c5` **feat(verify): pytest-not-importable distinct honest tier** — Apex'i çalıştıran
  yorumlayıcı pytest'e sahip değilse artık "suite RED" sanılmaz; ayrı `verification-unavailable`
  tier'ı (NO_SUITE'e KATILMADAN) + her giriş noktasında (develop/ideate/maintain) yüksek-sesli,
  yorumlayıcıyı-adıyla-söyleyen mesaj; proof-carrying (doğrulayamayınca land ETMEZ). Buyer-proof'un
  bulduğu **sessiz tam-teslimat-açığını** kapatır. (run_tests/_apply_verify/develop_session/
  idea_action_bridge/cli_ideate; green/red/no-suite byte-identical.)
- `921de98` **feat(stub-synthesis): sabit-anahtar indeksleme `a[k]`** — iç pozisyonlar (`xs[1]`,
  `xs[2]`) artık sentezlenebilir; indeks witness'ların tip-tam kesişiminden, ≥2-witness tabanı +
  mevcut canary/accept gate'leri değişmeden (0/negatif indeks first/last builtin'lerinin).
- `0687fc3` **feat(infer-type-hints): aynı-tip literal binary** — `1+2`→int, `'a'+'b'`→str,
  `[1]+[2]`→list, `(1,)+(2,)`→tuple (Add/Sub/Mult/Mod/FloorDiv; **Pow/Div/bool sağlamlık için
  hariç**; name/mixed/non-literal reddedilir — değer tip-sınırı değildir).
- `1360346` **feat(verify): src-layout import çözümü** — `src/`/`lib/` layout'lu repolarda
  `import mod` artık çözülür (`RunTestsSkill._import_roots`: root-FIRST + yalnız bare-stem-import
  edilen modülü barındıran src/lib eklenir, bounded/sorted/saf-AST); collection-error → yanlış-RED
  → "hiç inmedi" kapanır. Gerçek öğrenci/şirket repolarında landing'i açar; #A'nın pytest-tespiti
  bozulmadan birleşti.

**— önceki oturum —**

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

- **Kapı:** `python scripts/verify.py` → full green (**~21.591 test** + ruff), öz-not **A+99**
  (bu oturumda `--chunks 16 -j 4` → 647s, 16/16 chunk + ruff PASS, exit 0).
- **⚠️ FRESH-CONTAINER KAPI ÖN-KOŞULU (yeni oturum bunu OKUSUN):** Bulut klonu **shallow**
  gelir (~50 commit); karakterizasyon testleri `git show <eski-commit>^` ile snapshot
  stage eder → shallow'da **collection-error** (bu oturumda 7 chunk böyle kırıldı, dalga
  DEĞİL). Kapıdan önce **`git fetch --unshallow`** ŞART (50→~1462 commit). Ayrıca
  `pip install -e ".[dev]"` (pytest-timeout + PyYAML; yoksa addopts/import kırılır).
  Hızlı ön-uçuş: `python -m pytest tests/ --collect-only -q` (≈5 sn, import/snapshot
  kırıklarını full suite koşmadan yakalar).
  - **HIZLI (yerel, 32GB/Core Ultra 9):** `python scripts/verify.py --chunks 16 -j 8` (~6-10 dk).
  - Burada (4 çekirdek/15GB) `-j 2` ile ~30 dk, tepe RAM 2.8GB. Varsayılan sıralı = OOM-güvenli.
    Bu oturum `-j 4` ile ~650s, sorunsuz.
- **⚠️ Worktree izolasyonu GÜVENİLMEZ:** bu ortamda `isolation: worktree` bazen **eski tabandan**
  checkout açar (gözlemlendi: `54962d3`, HEAD'den 1114 commit geride → hedef dosya orada YOK;
  başka bir worktree doğru `4d9466c`'teydi — tutarsız). **Kod-yazan mühendisleri ANA AĞAÇTA**
  çalıştır (worktree değil), git komutu yasakla + tek-yazar/dosya. (#D worktree'de bloklandı,
  ana ağaçta indi.) Ana ağaçta paralel = çakışma → **ayrık-dosya + sıralı** koştur.
- **Öz-not invaryantı A+99:** grader karmaşıklık tavanı **12** (`app.tools.code_metrics.function_complexities`, ruff C901'den FARKLI/daha sıkı). Yeni fonksiyonu >12 bırakırsan `test_*_self_grade*` / `*a_plus_99` KIRILIR. Kontrol:
  `python -c "from app.tools.code_metrics import function_complexities as f; print([(n,cx) for n,l,cx in f(open('<dosya>').read()) if cx>12])"` → `[]` olmalı.
- **Buyer-proof saha testi:** bağımsız bir projede tüm yetenekler **gerçek kod indirdi**; determinism (byte-byte), çevrimdışı (`unshare -n`), sıfır-token doğrulandı; `==`→bool reddi sahada teyit edildi.
- **Denetçi:** `apex self-audit --north-star` → **PASS, drift=False** (somut=16, güvenlik=0). ON-MISSION.

---

## 3. SIRADAKİ İŞLER (öncelik sırası — saha testi gaplerine dayalı)

1. ✅ **(TAMAM — `436e51b`) Reduction belirsizlik açıklaması.** Stub belirsiz witness yüzünden reddedilince neden+nasıl-düzelt bildiriliyor. **Kalan 1-satır follow-up:** SADECE belirsiz stub'ı olan bir modül honest-fitness ile move-enumerasyonundan eleniyor (`module_has_fillable_stub`→False), o yüzden all-ambiguous modülde sebep uçtan-uca yönlenmiyor; `objective_compiler.py`/`develop_session.py`'de bir disclosure-only refuse-move veya `render_session_markdown`'da `obj.blocked` render'ı gerekir.
2. ✅ **(TAMAM — bu oturum, `4417d40`) Idea-motoru erişimi.** Sentez hedefleri
   (implement-stub/infer-type-hints/dataclassify) `apex ideate --actions`'te **executable**
   ve `--apply` ile **landable**; grounding `idea_synthesis_signals.py`, additive bridge
   augmentasyonu, seeder'a dokunulmadı. Buyer-proof bağımsız projede doğruladı.

**✅ İNDİ (bu oturum, birleşik full-gate yeşil):** #A yorumlayıcı/pytest dürüst tier'ı (`13168c5`)
· #D sabit-anahtar indeksleme (`921de98`) · #E aynı-tip literal binary (`0687fc3`) · #B src-layout
import çözümü (`1360346`).

**← SIRADAKİ ÖNCELİK:**
- **#C — raporlama dürüstlük uzlaştırması** (NET kazanımlar): (a) `--json` blocked/skipped satırları
  `verified`/`coverage` anahtarlarını atlıyor (`idea_action_bridge.py` ~2586/2689) → `None` default
  ekle (additive); (b) rollback yeni-dosyayı unlink ediyor ama `__pycache__/*.pyc` + boş
  `.github/workflows/` kalıyor (`_restore_snapshot` ~1756) → temizle. (c) apply-sayacı sentezi
  ayrı mı sayıyor — ÖNCE ampirik doğrula (scout buyer-proof'un bu iddiasını KISMEN çürüttü).

**📋 SCOUT-HARİTALI SIRADAKİ DALGALAR (bu oturumun 8 keşifçisinden; soundness + insertion intel HAZIR):**
- **Idea-reach v2 — cover-gaps'i ideate'e köprüle** (EN YÜKSEK; pure): yeni sinyal
  `cover_gaps_modules` (`plan_cover_gaps(root,rel).new_contents` gate'i — dürüst) + `_FACT_ACTIONS`
  + `_SYNTHESIS_OBJECTIVES` satırı + implement-stub gibi `apply_rename` delege (yeni `_apply_objective_via_develop_core`).
  Ardından wire-exports / generate-usage-doc (pure+oracle), strengthen-tests / tdd-implement (pytest-gated; tdd per-symbol → özel wiring).
- **PARAM-tipi isinstance-guard'dan** (NOVEL, sağlam, kilitli-refusal'dan AYRI): koşulsuz entry
  `if not isinstance(x,T): raise` / `assert isinstance(x,T)` → `x: T` (çalışma-zamanı zorunlu bound,
  değer-tahmini DEĞİL). Koşullar: girişte koşulsuz, tek-sınıf (tuple→Union reddet), guard'dan önce
  reassign/kullanım yok, mevcut anotasyon yok. Insertion `_annotatable_params()`.
- **builtin-call dönüş-tipleri** (`len/ord/id/hash`→int, `str/repr/hex/oct/bin/chr`→str, `bool`→bool,
  `list/set/dict/tuple/frozenset/sorted`→container) — **shadowing-guard ŞART** (`_assigned_names_in_scope`,
  `_own_returns` deseni); test satır 306 `len`-refusal'ı guard'la KASITLI güncellenir (zayıflatma değil).
- **UnaryOp numeric** (`-1`→int, `~5`→int, `-1.5`→float; ≤4 LOC) + **sequence/str × int**
  (`'a'*3`→str, `[0]*3`→list; ayrı `_mixed_sequence_int_mult`, mixed-type olduğu için same-type-binop kapsamaz).
- **Stub şablonları (sıra):** Slicing `a[:k]`/`a[k:]` (~50 LOC, constant-index disiplini) → `a.index(k)`
  → `k*a` sol-sabit (yalnız `*`) → iki-witness ternary (yalnız `<=`/`>=`/`==`; `<`/`>` min/max ile ÖZDEŞ → emit etme).
- **JSDoc-only JS/TS lander** (R&D #2, **recommend-only** — JS runner yok): `js-doc-params` objektifi,
  `ObjectiveSpec` ile kayıt (module-objective DEĞİL), 3 saf-Python yapısal kontrol (yorum-only/imza-byte-identical/
  kod-bytes-değişmez), NO_SUITE dürüstlük damgası; additive `_seed_js_ts_doc_params`. Ötesi vendored parser ister.

**PARK (North-Star sürücüsü DEĞİL — moat cilası):** coverage backlog (en riskli:
  `app/execution/semantic/transforms/_apply_helpers.py`, fan-in 10, 0 direct test);
  determinizm/fake-green sweep (0 canlı delik; `nan`→`math.isfinite` H1 latent).
3. _(Eski #3 "düz-paket import" ve #4 "JS/TS lander" yukarıda **#B** ve **JSDoc** olarak
   RAFİNE edildi — scout #1 ampirik gösterdi: düz vaka zaten çözülmüş, src-layout kaldı,
   fix TEK yer ve dar; JS/TS için tek çevrimdışı-sağlam adım JSDoc-yorum.)_

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
