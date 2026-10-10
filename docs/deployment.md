# Deployment preparation

Status: prepared; the **Streamlit app is not published**. Official requirements reviewed on 10 October 2026. The approved public source repository is [KothariMayaank/retail-demand-planner](https://github.com/KothariMayaank/retail-demand-planner). Publishing the source does not deploy the app; a public Streamlit deployment still requires approval.

## Recommended host and verified requirements

Streamlit Community Cloud is suitable for this small portfolio demo. It offers free Streamlit hosting connected to GitHub repositories. [Official overview](https://docs.streamlit.io/deploy/streamlit-community-cloud).

Use **Python 3.12**, explicitly selected in Advanced settings. The deployment form takes repository, branch and entry-point path; this project uses **cloud_app.py**. Supported Python versions must still receive security updates. [Official deployment instructions](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy).

Keep `requirements.txt`, `requirements-lock.txt`, `.streamlit/config.toml`, `config/settings.toml`, app modules, templates and synthetic data in the repository. Hosting starts from the repository root; Linux paths are case-sensitive and use forward slashes. The fixed localhost bind was removed so hosting controls the server connection. [Official file organization](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/file-organization).

The root requirements file pins four direct packages and references a full version constraint file. Community Cloud supports requirements.txt; no apt packages or `packages.txt` are needed here. Do not add competing environment files unless deliberately migrating the dependency setup. The unused statsmodels dependency was removed: regression is implemented with NumPy. [Official dependency instructions](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/app-dependencies).

Repository administrators can deploy the app. The service runs on Linux and may override some Streamlit settings, including usage-statistics reporting; the local setting is not a cloud privacy guarantee. [Official status and limitations](https://docs.streamlit.io/deploy/streamlit-community-cloud/status).

## Public-demo behavior

`cloud_app.py` runs the same dashboard with a synthetic-only profile:

- A visible banner identifies simulated data and results.
- Upload controls and uploaded-data loading are disabled.
- Analysis does not save normalized inputs, models or results to server folders.
- Users can download synthetic forecasts, inventory results and the combined ZIP.
- CSVs include `data_source` and `synthetic_data`; the ZIP also includes metadata.

`app.py` remains the full local application, with uploads and saved reproducible runs. Do not deploy this full-upload entry point publicly without a separate privacy, access and retention review. No database, keys, secrets or external account integrations are required for the prepared demo.

## Reviewed release bundle

Run:

```powershell
.\.venv\Scripts\python.exe scripts/prepare_deployment.py
```

This builds `outputs/deployment/retail-demand-planner-source.zip` and a SHA-256 file manifest. It uses an explicit file allowlist, rather than packaging the whole workspace. Uploaded CSVs, saved analysis runs, virtual environments, credential files and generated screenshots are excluded. A recognized-credential-pattern scan runs before packaging. This is not an exhaustive proof against every possible secret; review the manifest and source before publication.

`.gitignore` excludes uploads, outputs, virtual environments, `.env` files, secrets.toml and key files. Ignore rules do not remove files already committed to another repository. When using an existing repository, inspect both staged files and history before pushing; never commit `.streamlit/secrets.toml`. Future required credentials belong in Community Cloud settings. [Official secrets guidance](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management).

## Deploy only after approval

1. Review this guide, the source ZIP and `docs/project_presentation.md`. Obtain the user's approval for the public, synthetic-only demo and the GitHub repository that will hold its source.
2. Extract the allowlisted bundle into a clean repository. Include hidden `.streamlit` and `.github` directories. Review `git status` and staged changes; do not copy the entire working folder or outputs. Commit and push only approved files to the approved repository/branch.
3. Sign in to Streamlit Community Cloud and connect the authorized GitHub account. Choose Create app, supply that repository/branch and `cloud_app.py`, and select Python **3.12** in Advanced settings. Leave secrets empty. Choose a demo URL, then deploy only with approval.
4. Watch installation logs. Check public/private access in app settings before sharing the URL. A repository's visibility is separate from the application's access settings. [Official app settings](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app/app-settings).
5. Load the synthetic sample, run analysis, open all five main sections and export the ZIP. Confirm the demo banner, absence of upload controls, nonnegative forecasts and clear uncertainty warnings. If the build fails, inspect the first error in logs; check Python version, missing tracked sample files and dependency resolution. Do not relax validation or unpin packages merely to hide errors.

## Local verification and limits

The earlier fresh Windows/Python 3.12 installation passed **110 tests**. The full-project review now passes **120 tests** in the existing working environment and in a clean extraction using the existing deployment-check environment. Dependency consistency, full synthetic sample/upload acceptance and both entry-point startup checks pass. The current source archive has been rebuilt with 85 allowlisted files; regenerate it after later changes. The Ubuntu/Python 3.12 workflow in `.github/workflows/verify.yml` will run installation, tests, startup and acceptance after an approved push; it has **not** run on GitHub yet. See [the current review](project_review.md).

No actual Community Cloud build has been executed. Linux hosting compatibility is prepared, not certified by a completed cloud deployment. The Windows dependency constraints have no local paths or Windows-only package requirements, but a hosted installation still needs to be checked. Cloud resource availability and first-run training latency may differ from this computer. Sessions and cache are transient; download results before ending the session. Hosting is a demonstration, not a production inventory system.
