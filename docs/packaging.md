# Empaquetado y distribución en macOS

Documento de apoyo del [README](../README.md). Describe cómo se construye
`dist/MacDirStat.app`, qué se verificó realmente en este Mac y qué queda
pendiente (firma Developer ID y notarización) con instrucciones exactas.

## 1. Build reproducible

```bash
./build_macos.sh                # crea/valida .venv, tests rápidos, icono, PyInstaller, verificaciones
./build_macos.sh --skip-tests   # omite pytest
./build_macos.sh --clean        # elimina build/ y dist/ antes de construir
./build_macos.sh --universal2   # exige Python universal2 y pide --target-arch universal2
./build_macos.sh --open         # abre la app al terminar
```

El script es idempotente y falla con mensaje claro si falta una herramienta
(`python3`, `iconutil`, `codesign`, `lipo`, `plutil`, `file`, `du`), si las
pruebas no pasan o si la arquitectura/Info.plist resultantes no son las
esperadas. Pasos internos:

1. Valida macOS y herramientas; crea `.venv` si no existe e instala
   `requirements.txt` + `requirements-dev.txt`.
2. Ejecuta la suite rápida con `QT_QPA_PLATFORM=offscreen`.
3. Genera `build/AppIcon.icns` con `scripts/make_icon.py` (Qt renderiza el SVG
   a `.iconset` y `iconutil` produce el `.icns`).
4. Lanza PyInstaller con `--clean --noconfirm` y `MacDirStat.spec`.
5. Verifica arquitectura (`file`, `lipo -archs`), `Info.plist`
   (`LSMinimumSystemVersion=13.0`, `NSHighResolutionCapable=true`,
   `CFBundleIdentifier`) y firma **ad-hoc** (`codesign`).

## 2. `MacDirStat.spec`

- **Modo onedir** (`COLLECT` + `BUNDLE`): arranque rápido y firma más simple
  que onefile.
- **Ventana, sin consola** (`console=False`).
- Bundle `com.sergiovalle.macdirstat`, versión `1.0.0`,
  `LSMinimumSystemVersion 13.0`, `NSHighResolutionCapable`,
  categoría `public.app-category.utilities`.
- `datas`: `app/resources/icons/app.svg` → `resources/icons` (la app lo
  resuelve con `resource_path()` desde `sys._MEIPASS`).
- **Exclusión de módulos Qt no usados** (WebEngine, QML/Quick, Multimedia,
  Pdf, 3D, Charts, etc.) más `tkinter`/`unittest`: reduce el tamaño final a
  ~96 MB.
- Sin `UPX`, sin entitlements, sin sandbox.

## 3. Resultado real del build (2026-10-17)

| Comprobación | Comando | Resultado |
|---|---|---|
| Ejecutable | `file dist/MacDirStat.app/Contents/MacOS/MacDirStat` | `Mach-O 64-bit executable arm64` |
| Arquitecturas | `lipo -archs …` | `arm64` |
| Info.plist | `plutil -extract LSMinimumSystemVersion raw …` | `13.0` |
| Alta resolución | `plutil -extract NSHighResolutionCapable raw …` | `true` |
| Bundle ID | `plutil -extract CFBundleIdentifier raw …` | `com.sergiovalle.macdirstat` |
| Versión | `plutil -extract CFBundleShortVersionString raw …` | `1.0.1` |
| Firma | `codesign -dv dist/MacDirStat.app` | `Signature=adhoc`; `codesign --verify --deep --strict` OK |
| Tamaño | `du -sh dist/MacDirStat.app` | 96 MB |
| Arranque + escaneo + captura | binario con `--scan /tmp/macdirstat-fixture --screenshot …` | exit 0, PNG correcto |
| Arranque tipo Finder | `open dist/MacDirStat.app --args --smoke-test --delay-ms 2000` | abre y se cierra solo |

Prueba manual pendiente (requiere interacción con pantalla): doble clic,
hover, arrastrar el splitter y **mover un archivo temporal a la Papelera desde
la app empaquetada**. El mismo código de papelera está cubierto por
`tests/test_macos_integration.py` (3 pruebas en verde).

## 4. Arquitecturas

- **Apple Silicon (verificado):** build por defecto; Python 3.13.3 universal2
  del entorno ejecutándose arm64 → `.app` arm64.
- **Intel (no verificado en este Mac):** ejecutar el build en un Mac Intel o
  con un Python `x86_64` bajo Rosetta 2; no mezclar binarios. El script
  comprueba con `lipo` que el binario contiene `$(uname -m)`.
- **universal2 (no generado; documentado):** el Python del entorno es
  universal2 y PySide6 publica wheels universal2, pero no se generó ni
  verificó un build universal2. Para intentarlo:

  ```bash
  ./build_macos.sh --universal2
  lipo -archs dist/MacDirStat.app/Contents/MacOS/MacDirStat   # debe incluir x86_64 y arm64
  ```

  El script falla si el resultado no incluye ambas. Si algún artefacto no
  resulta universal2, la recomendación del plan es entregar dos builds
  separados y documentarlo; **no se afirma universalidad sin verificarla**.

## 5. Permisos de macOS (TCC)

- La app **no** solicita privilegios de administrador y **no** ejecuta `sudo`.
- El selector nativo de carpetas concede acceso puntual a la carpeta elegida
  durante esa sesión; no desbloquea todo el disco.
- Para analizar zonas protegidas (Escritorio, Documentos, Descargas, partes de
  `~/Library` o `/System/Volumes/Data`) hay que conceder **Acceso Total al
  Disco** manualmente:
  1. Ajustes del Sistema → Privacidad y seguridad → Acceso total al disco.
  2. Añadir `MacDirStat.app` (o la app de desarrollo) y activarlo.
  3. Reiniciar la app y volver a analizar.
- Empaquetar como `.app` **no** concede ningún permiso; sin Acceso Total al
  Disco el resultado será parcial y la app lo mostrará como tal (banner de
  errores), nunca en silencio.
- Sin entitlements que eludan TCC, sin sandbox, sin red, sin telemetría.

## 6. Firma Developer ID y notarización (pendiente; procedimiento exacto)

En este entorno no hay credenciales de Apple, por lo que **no se ha firmado
con Developer ID ni notarizado**. La build local usa firma ad-hoc; Gatekeeper
puede pedir «Abrir» con clic derecho la primera vez. Para distribuir:

```bash
# 1) Firmar con Developer ID Application (Hardened Runtime, sin sandbox)
codesign --force --deep --options runtime --timestamp \
  --sign "Developer ID Application: TU NOMBRE (TEAMID)" dist/MacDirStat.app

# 2) Empaquetar y notarizar
ditto -c -k --keepParent dist/MacDirStat.app dist/MacDirStat.zip
xcrun notarytool submit dist/MacDirStat.zip \
  --apple-id "tu@apple.id" --team-id TEAMID --password "app-specific-password" --wait

# 3) Grapado y verificación
xcrun stapler staple dist/MacDirStat.app
spctl -a -vv dist/MacDirStat.app
```

Notas: `--deep` solo se usa para la firma ad-hoc local; para Developer ID,
firmar primero los binarios internos si fuese necesario o usar las
herramientas recomendadas por PyInstaller. Sin `stapler` el ticket viaja en el
ZIP pero no queda grapado a la `.app`; `spctl` debe aceptarla tras el grapado.

## 7. Diagnóstico de problemas frecuentes

| Síntoma | Causa probable | Solución |
|---|---|---|
| «La app no se puede abrir porque proviene de un desarrollador desconocido» | Build ad-hoc sin notarizar / cuarentena | Clic derecho → Abrir, o `xattr -dr com.apple.quarantine dist/MacDirStat.app` |
| «MacDirStat.app está dañada» | Cuarentena sobre un bundle firmado de forma inconsistente | Reconstruir con `./build_macos.sh --clean`; no mezclar arquitecturas |
| El escaneo muestra menos tamaño del esperado | TCC bloqueó carpetas protegidas | Conceder Acceso Total al Disco (§5) y reanalizar |
| `codesign --verify` falla tras tocar el bundle | Firma invalidada por copiar/editar archivos dentro | Re-firmar: `codesign --force --deep --sign - dist/MacDirStat.app` |
| PyInstaller no encuentra PySide6 | `.venv` incompleto | `rm -rf .venv && ./build_macos.sh` |
| El icono no aparece | `build/AppIcon.icns` ausente | `./build_macos.sh` (lo genera antes de PyInstaller) |

## 8. Privacidad

MacDirStat no realiza llamadas de red, no tiene telemetría ni analítica y solo
escribe preferencias en `QSettings` (dominio `com.sergiovalle.macdirstat`),
geometría de ventana y los archivos que el usuario elige mover a la Papelera.
