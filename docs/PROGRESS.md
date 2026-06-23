# Apex — Oturum Devri & İlerleme (LIVING HANDOFF)

> Bu dosya **oturumlar arası hafızadır**: bir önceki oturumda ne yapıldığını, kanıt
> duruşunu ve **sıradaki işleri** taşır. Yeni oturum (özellikle **yerel**) buradan
> kaldığı yerden devam edebilsin diye yazıldı. North Star/`CLAUDE.md` **kilitli
> misyon**; bu dosya **operasyonel durum**dur (misyonu yeniden tartışmaz).
>
> **Branch:** `claude/apex-market-positioning-eyml1y` · **Son güncelleme:** 2026-06-23

---

## 1. Bu oturumda inen geliştirme (hepsi `origin`'de, A+99, gated, never-fake-green)

**BU OTURUM (6. tur) — kompozisyonel sentez + modernize köprüsü + comprehension test-pin + buyer-proof (full-gate yeşil, A+99):**
- `49e0011` **feat(stub-synthesis): sınırlı 1-seviye kompozisyonel gövdeler** — `return a[k] <op> c` (sabit-index
  sonra skaler-aritmetik) ve `return len(a) <op> c`; str/list/tuple, int çıktı, op∈{+,−,*}. **Buyer-proof boşluğunu
  kapatır**: `double_first([5,9])=10,([0,1])=0,([7])=14` → `return xs[0] * 2`. Sağlamlık uçtan-uca
  witness-doğrulamasından (kompozisyona güvenmekten DEĞİL): her (k,op,c) HER witness'a doğrulanır, sınırlı
  (index = en-kısa-witness'ta geçerli ∪ {0,1,−1}; sabit −64..64), ≥2-distinct floor + type-exact gate + off-witness
  canary, yalnız tek hayatta-kalan emit (ambiguity→refuse). KRİTİK **no-shadow**: bir atom zaten tüm witness'ları
  üretiyorsa kompozisyon ERTELER → basit gövdeyi gölgelemez/bozmaz (2 regresyonu bu çözdü).
- `57e344e` **feat(ideate): modernize köprüsü** — `modernize` artık **6. grounded opt-in** (varsayılan kapalı,
  `modernize=True`), Refine fazı. objective-compiler-driven (tek plan_* değil); sinyal `modernizable_modules`
  objektifin kendi `_tidy_transforms`'unu modül üstünde zincirleyip yalnız sonuç değişiyorsa nitelendirir
  (`modernize_plan(...).new_contents` — lander'la tek kaynak). Zaten-modern modül no-op (over-promise yok).
  Per-module; `apply_rename(impact_scope=True)`'e delege. Varsayılan plan **byte-identical**.
- `31458c1` **test(infer-type-hints): comprehension/collection dönüş-tipi sabitleme** — comprehension (list/set/dict)
  + constructor (list/dict/set/tuple/frozenset) çıkarımı ZATEN vardı (`_DISPLAY_TYPES`/`_BUILTIN_CALL_RETURN_TYPES`);
  30-test adanmış süit tek yerde sabitler (accepts + kilitli refüzler: generator-exp, shadowed constructor;
  eleman-tipi çıkarılmaz — bare list). Üretim değişikliği yok (mühendis keşifte dürüstçe raporladı).
- **BUYER-PROOF** (commit edilmedi; canlı kanıt): `apex develop session --apply` bağımsız bir projeye uygulandı →
  2-failed→**6-passed**, 5 katkı/4 dosya: `add`→a+b, `count_a`→`s.count('a')` [5.tur], `label`→`-> str` [4.tur],
  `banner`→`-> bytes` [5.tur], Point→@dataclass, wire-exports; `shout` (param-alıcı) **sağlam reddedildi**;
  wire-exports "**weak/uncovered**" diye dürüstçe işaretlendi; **iki bağımsız koşu byte-identical** (deterministik).
  + **read-only keşif denetçisi** 7-9. turlar için dosya-ayrık slate çıkardı (§3'e işlendi).

**BU OTURUM (5. tur) — 3 paralel dosya-ayrık dalga (bytes-tipi · count-stub · strengthen-tests köprüsü), full-gate yeşil, A+99:**
- `b36ef48` **feat(infer-type-hints): sağlam `bytes` dönüş-tipi** — str-metot kuralının analoğu: `b"..."`→bytes,
  `<str-lit>.encode()`→bytes, `<bytes-lit>.decode()`→str, bytes-döndüren bytes-metot zinciri
  (`b"a".upper().strip()`)→bytes. `_bytes_method_call_returns_type` `_literal_type`'a bağlı → ternary+recursion
  ile kompoze. Yalnız LİTERAL alıcı + arg-BAĞIMSIZ-sonuç-tipli metotlar; bare-Name alıcı, bilinmeyen/str alıcıda
  `.decode()`, arg-bağımlı metotlar (split/find/count) reddedilir. Stale `'s'.encode()` assertion'ı güncellendi
  (artık sağlam `-> bytes`; encode HEP bytes döndürür — yanlış str değil).
- `5dc6af2` **feat(stub-synthesis): 1-arg occurrence-count (`a.count(k)`)** — str/list/tuple üzerinde
  `(arg, beklenen_int)` witness'ları sabit `k`'nin sayımıysa `return a.count(k)`. `k` witness-input'tan madenlenir
  (str için substring, sequence için distinct eleman), HER witness'ı üretmesi doğrulanır, yalnız TEK `k` hayatta
  kalırsa emit (ambiguity→refuse). Type-exact int (bool reddedilir), off-witness canary, ≥2-distinct floor;
  non-varying all-equal contract + boş-substring (`count('')`) reddedilir. Never-fake-green.
- `9ba9d28` **feat(ideate): strengthen-tests köprüsü** — develop hedefi `strengthen-tests` artık ideate'te
  LANDABLE; **5. opt-in** (varsayılan kapalı, `strengthen_tests=True`), Stabilize fazı. Çift-gate mutant-öldüren
  assertion lander'ı (survivor VAR ∧ gerçek-kodda geçip mutantta düşen assertion sentezlenebilir). Sinyal
  `strengthenable_modules` lander'ın KENDİ kapısına (`plan_strengthen_tests().new_contents`) delege; saturated/
  öldürülemez-survivor/red-baseline reddedilir (over-promise yok). Per-module (cover-gaps şekli);
  `apply_rename(impact_scope=True)`'e delege. Varsayılan plan **byte-identical**, flag bağımsız.

**BU OTURUM (4. tur) — 3 paralel sentez dalgası + paralel-kapı izolasyon düzeltmesi (full-gate yeşil, A+99):**
- `806238a` **feat(infer-type-hints): aynı-tip ternary dönüş** — `return X if C else Y` (ast.IfExp), her İKİ
  dal da AYNI sağlam tipe çözülürse o tip (`'a' if c else 'b'`→str, `[1] if c else []`→list). Kural
  `_return_value_type` içinde (`_ifexp_same_type`, aynı oracle'a recursion) → fazladan üst-dallanma YOK; iç-içe
  ternary recursion'la, karışık plain+ternary `_infer_return_type`'ın aynı-tip mutabakatıyla çözülür. KİLİTLİ
  refüzler inşa-gereği korunur (dalda `==`/`/`/`**`/bare-name/unknown-call → None → tüm ternary reddedilir;
  farklı-tip dallar reddedilir); koşul hiç incelenmez. 205 infer_type_hints testi yeşil.
- `9d80107` **feat(stub-synthesis): 1-arg string-classification** — `return a.<method>()`; isdigit/isalpha/
  isalnum/isupper/islower/isspace/istitle'dan HER witness bool'unu üreten TEK metot (gerçek str özelliği,
  ezber-tablo DEĞİL — `is_num('123')==True,'12a'==False` → `s.isdigit()`). startswith/endswith kardeşi, aynı
  `_string_templates` yoluna bağlı (type-exact accept-gate, off-witness str-canary, ≥2-distinct floor,
  discriminating ≥1T∧≥1F değişmeden). NEVER-GUESS: yalnız TEK metot uyuyorsa emit (0 veya ≥2 → hiçbir şey).
  262 komşu stub testi yeşil.
- `05665bb` **feat(ideate): tdd-implement köprüsü** — develop hedefi `tdd-implement` artık ideate'te LANDABLE;
  **4. opt-in** (varsayılan kapalı, `tdd_implement=True`) ve **ilk PER-SYMBOL** köprü. RED testin çağırdığı eksik
  fonksiyonu sentezler (testi yeşile çeviren `def`). Sinyal `tdd_implementable_symbols` lander'ın KENDİ detektörünü
  (`detect_missing_symbols`) bir kez koşar, sonra yalnız `plan_tdd_implement().new_contents` dolu olanı tutar
  (lander'ın kendi kapısı; assertion-failure/zaten-test'li/şablon-uymayan reddedilir — over-promise yok). Target
  `"<module>:<name>"`; `apply_step` implement-stub gibi `apply_rename(impact_scope=True)`'e delege. Flag bağımsız +
  varsayılan plan **byte-identical**. 235 pinned + 194 bridge/ideate testi yeşil.
- `0072a30` **test(characterization): volatile reflection-ledger bloğu normalize** — `test_main_byte_identical`
  frozen↔live `main()`'i byte-byte karşılaştırır; `"reflection"` bloğu (total_runs/total_actions/success_rate/
  false_positive_rate/top_false_positives) FeedbackLoop'un **cwd-göreli** `.apex/feedback_log.json`'undan gelir.
  Harness cwd=REPO_ROOT koştuğundan **paralel kapıda** (`-j N`) başka süitlerin `main()`'i bu PAYLAŞILAN dosyayı
  değiştirir → giriş-sayısı orig↔new okumaları arasında YARIŞIR (senaryo [4]: total_actions 90 vs 89, yalnız chunk
  kompozisyonu bir yazıcıyı yanına koyunca; round-4 yeni test dosyaları 16-parça bölüşümünü kaydırıp açığa çıkardı).
  `_normalize`'a bu volatile alanlar + top_false_positives listesi eklendi — previous_run_count/total/token/süre
  gibi runtime-state, `main()` kontrol-akışı DEĞİL; 6000+ karakter kontrol-akışı karşılaştırması değişmedi (gerçek
  sapma hâlâ patlar). Simüle yarış çifti normalize-eşit + süit yeşil. (KÖK: cwd-göreli `.apex` paralel paylaşımı.)

**BU OTURUM (3. tur) — 3 paralel sentez dalgası + develop-loop determinizm KÖK-düzeltmesi (full-gate yeşil, A+99):**
- `b7985f7` **fix(develop): determinist regresyon-backstop — bayat bytecode OKUMAZ** — oturum-sonu
  regresyon-backstop'u (ve move-başı impact-scoped kapı) projeyi alt-süreçte koşar; bir move modülü
  yeniden yazıp **aynı tam-SANİYE** içinde tekrar koşulunca CPython'un saniye-granüler pyc-invalidation'ı
  **bayat `.pyc`** servis ediyordu → gerçek regresyon ~%15 **GÖRÜLMÜYOR** (`regression_rolled_back` byte-aynı
  girdide False; auto-rollback bir koşuda fire ediyor, diğerinde etmiyor). Düzeltme: DONTWRITE'ı eksik olan
  iki alt-sürece `PYTHONDONTWRITEBYTECODE=1` — `RunTestsSkill` (ana koşucu + backstop **okuyucusu**) ve
  `cross_file_rename`'in impact-scoped move-kapısı (bayat cache'in **YAZICISI**). import-oracle/test-shield
  zaten set ediyordu; artık HİÇBİR Apex alt-süreci kullanıcının projesine bytecode yazmaz → her oturum-içi
  tekrar GÜNCEL kaynaktan derler (same input → same rollback). **Kanıt:** düzeltme sonrası **0/30** develop-session
  flake (önce 3/20), modül **5/5** yeşil, minimal aynı-saniye-rewrite repro mekanizmayı+düzeltmeyi doğruladı.
  Önceden izole geçen ama modülde flake olan determinizm + transitive-rollback testlerini sabitler.
- `3fe52cc` **feat(ideate): generate-usage-doc köprüsü** — develop hedefi `generate-usage-doc` artık
  `apex ideate --actions`'ta LANDABLE; **3. geniş opt-in** hedef (varsayılan kapalı, `generate_usage_doc=True`).
  Paketin PUBLIC API'sinden (public top-level fonksiyon/sınıf imzaları, ilk docstring satırı, mevcut `>>>`
  doctest'ler) determinist `USAGE.md` yazar; PURE + **DOCTEST ORACLE** (her `>>>` temiz alt-süreçte koşar,
  yeşil koşmayan örnek atlanır = dürüst eksik-iddia). wire-exports gibi develop-core `apply_rename`'e delege.
  Grounding sinyali `generate_usage_doc_packages` == lander'ın KENDİ kapısı (`plan_generate_usage_doc().new_contents`);
  varsayılan plan (flag kapalı) **byte-identical**.
- `8fac0f8` **feat(infer-type-hints): giriş isinstance-guard'ından sağlam PARAMETRE tipi** — koşulsuz
  `assert isinstance(x, str)` / `if not isinstance(x, int): raise ...` gövde-girişinde her devam-eden yol
  `x`'in o sınıf örneği olduğunu KANITLAR → `x: str`/`x: int` zaten runtime'ın dayattığı bir olguyu yazar.
  Default-değerden çıkarım **REDDİ** kilidini gevşetmez (default = atlanmış-arg değeri, tip-sınırı değil →
  reddedilmeye devam). Reddedilen sağlamlık-koşulları sabit: koşullu guard, sınıf TUPLE'ı (Union gerekir),
  guard'tan önce yeniden-atanmış/kullanılmış param, zaten-anotasyonlu param, dotted/bilinmeyen sınıf. Fake-green canary.
- `7cc3445` **feat(stub-synthesis): 1-arg string-predicate (startswith/endswith)** — `return a.startswith(k)` /
  `return a.endswith(k)`; `k` = True-bekleyen witness string'lerinin ortak prefix'i (resp. suffix), HER witness'ın
  beklenen bool'unu üretmesi DOĞRULANDIKTAN sonra emit edilir. Tip-tam accept-gate + off-witness str-canary
  tek hakem (never-fake-green). Sözleşme AYIRT etmeli (≥1 True ∧ ≥1 False, yoksa sabit→başka aile), ≥2-distinct-witness tabanı.

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

**Aynı oturum — develop-core + dürüstlük dalgaları (full-gate yeşil, A+99):**
- `f1b5a37`+`b882880`+`5d96388` **2. tur — 3 PARALEL ağır mühendis (manuel-worktree)** — builtin-call
  dönüş-tipleri (shadow-guard: `len/str/bool/list/sorted...`) · `a.index(k)` stub (eleman-pozisyonu) ·
  wire-exports idea-motoru köprüsü (2. bağımsız opt-in `wire_exports=False`). 6 hafif keşifçi gelecek
  dalgaları haritaladı; `/code-review` skill = 0 bug; birleşik full-gate yeşil. **Dayanıklılık:** 2 mühendis
  API-529-overload'a düştü (iş kaybı YOK, worktree temizdi) → retry'la döndü; never-fake-green korundu.
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
- `e7a964d`+`964df1a`+`4192d9a` **3 PARALEL ağır mühendis (manuel-worktree, OOM tavanı=3)** —
  cover-gaps idea-motoruna köprülendi (opt-in `cover_gaps=False`, `_apply_implement_stub`→tablo-sürücülü
  `_DELEGATED_SYNTHESIS` genelleştirmesi) · unary-numeric + sequence×int tip-çıkarımı · slicing stub
  şablonu `a[:k]`/`a[k:]`. Hepsi ayrık-dosya; **`/code-review` skill'i** (2 bulucu = `[]` bulgu);
  birleşik full-gate yeşil. **Operasyonel ders:** auto-worktree eski-taban bozuk → **manuel
  `git worktree add <path> HEAD`** doğru taban + import-izolasyon verir (kanıtlandı) → 3 paralel ağır
  mühendis açar; ama bitince worktree'leri SİL (paylaşılan-`.git`, paralel git-testlerini flake yapar).

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

- **Kapı:** `python scripts/verify.py` → full green (**~22.010 test** + ruff), öz-not **A+99**
  (bu oturumda `--chunks 16 -j 4` → 772s, 16/16 chunk + ruff PASS, exit 0).
- **⚠️ FRESH-CONTAINER KAPI ÖN-KOŞULU (yeni oturum bunu OKUSUN):** Bulut klonu **shallow**
  gelir (~50 commit); karakterizasyon testleri `git show <eski-commit>^` ile snapshot
  stage eder → shallow'da **collection-error** (bu oturumda 7 chunk böyle kırıldı, dalga
  DEĞİL). Kapıdan önce **`git fetch --unshallow`** ŞART (50→~1462 commit). Ayrıca
  `pip install -e ".[dev]"` (pytest-timeout + PyYAML; yoksa addopts/import kırılır).
  Hızlı ön-uçuş: `python -m pytest tests/ --collect-only -q` (≈5 sn, import/snapshot
  kırıklarını full suite koşmadan yakalar).
  - **HIZLI (yerel, 32GB/Core Ultra 9):** `python scripts/verify.py --chunks 16 -j 8` (~6-10 dk).
  - Burada (4 çekirdek/15GB) `-j 2` ile ~30 dk, tepe RAM 2.8GB. Varsayılan sıralı = OOM-güvenli.
    Bu oturum `-j 4` ile ~560s, sorunsuz.
- **⚠️ DETERMİNİZM İNVARYANTI (pyc):** Apex'in projeyi **import eden / test koşan HER alt-süreci**
  `PYTHONDONTWRITEBYTECODE=1` set ETMELİ. CPython'un pyc-invalidation'ı **tam-saniye** granüler →
  aynı-saniye içinde rewrite+rerun **bayat `.pyc`** okur → develop-loop'un regresyon-backstop'u gerçek
  regresyonu NON-determinist kaçırır. Bu oturum `b7985f7` ile düzeltildi (`RunTestsSkill` +
  `cross_file_rename`; `import_oracle`/`test_shield` zaten set ediyordu). **Yeni bir proje-import eden
  alt-süreç eklersen DONTWRITE'ı UNUTMA** (yoksa determinizm/never-fake-green testleri flake olur).
- **⚠️ PARALEL-KAPI PAYLAŞILAN-STATE TUZAĞI:** `verify.py -j N` chunk'ları **paylaşılan dosya sistemini**
  (repo + `/tmp`) paylaşır; `main()` FeedbackLoop'a **cwd-göreli `.apex/feedback_log.json`** yazar. Byte-identical
  bir karakterizasyon bu paylaşılan ledger'dan türeyen sayıları (reflection: total_actions vb.) pinlerse, başka
  bir chunk'ın eşzamanlı `main()` yazısı onu **yarıştırır** → flake (4. tur `0072a30` ile bu testte `_normalize`
  foldlandı). **Yeni test paylaşılan repo-state'i (`.apex`, scratch dosyaları) okuyan/yazana bir şey pinlemesin**;
  ya runtime-state'i normalize et ya da per-test izole et. (CLAUDE.md "transient hazards" sınıfının paralel yüzü.)
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

**🆕 EN GÜNCEL SLATE (6. tur keşif denetçisi; grounded · dosya-ayrık · sound · anafikre-sadık — PAKETLEME: R7 = A1∥B1∥C1, R8 = A2∥B2∥D1, R9 = C2/doctest):**
- **A1** [`type_annotations.py`]: param tipi `assert isinstance(x,A) and isinstance(y,B)` (BoolOp-And → operand başına single-class guard'a böl; `_entry_guard_binding`/`_isinstance_single_class` besle). Sağlam: assert İKİSİ de tutmazsa raise eder; `or` dışlanır. Witness: `assert isinstance(x,int) and isinstance(y,str)` → `f(x:int, y:str)`.
- **B1** [`stub_synthesis.py`]: `a.replace(k1,k2)` MADENLENMİŞ tek-çift (input→output ortak-altdizi diff'i), witness-doğrulamalı, ambiguity-refuse — bugünkü kombinatoryal literal çarpımı yerine. Witness: `slug("a b")=="a-b"` → `s.replace(' ','-')`.
- **C1** [`idea_synthesis_signals.py`+`idea_action_bridge.py`]: `dedup-total-return` & `dedup-parameterized` objektiflerini GROUNDED-köprüle (KAYITLI ama yüzeysizlenmemiş — `app/execution/objectives/{dedup_total_return.py:62,dedup_parameterized.py:54}`; sinyal yok). `_is_strengthenable` desenini aynala (gate=non-empty `plan_*().new_contents`).
- **A2** [`type_annotations.py`]: parametrize display tipleri — `{1:"a"}`→`dict[int,str]`, `[1,2]`→`list[int]`, `(1,"a")`→`tuple[int,str]` (her eleman `_literal_type`'la kanıtlı; karışık→bare; comp→bare). `_DISPLAY_TYPES.get` dalını `_parametrized_display_type` ile değiştir. (A1 ile aynı dosya → ayrı tur.)
- **B2** [`stub_synthesis.py`]: `sorted(a)[k]` (k-inci küçük) + `len(set(a))` (distinct-sayım). sorted[k] her witness'ta 0≤k<len iken total; len(set) sayım (PYTHONHASHSEED yok). (B1 ile aynı dosya → ayrı tur.)
- **C2/doctest** [`stub_synthesis.py`]: witness'ları modül docstring `>>>` doctest'lerinden de madenle (`_witnesses_in_file` kardeşi). `fillable_stub_modules`'tan akar, köprü değişmez.
- **D1** (YENİ yetenek, kendi dosyası) [`app/execution/objectives/document_signature.py` + küçük C-bağlama]: PEP 257 docstring İSKELETİ sentezle — param adları AST'ten (GERÇEK, çıkarım değil) + `Returns: <type>` SADECE `infer_annotations` dönüş-tipini kanıtladığında. North-Star "docstring ekle" sağlam yapılmış. Zaten-belgeli/fixture reddet. `infer_type_hints.py`+`docstring.py` aynala.
- **DIŞLANAN (drift/unsound — YAPMA):** bare-Name/Call dönüşten çıkarım (non-local) · default'tan param · `==`/`<`→bool (override edilebilir dunder) · Div/Pow aynı-tip · `set(a)`/`list(set)` (PYTHONHASHSEED sıra) · daha fazla detektör/safety/honesty makinesi.

**(ÖNCEKİ turlarda İNEN — referans):**

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

**📋 SCOUT-HARİTALI DALGALAR (bu oturumun 8 keşifçisinden; soundness + insertion intel HAZIR):**
**✅ İNDİ bu oturum (2 tur × 3 paralel):** cover-gaps (`e7a964d`) · unary+seq×int (`964df1a`) · slicing
(`4192d9a`) · builtin-call types (`f1b5a37`) · `a.index(k)` (`b882880`) · wire-exports köprüsü (`5d96388`).
KALAN follow-up'lar (insertion-intel HAZIR, scout-haritalı): cover-gaps→**generate-usage-doc** /
strengthen-tests / **tdd-implement** bridge'leri (usage-doc & tdd seam'leri tam çıkarıldı) · type→**isinstance-guard
PARAM** (novel sağlam) / **ternary-return** (iki dal aynı tip) / bytes-method · stub→**startswith/endswith→bool** /
sol-sabit / ternary · JSDoc lander · #C (JSON-şema `None`-default + rollback `.pyc`/boş-dir temizlik; sayaç=fix-gerekmez).
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
