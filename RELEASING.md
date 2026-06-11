# Releasing Apex — the 5-minute checklist

Everything below is free. Code-side work is already done (packaging metadata,
`release.yml`, `pages.yml`, the `docs/` site, action branding); what remains
are one-time clicks on github.com / pypi.org.

## 0. One-time: make the repo public

Settings → General → Danger Zone → **Change visibility → Public**.
(Required for free GitHub Pages and for the Action Marketplace.)

## 1. PyPI — publish `pip install apex-orchestrator`

Uses **Trusted Publishing** — no API token is ever created or stored.

1. Create a free account at <https://pypi.org> (enable 2FA when prompted).
2. PyPI → your account → **Publishing** → *Add a new pending publisher*:
   - PyPI project name: `apex-orchestrator`
   - Owner: `Mert544` · Repository: `Apex-orchestrator`
   - Workflow name: `release.yml`
   - Environment name: `pypi`
3. GitHub repo → Settings → **Environments** → *New environment* → name it `pypi`.
   (Optional: add yourself as a required reviewer for a manual approval step.)
4. Ship it:

   ```bash
   git tag v0.1.0
   git push origin v0.1.0
   ```

   The `Release to PyPI` workflow builds the sdist+wheel, twine-checks them,
   smoke-tests the wheel in a clean venv, publishes to PyPI, and opens a
   GitHub Release with the artifacts attached.

5. Verify: `pip install apex-orchestrator && apex --help`.

## 2. GitHub Action — list on the Marketplace

`action.yml` already has the required `branding` (shield / blue).

1. Enable 2FA on your GitHub account (Marketplace requirement).
2. Open the release that step 1 created (Releases → `v0.1.0`) → **Edit**.
3. Tick **“Publish this Action to the GitHub Marketplace”**, accept the terms,
   pick categories (suggested: *Code quality*, *Security*) → **Update release**.
4. Keep a floating major tag so users can pin `@v1`:

   ```bash
   git tag -f v1 v0.1.0
   git push -f origin v1
   ```

## 3. GitHub Pages — the demo site

1. Repo → Settings → **Pages** → Build and deployment → Source: **GitHub Actions**.
2. Merge/push to `main` (or run the *Deploy demo site to Pages* workflow from
   the Actions tab). The workflow installs Apex, **regenerates the live report
   from that commit** (`apex dashboard --target=. --out=docs/demo.html`), and
   deploys `docs/`.
3. The site appears at <https://mert544.github.io/Apex-orchestrator/>.

## Releasing the next version

```bash
# 1. bump `version` in pyproject.toml (e.g. 0.1.1)
# 2. commit it, then:
git tag v0.1.1 && git push origin v0.1.1
git tag -f v1 v0.1.1 && git push -f origin v1   # keep the action's @v1 fresh
```
