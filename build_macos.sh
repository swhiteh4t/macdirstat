#!/bin/bash
# build_macos.sh — construye dist/MacDirStat.app de forma idempotente.
#
# Uso:
#   ./build_macos.sh                 # crea/valida .venv, tests rápidos, build nativa
#   ./build_macos.sh --skip-tests    # omite pytest
#   ./build_macos.sh --universal2    # exige Python universal2 y genera build universal2
#   ./build_macos.sh --clean         # elimina build/ y dist/ antes de construir
#   ./build_macos.sh --open          # abre la app al terminar
#
# Falla con mensaje claro si falta una herramienta, si las pruebas fallan o si
# la arquitectura resultante no es la esperada. La firma es ad-hoc (ver
# docs/packaging.md); sin credenciales no se firma con Developer ID.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO_DIR"

SKIP_TESTS=0
UNIVERSAL2=0
DO_CLEAN=0
DO_OPEN=0

for arg in "$@"; do
    case "$arg" in
        --skip-tests) SKIP_TESTS=1 ;;
        --universal2) UNIVERSAL2=1 ;;
        --clean)      DO_CLEAN=1 ;;
        --open)       DO_OPEN=1 ;;
        -h|--help)
            sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            echo "Opción desconocida: $arg (usa --help)" >&2
            exit 2
            ;;
    esac
done

fail() { echo "ERROR: $*" >&2; exit 1; }
note() { echo "==> $*"; }

# ---------------------------------------------------------------- entorno
[[ "$(uname -s)" == "Darwin" ]] || fail "Este script solo se ejecuta en macOS."

for tool in python3 iconutil codesign lipo plutil file du; do
    command -v "$tool" >/dev/null 2>&1 || fail "Falta la herramienta '$tool'."
done

VENV_PY=".venv/bin/python"
if [[ ! -x "$VENV_PY" ]]; then
    note "Creando .venv con python3 ($(python3 --version 2>&1))"
    python3 -m venv .venv
    "$VENV_PY" -m pip install --upgrade pip >/dev/null
    "$VENV_PY" -m pip install -r requirements.txt -r requirements-dev.txt
fi
[[ -x "$VENV_PY" ]] || fail "No se pudo crear/validar .venv."

if [[ "$UNIVERSAL2" -eq 1 ]]; then
    PLATFORM="$("$VENV_PY" -c 'import sysconfig; print(sysconfig.get_platform())')"
    [[ "$PLATFORM" == *universal2* ]] || fail \
        "Python del venv no es universal2 ($PLATFORM). Usa un Python universal2 para --universal2."
fi

pkgs="$("$VENV_PY" -c 'import PySide6, sys; print("PySide6", PySide6.__version__)')" \
    || fail "PySide6 no está instalado en .venv."
note "Entorno: $pkgs, $(uname -m), $(sw_vers -productVersion)"

# ---------------------------------------------------------------- pruebas
if [[ "$SKIP_TESTS" -eq 0 ]]; then
    note "Ejecutando pruebas rápidas (offscreen)…"
    QT_QPA_PLATFORM=offscreen "$VENV_PY" -m pytest -q \
        || fail "Las pruebas fallaron; se cancela el empaquetado."
else
    note "Pruebas omitidas (--skip-tests)."
fi

# ---------------------------------------------------------------- limpieza
if [[ "$DO_CLEAN" -eq 1 ]]; then
    note "Eliminando build/ y dist/ (--clean)"
    rm -rf build dist
fi

# ---------------------------------------------------------------- icono
note "Generando icono (scripts/make_icon.py)"
mkdir -p build
"$VENV_PY" scripts/make_icon.py >/dev/null
[[ -f build/AppIcon.icns ]] || fail "No se generó build/AppIcon.icns."

# ---------------------------------------------------------------- PyInstaller
PYINSTALLER_ARGS=(--noconfirm --clean --log-level=WARN MacDirStat.spec)
if [[ "$UNIVERSAL2" -eq 1 ]]; then
    PYINSTALLER_ARGS=(--target-arch universal2 "${PYINSTALLER_ARGS[@]}")
fi
note "Construyendo .app con PyInstaller…"
"$VENV_PY" -m PyInstaller "${PYINSTALLER_ARGS[@]}" \
    || fail "PyInstaller falló."

APP="dist/MacDirStat.app"
BIN="$APP/Contents/MacOS/MacDirStat"
[[ -x "$BIN" ]] || fail "No se generó $BIN."

# ---------------------------------------------------------------- verificación
note "Verificando arquitectura"
ARCHS="$(lipo -archs "$BIN")"
echo "    file: $(file -b "$BIN")"
echo "    lipo -archs: $ARCHS"
if [[ "$UNIVERSAL2" -eq 1 ]]; then
    [[ "$ARCHS" == *"x86_64"* && "$ARCHS" == *"arm64"* ]] \
        || fail "Se pidió universal2 pero lipo devuelve: $ARCHS"
    if [[ "$ARCHS" != *"x86_64 arm64"* && "$ARCHS" != *"arm64 x86_64"* ]]; then
        note "Aviso: hay binarios auxiliares con arquitecturas parciales; revisa con:"
        note "  find dist/MacDirStat.app -type f -perm +111 -exec sh -c 'lipo -archs \"\$0\" 2>/dev/null | grep -qv \"x86_64 arm64\" && echo \"\$0\"' {} \\;"
    fi
else
    NATIVE="$(uname -m)"
    [[ "$ARCHS" == *"$NATIVE"* ]] || fail "Se esperaba $NATIVE en el binario, lipo devuelve: $ARCHS"
fi

note "Verificando Info.plist"
plutil -extract LSMinimumSystemVersion raw "$APP/Contents/Info.plist" \
    | grep -q '^13\.0$' || fail "LSMinimumSystemVersion != 13.0"
plutil -extract NSHighResolutionCapable raw "$APP/Contents/Info.plist" \
    | grep -qi '^true$' || fail "NSHighResolutionCapable != true"
BUNDLE_ID_PLIST="$(plutil -extract CFBundleIdentifier raw "$APP/Contents/Info.plist")"
[[ "$BUNDLE_ID_PLIST" == "com.sergiovalle.macdirstat" ]] \
    || fail "CFBundleIdentifier inesperado: $BUNDLE_ID_PLIST"

note "Verificando firma ad-hoc"
if ! codesign -dv "$APP" 2>&1 | grep -q '^Signature=adhoc$'; then
    note "Firmando ad-hoc (fallback)"
    codesign --force --deep --sign - "$APP"
fi
codesign -dv "$APP" 2>&1 | grep '^Signature=' | sed 's/^/    /'
codesign --verify --deep --strict "$APP" \
    || fail "La verificación de firma ad-hoc falló (codesign --verify)."

note "Build correcta: $APP ($(du -sh "$APP" | cut -f1))"
note "Lanzar con: open $APP   (o $BIN --scan <carpeta>)"
note "Recuerda: la app no está firmada con Developer ID ni notarizada (ver docs/packaging.md)."

if [[ "$DO_OPEN" -eq 1 ]]; then
    note "Abriendo la app…"
    open "$APP"
fi

exit 0
