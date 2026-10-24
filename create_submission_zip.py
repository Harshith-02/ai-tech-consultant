import os
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
ZIP_NAME = "ai_tech_consultant_submission.zip"
ZIP_PATH = PROJECT_ROOT / ZIP_NAME

# Patterns to strictly exclude
EXCLUDE_DIRS = {
    ".git",
    ".venv",
    ".vercel",
    ".pytest_cache",
    "__pycache__",
    "scratch",
    "node_modules"
}

EXCLUDE_EXTENSIONS = {
    ".pyc",
    ".pyo"
}

EXCLUDE_FILES = {
    ".env",
    ".env.local",
    ".env.production",
    ZIP_NAME,
    "create_submission_zip.py"
}

def should_exclude(rel_path_str: str) -> bool:
    parts = rel_path_str.replace("\\", "/").split("/")
    for p in parts:
        if p in EXCLUDE_DIRS:
            return True
        if p.startswith(".env"):
            return True
    
    fname = parts[-1]
    if fname in EXCLUDE_FILES or fname.startswith(".env"):
        return True
    _, ext = os.path.splitext(fname)
    if ext in EXCLUDE_EXTENSIONS:
        return True
    return False

def create_zip():
    print(f"Creating submission ZIP: {ZIP_PATH}...")
    
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
        
    included_files = []
    
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(PROJECT_ROOT):
            # Prune excluded directories in-place
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            
            for f in files:
                full_path = Path(root) / f
                rel_path = full_path.relative_to(PROJECT_ROOT)
                rel_str = str(rel_path)
                
                if should_exclude(rel_str):
                    continue
                    
                zipf.write(full_path, arcname=rel_str)
                included_files.append(rel_str)

    print(f"\n[SUCCESS] Archive created: {ZIP_NAME}")
    print(f"Total files included: {len(included_files):,}")
    print(f"Archive file size: {ZIP_PATH.stat().st_size:,} bytes")
    
    # Audit verification of archive
    db_found = False
    secret_found = False
    with zipfile.ZipFile(ZIP_PATH, "r") as zipf:
        names = zipf.namelist()
        for name in names:
            if "knowledge_brain.db" in name:
                db_found = True
                info = zipf.getinfo(name)
                print(f"  [VERIFIED] Populated database in ZIP: {name} ({info.file_size:,} bytes uncompressed)")
            if ".env" in name or "secret" in name.lower() and not name.endswith(".py") and not name.endswith(".md"):
                print(f"  [ALERT] Possible secret in archive: {name}")
                secret_found = True
                
    assert db_found, "CRITICAL ERROR: knowledge_brain.db not found in archive!"
    assert not secret_found, "CRITICAL ERROR: Secret file found in archive!"
    print("  [VERIFIED] All security exclusions enforced (no credentials or env secrets included).")

if __name__ == "__main__":
    create_zip()
