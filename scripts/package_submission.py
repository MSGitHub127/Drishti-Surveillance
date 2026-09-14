import os
import zipfile
import sys

def create_submission_zip():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    parent_dir = os.path.dirname(base_dir)
    zip_path = os.path.join(parent_dir, "team-vayunotics-gph26.zip")
    root_folder_name = "team-vayunotics-gph26"

    exclude_dirs = {"__pycache__", ".pytest_cache", ".git", ".venv", "venv", "env", ".idea", ".vscode"}
    exclude_extensions = {".pyc", ".pyo", ".pyd"}

    print(f"Creating submission zip: {zip_path}")
    total_files = 0

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zipf:
        for root, dirs, files in os.walk(base_dir):
            dirs[:] = [d for d in dirs if d not in exclude_dirs and not d.startswith(".")]

            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext in exclude_extensions:
                    continue
                if file.startswith("."):
                    continue

                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, base_dir)
                archive_name = os.path.join(root_folder_name, rel_path).replace("\\", "/")

                zipf.write(full_path, archive_name)
                total_files += 1

    size_mb = os.path.getsize(zip_path) / (1024 * 1024)
    print(f"Zip created successfully: {total_files} files packaged, size: {size_mb:.2f} MB")

if __name__ == "__main__":
    create_submission_zip()
