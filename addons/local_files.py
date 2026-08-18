from pathlib import Path

from addons.base import Addon, AddonResult
from backend.settings import Settings

MAX_CHARS = 8_000
MAX_LIST_ENTRIES = 200
TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".json", ".log", ".py", ".yaml", ".yml", ".ini", ".xml"}


class LocalFilesAddon(Addon):
    """Read-only access to files inside folders the user has explicitly
    allow-listed via FENRIS_LOCAL_FOLDERS. Listing is unrestricted among those
    folders; reading a file's contents requires confirmation, since it's the
    step that actually exposes file content to the model."""

    id = "local_files"
    name = "Local files"
    description = "List and read files inside folders the user has explicitly allowed."
    required_role = "user"

    def run(self, actor_name: str, actor_role: str, action: str, payload: dict, confirmed: bool) -> AddonResult:
        if action == "list":
            return self._list(payload)
        if action == "read":
            if not confirmed:
                path = payload.get("path", "")
                return AddonResult("confirmation_required", f"Ready to read {path}. Confirm to open it.", payload)
            return self._read(payload)
        return AddonResult("invalid", "Supported actions: list, read.")

    @staticmethod
    def _resolve(raw_path: str) -> Path | None:
        """raw_path resolved to an absolute path, but only if it's inside one
        of the allowed folders (or is one itself) — otherwise None."""
        if not raw_path:
            return None
        try:
            resolved = Path(raw_path).expanduser().resolve()
        except (OSError, RuntimeError):
            return None
        for folder in Settings.LOCAL_DATA_FOLDERS:
            if resolved == folder or folder in resolved.parents:
                return resolved
        return None

    def _list(self, payload: dict) -> AddonResult:
        if not Settings.LOCAL_DATA_FOLDERS:
            return AddonResult(
                "invalid", "No local folders are configured. Set FENRIS_LOCAL_FOLDERS in .env to enable this."
            )
        raw_path = (payload.get("path") or "").strip()
        if raw_path:
            folder = self._resolve(raw_path)
            if folder is None or not folder.is_dir():
                return AddonResult("invalid", f"{raw_path} isn't an allowed folder.")
            folders = [folder]
        else:
            folders = Settings.LOCAL_DATA_FOLDERS

        entries = []
        for folder in folders:
            if not folder.is_dir():
                continue
            for item in sorted(folder.iterdir()):
                entries.append({"name": item.name, "path": str(item), "is_folder": item.is_dir()})
                if len(entries) >= MAX_LIST_ENTRIES:
                    break
            if len(entries) >= MAX_LIST_ENTRIES:
                break
        return AddonResult("complete", f"Found {len(entries)} items.", {"entries": entries})

    def _read(self, payload: dict) -> AddonResult:
        raw_path = payload.get("path", "")
        resolved = self._resolve(raw_path)
        if resolved is None:
            return AddonResult("invalid", f"{raw_path} is outside the folders Fenris is allowed to read.")
        if not resolved.is_file():
            return AddonResult("invalid", f"No file found at {raw_path}.")
        text = self._extract_text(resolved)
        if text is None:
            return AddonResult("invalid", f"Couldn't read {resolved.name} — unsupported or unreadable file.")
        return AddonResult("complete", f"Read {resolved.name}.", {"path": str(resolved), "text": text[:MAX_CHARS]})

    @staticmethod
    def _extract_text(path: Path) -> str | None:
        suffix = path.suffix.lower()
        try:
            if suffix == ".pdf":
                from pypdf import PdfReader

                reader = PdfReader(str(path))
                return "\n".join((page.extract_text() or "") for page in reader.pages).strip()
            if suffix == ".docx":
                import docx

                document = docx.Document(str(path))
                return "\n".join(paragraph.text for paragraph in document.paragraphs).strip()
            if suffix in TEXT_EXTENSIONS:
                return path.read_text(encoding="utf-8", errors="replace").strip()
            return None
        except Exception:
            return None
