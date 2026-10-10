"""Build an allowlisted source archive; never include uploads, outputs or secrets."""
from hashlib import sha256
from pathlib import Path
import json
import re
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
FIXED = ("app.py", "cloud_app.py", "README.md", "requirements.txt", "requirements-lock.txt", ".gitignore",
         ".streamlit/config.toml", "config/settings.toml")


def release_files(root=ROOT):
    paths = [root / name for name in FIXED]
    for directory, pattern in (("demand_planner", "*.py"), ("scripts", "*.py"), ("tests", "*.py"),
                               ("docs", "*.md"), ("data/templates", "*.csv"), ("data/sample", "*.csv"),
                               ("data/sample", "*.json"), ("data/sample", "README.md"), (".github/workflows", "*.yml")):
        paths.extend((root / directory).rglob(pattern))
    files = sorted(set(paths))
    for path in files:
        relative = path.relative_to(root).as_posix()
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Missing or unexpected release file: {relative}")
        if any(part.startswith(".venv") or part in ("outputs", "uploads", "__pycache__") for part in path.relative_to(root).parts):
            raise ValueError(f"Private/generated path in release: {relative}")
        content = path.read_text(encoding="utf-8-sig")
        if re.search(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\bAKIA[A-Z0-9]{16}\b|\bgh[pousr]_[A-Za-z0-9]{30,}\b|\bsk-[A-Za-z0-9]{24,}\b", content):
            raise ValueError(f"Recognized credential pattern in release: {relative}")
    manifest = json.loads((root / "data/sample/manifest.json").read_text(encoding="utf-8"))
    if manifest.get("is_synthetic") is not True:
        raise ValueError("Sample manifest must explicitly declare is_synthetic: true.")
    return files


def prepare():
    files = release_files()
    destination = ROOT / "outputs/deployment"
    destination.mkdir(parents=True, exist_ok=True)
    archive_path = destination / "retail-demand-planner-source.zip"
    hashes = {}
    with ZipFile(archive_path, "w", ZIP_DEFLATED) as archive:
        for path in files:
            name = path.relative_to(ROOT).as_posix()
            content = path.read_bytes()
            archive.writestr(name, content)
            hashes[name] = sha256(content).hexdigest()
    report = {"archive": archive_path.name, "entrypoint": "cloud_app.py", "python": "3.12",
              "file_count": len(files), "known_credential_patterns_found": 0,
              "uploads_and_generated_outputs_included": False, "files_sha256": hashes}
    (destination / "manifest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"PASS: prepared {len(files)} allowlisted files; no uploads, generated runs or recognized credentials.\n{archive_path}")
    return archive_path


if __name__ == "__main__":
    prepare()
