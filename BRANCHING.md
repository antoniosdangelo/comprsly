# Comprsly branch rules

## The two branches that always exist

- `main`: tested code. This is what the Store package is built from.
- `sandbox`: where everything goes first.

## Work branches

Name the side first, so it is always visible:

- `backend/<what>` for the engine, detection, the tests, the build and the dev tools.
- `frontend/<what>` for the screens, the icons and the docs.

**One push is exactly two branches, one of each, backend first.** Not three, not one combined. Each carries an untracked `PR.md` beside the work: what changed, why, how it was tested.

## The path every change takes

1. Branch from `sandbox`.
2. Run the app and use it like a customer, then run the tests. All must pass.
3. Commit locally, authored as Antonio, plain English message, no Claude attribution of any kind. **Then stop.** Agents do not push, do not open pull requests and do not merge.
4. Antonio reviews the branch in VS Code Source Control and pushes it.
5. Pull request into `sandbox`. Checks run. **Nothing merges automatically**, Antonio merges it, and the work branch is deleted.
6. `sandbox` is promoted to `main` only when Antonio says so.
7. A Store release is a separate, manual job. See `docs/release-runbook.md`.

## Running it

From the repo root:

```
pip install -r product/build/requirements.txt
python product/backend/main.py
python -m unittest discover -s product/backend -p "test_*.py"
```

That is `unittest`, not pytest, which is not installed. CI runs the same test line on a Windows runner, because `main.py` imports a Windows API as it loads. On a Mac it is `requirements-mac.txt` and `python product/backend/main_mac.py --check`.

## What runs on GitHub

- `checks.yml`, on every pull request and every push to `sandbox`: the app compiles, the tests run on `windows-latest`, and gitleaks scans for secrets.
- `build.yml`, on a push to `main`: builds the installer as an artifact. It does not publish anything to the Store.
- `macos.yml`: the shared engine and Mac layer tests, the `.app` build, and a smoke run on a macOS runner.

## Guards, once per clone

```
git config core.hooksPath .githooks
```

That turns on the secret check and the `main` push guard. They only protect a machine that has them on, which is why nothing secret is ever committed in the first place.

## Folders

`product/backend/`, `product/frontend/`, `product/build/`, `product/tools/`, `docs/`. Nothing else at that level. The website is a separate private repo, `comprsly-website`. Full layout in `README.md`.

## Databases

There is no database and no backend service. Comprsly runs entirely on the user's machine, and its settings and history live in `%LOCALAPPDATA%\Comprsly`. Never commit a `*.sqlite`, `*.db` or a backup.
