"""Clasificación de archivos por extensión y categoría."""

from __future__ import annotations

import os
from enum import StrEnum


class Category(StrEnum):
    DOCUMENTS = "documents"
    IMAGES = "images"
    VIDEO = "video"
    AUDIO = "audio"
    ARCHIVE = "archive"
    APPS = "apps"
    CODE = "code"
    SYSTEM = "system"
    OTHER = "other"


CATEGORY_LABELS: dict[Category, str] = {
    Category.DOCUMENTS: "Documentos",
    Category.IMAGES: "Imágenes",
    Category.VIDEO: "Vídeos",
    Category.AUDIO: "Audio",
    Category.ARCHIVE: "Comprimidos",
    Category.APPS: "Aplicaciones y paquetes",
    Category.CODE: "Bibliotecas y código",
    Category.SYSTEM: "Archivos del sistema",
    Category.OTHER: "Otros",
}

CATEGORY_ORDER: tuple[Category, ...] = (
    Category.DOCUMENTS,
    Category.IMAGES,
    Category.VIDEO,
    Category.AUDIO,
    Category.ARCHIVE,
    Category.APPS,
    Category.CODE,
    Category.SYSTEM,
    Category.OTHER,
)

_EXTENSIONS: dict[Category, frozenset[str]] = {
    Category.DOCUMENTS: frozenset(
        {
            "txt", "md", "markdown", "rtf", "pdf", "doc", "docx", "odt",
            "xls", "xlsx", "ods", "ppt", "pptx", "odp", "pages", "numbers",
            "keynote", "csv", "tsv", "epub", "mobi", "tex", "log", "eml",
        }
    ),
    Category.IMAGES: frozenset(
        {
            "jpg", "jpeg", "png", "gif", "heic", "heif", "tif", "tiff",
            "bmp", "webp", "svg", "raw", "dng", "cr2", "nef", "arw", "psd",
            "ai", "sketch", "fig",
        }
    ),
    Category.VIDEO: frozenset(
        {
            "mp4", "m4v", "mov", "avi", "mkv", "webm", "flv", "wmv",
            "mpg", "mpeg", "3gp", "ts", "mts", "m2ts", "vob",
        }
    ),
    Category.AUDIO: frozenset(
        {
            "mp3", "m4a", "wav", "aiff", "aif", "aac", "flac", "ogg",
            "opus", "wma", "alac", "mid", "midi",
        }
    ),
    Category.ARCHIVE: frozenset(
        {
            "zip", "rar", "7z", "tar", "gz", "bz2", "xz", "tgz", "tbz2",
            "txz", "zst", "lz4", "iso", "dmg", "pkg", "mpkg", "jar", "war",
            "tar.gz", "tar.bz2", "tar.xz", "tar.zst", "tar.lz4",
        }
    ),
    Category.APPS: frozenset({"app", "bundle", "framework", "xcodeproj", "playground"}),
    Category.CODE: frozenset(
        {
            "py", "pyi", "pyx", "js", "mjs", "cjs", "ts", "tsx", "jsx",
            "java", "kt", "kts", "c", "h", "cc", "cpp", "cxx", "hpp",
            "swift", "m", "mm", "rs", "go", "rb", "php", "sh", "bash",
            "zsh", "fish", "css", "scss", "sass", "less", "html", "htm",
            "xml", "yaml", "yml", "json", "toml", "ini", "cfg", "conf",
            "sql", "r", "lua", "pl", "scala", "dart", "vue", "svelte",
            "ipynb", "gradle", "cmake", "makefile", "dockerfile",
        }
    ),
    Category.SYSTEM: frozenset(
        {
            "plist", "kext", "dylib", "so", "a", "o", "dsym", "pem",
            "cer", "crt", "mobileprovision", "entitlements", "strings",
        }
    ),
}

_SYSTEM_PREFIXES = (
    "/System/",
    "/usr/",
    "/bin/",
    "/sbin/",
    "/dev/",
    "/Library/Apple/",
    "/cores/",
)

_SPECIAL_NAMES = {
    "makefile": Category.CODE,
    "cmakelists.txt": Category.CODE,
    "dockerfile": Category.CODE,
    ".gitignore": Category.CODE,
    ".zshrc": Category.CODE,
    ".bashrc": Category.CODE,
    ".profile": Category.CODE,
}

_COMPOUND_SUFFIXES = ("tar.gz", "tar.bz2", "tar.xz", "tar.zst", "tar.lz4")


def extension_of(name: str) -> str:
    """Extensión en minúsculas, sin punto; admite sufijos compuestos comunes."""
    lower = name.casefold()
    for suffix in _COMPOUND_SUFFIXES:
        if lower.endswith("." + suffix):
            return suffix
    stem, ext = os.path.splitext(name)
    if not stem or not ext:
        return ""
    return ext[1:].casefold()


def category_for(
    name: str,
    *,
    is_dir: bool = False,
    is_package: bool = False,
    path: str = "",
) -> Category:
    if is_package:
        return Category.APPS
    if is_dir:
        return Category.OTHER
    special = _SPECIAL_NAMES.get(name.casefold())
    if special is not None:
        return special
    ext = extension_of(name)
    if ext:
        for category, extensions in _EXTENSIONS.items():
            if ext in extensions:
                return category
    if path:
        normalised = path.replace(os.sep, "/")
        if any(normalised.startswith(prefix) for prefix in _SYSTEM_PREFIXES):
            return Category.SYSTEM
        if "/Library/" in normalised or normalised.startswith("/Library/"):
            return Category.SYSTEM
    return Category.OTHER


def categories_for_extension(ext: str) -> Category:
    return category_for(f"x.{ext}")
