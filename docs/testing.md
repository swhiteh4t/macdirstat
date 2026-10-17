# Pruebas y resultados reales

Documento de apoyo del [README](../README.md). Los resultados de este documento
se copian de ejecuciones reales realizadas en el Mac de desarrollo; no se
inventan ni se trasladan de otros equipos. Cada tabla indica fecha y entorno.

## 1. Cómo ejecutar

```bash
source .venv/bin/activate

# Suite rápida, sin pantalla (140 pruebas; excluye slow y macos_integration)
QT_QPA_PLATFORM=offscreen pytest -q

# Con pantalla real (misma suite; útil para descartar regresiones del backend gráfico)
pytest -q

# Integración real con macOS (Papelera nativa) — mueve un archivo temporal
# a ~/.Trash y lo elimina de allí al terminar
QT_QPA_PLATFORM=offscreen pytest -m macos_integration -v

# Pruebas de carga (marcador slow)
pytest -q -m slow

# Benchmarks (no forman parte de pytest)
python benchmarks/make_fixture.py --files 100000
python benchmarks/bench_scan.py --fixture benchmarks/tmp/fixture-100000 --paint 60
```

`pyproject.toml` fija `addopts = "-ra -m 'not slow and not macos_integration'"`,
por lo que una ejecución normal nunca toca la Papelera ni crea 100 000 archivos.
`tests/conftest.py` fija `QT_QPA_PLATFORM=offscreen` antes de crear la
`QApplication`.

## 2. Resultado de la suite (ejecución real)

- **Fecha:** 2026-10-17
- **Entorno:** macOS 26.6.2 arm64, 10 CPUs, Python 3.13.3, PySide6 6.10.3,
  pytest 9.1.1, pytest-qt 4.5.0

| Comando | Resultado |
|---|---|
| `QT_QPA_PLATFORM=offscreen pytest -q` | **140 passed, 3 deselected** en 3.3 s |
| `pytest -m macos_integration -v` | **3 passed** en 0.13 s (Papelera real, limpieza verificada) |
| `pytest -q -m slow` | 0 pruebas marcadas `slow` (la carga se mide con benchmarks, ver §5) |

### Distribución por archivo (140 pruebas)

| Archivo | Pruebas | Cobertura |
|---|---|---|
| `test_categories.py` | 38 | Extensión → categoría, mayúsculas, comprimidos compuestos (`tar.gz`…), sin extensión |
| `test_scanner.py` | 19 | Recorrido, agregados, errores, symlinks, enlaces duros, permisos, desaparición |
| `test_treemap_layout.py` | 18 | Squarified, invariantes, agregación, hit-test, subárbol |
| `test_main_window.py` | 18 | Integración de UI completa (selección, filtros, métrica, papelera, banner) |
| `test_file_actions.py` | 13 | Validación de inodo/ruta/tipo, apertura, Finder, portapapeles, papelera falsa |
| `test_filters.py` | 13 | Búsqueda, extensiones, categorías, ocultos, ceros, exclusiones, snapshot |
| `test_treemap_widget.py` | 12 | Clic, doble clic, teclado, zoom, resize, tooltip escapado, agregados |
| `test_settings.py` | 6 | Valores por defecto, roundtrip, valores inválidos, geometría |
| `test_scan_cancel.py` | 3 | Cancelación con resultado parcial, corte temprano, escaneo completo |
| `test_macos_integration.py` | 3 (opt-in) | `QFile.supportsMoveToTrash`, papelera nativa real y vía `FileActions` |

## 3. Matriz obligatoria del enunciado (casos 1–20)

Todos ejecutados y en verde el 2026-10-17 (caso 10 completo; se omite
automáticamente si alguien ejecuta la suite como root).

| # | Caso | Prueba | Estado |
|---|---|---|---|
| 1 | Directorio vacío | `test_scanner.py::test_empty_directory` | ✅ |
| 2 | Un único archivo | `test_scanner.py::test_single_file` | ✅ |
| 3 | Archivos de tamaño cero | `test_scanner.py::test_zero_byte_files` | ✅ |
| 4 | Archivos pequeños y grandes | `test_scanner.py::test_size_accounting` | ✅ |
| 5 | Directorios anidados | `test_scanner.py::test_nested_directories` | ✅ |
| 6 | Nombres Unicode | `test_scanner.py::test_unicode_names` | ✅ |
| 7 | Extensiones diferentes | `test_categories.py`, `test_scanner.py` | ✅ |
| 8 | Enlaces simbólicos | `test_scanner.py::test_symlink_not_followed` | ✅ |
| 9 | Ciclos potenciales | `test_scanner.py::test_symlink_cycle_does_not_recurse` | ✅ |
| 10 | Archivos inaccesibles | `test_scanner.py::test_permission_denied_is_recorded` | ✅ (skip si root) |
| 11 | Archivos que desaparecen | `test_scanner.py::test_file_disappears_mid_scan` | ✅ |
| 12 | Cancelación | `test_scan_cancel.py::test_cancel_returns_partial_result` | ✅ |
| 13 | Tamaños acumulados | `test_scanner.py::test_directory_aggregates` | ✅ |
| 14 | Aplicar/retirar filtros | `test_filters.py::test_apply_and_clear_filters` | ✅ |
| 15 | Ordenación por tamaño | `test_filters.py::test_largest_rankings_filtered`, modelo | ✅ |
| 16 | Selección de rectángulos | `test_treemap_layout.py::test_hit_test_*`, `test_treemap_widget.py::test_click_*` | ✅ |
| 17 | Cambio de directorio en el mapa | `test_treemap_widget.py::test_zoom_and_back_changes_root`, `test_main_window.py::test_zoom_and_back_with_breadcrumb` | ✅ |
| 18 | Enlaces duros | `test_scanner.py::test_hardlink_policies` | ✅ |
| 19 | Redimensionado | `test_treemap_widget.py::test_resize_relayout` | ✅ |
| 20 | Apertura/papelera seguras | `test_file_actions.py` (papelera falsa) + `test_macos_integration.py` (papelera real, opt-in) | ✅ |

### Casos sintéticos del treemap (plan §8.3)

| Caso | Prueba |
|---|---|
| Todos del mismo tamaño (cuadrícula) | `test_equal_sizes_grid_like` |
| Un archivo domina la superficie | `test_dominant_file_matches_share` |
| Tamaños muy dispares | `test_area_proportional_to_size`, `test_no_overlap_between_siblings` |
| Agregación sin pérdida de suma | `test_aggregation_preserves_sum_and_membership`, `test_no_aggregation_when_all_visible` |
| Todo a cero / árbol vacío | `test_zero_and_empty_tree`, `test_empty_snapshot_message_no_crash` |
| Invariantes (dentro de límites, sin solapes, proporcionalidad, determinismo) | `test_all_rects_inside_bounds`, `test_area_sum_equals_rect`, `test_deterministic_layout` |
| Subárbol: contención y proporcionalidad por nivel | `test_subtree_children_inside_parent`, `test_subtree_level_proportionality`, `test_subtree_collapses_tiny_directories` |
| Límite de fichas | `test_tile_count_and_max` |

### Pruebas de UI (plan §8.4)

| Caso | Prueba |
|---|---|
| Estado vacío al arrancar | `test_main_window.py::test_starts_with_empty_state` |
| Selección sincronizada mapa ↔ árbol ↔ detalles | `test_tree_selection_updates_details_and_treemap`, `test_treemap_selection_updates_tree_and_details` |
| Tooltip con `<script>` escapado | `test_treemap_widget.py::test_tooltip_escapes_html` |
| Zoom, breadcrumb y atrás | `test_zoom_and_back_with_breadcrumb` |
| Cambio de métrica actualiza etiquetas | `test_metric_change_updates_labels` |
| Papelera cancelada no muta el árbol | `test_trash_cancelled_does_not_mutate` |
| Resultado parcial muestra banner | `test_partial_result_shows_banner` |
| Tema claro/oscuro conserva colores de categoría | `test_theme_switch_keeps_category_colors` |

## 4. Cobertura de las fases del plan (verificación, no solo tests)

| Verificación manual | Comando usado | Resultado real |
|---|---|---|
| Ventana abre/cierra offscreen | `QT_QPA_PLATFORM=offscreen python main.py --smoke-test --delay-ms 1200` | exit 0 |
| Escaneo real con captura | `python main.py --scan /tmp/macdirstat-fixture --screenshot /tmp/shot.png --delay-ms 2500` | PNG con treemap, leyenda, filtros, estado (ver README) |
| App empaquetada, escaneo y captura | `dist/MacDirStat.app/Contents/MacOS/MacDirStat --scan … --screenshot …` | exit 0, PNG correcto |
| App empaquetada desde Finder (aprox. con `open`) | `open dist/MacDirStat.app --args --smoke-test --delay-ms 2000` | arranca y se cierra sola |
| Papelera real | `pytest -m macos_integration` | 3 passed; sin restos en `~/.Trash` (verificado) |

No automatizado (requiere interacción manual con pantalla real): gestos de
ratón sobre la ventana visible (doble clic, hover, arrastrar splitter), mover a
la Papelera desde la `.app` empaquetada (el mismo código está cubierto por la
integración) y la firma/notarización con Developer ID (ver `packaging.md`).

## 5. Benchmarks reales (fixture de 100 000 archivos)

- **Fecha:** 2026-10-17 19:52
- **Entorno:** macOS 26.6.2 (arm64), 10 CPUs, Python 3.13.3, PySide6 6.10.3
- **Fixture:** `benchmarks/tmp/fixture-100000` — 100 000 archivos en 100
  carpetas, 163.7 MB lógicos (19 969 de 0 bytes), semilla `20261017`,
  creado en 6.642 s
- **Métrica:** espacio asignado (`st_blocks × 512`), la métrica por defecto
- **Comandos:** `python benchmarks/make_fixture.py --files 100000` y
  `python benchmarks/bench_scan.py --fixture benchmarks/tmp/fixture-100000 --paint 60`

| Medición | Valor |
|---|---|
| Escaneo (100 000 archivos, 0 errores) | 1.264 s (otras ejecuciones del mismo fixture: 0.55–0.69 s; variación de caché/carga) |
| Progreso | 14 eventos, intervalo máximo 0.102 s |
| Cancelación (solicitada a los 0.25 s) | latencia 0.017 s |
| Snapshot de filtros (identidad) | 0.034 s |
| Layout subárbol completo | 0.195 s, 60 000 fichas (truncado al límite de fichas) |
| Layout subárbol ~10 000 fichas | 0.075 s, 9 110 fichas |
| Layout nivel actual | 0.000 s, 100 fichas |
| RSS tras escanear (base 24.7 MB) | 74.2 MB (Δ 49.5 MB) |
| RSS máximo total (pico con layout+repintado) | 200.6 MB |
| Repintado 60 000 fichas (offscreen, n=60) | media 58.2 ms, p95 59.3 ms |
| Repintado 4 218 fichas (offscreen, n=60) | media 11.2 ms, **p95 11.5 ms** |

Contraste con los objetivos del plan:

| Objetivo | Objetivos del plan | Medido | Estado |
|---|---|---|---|
| Progreso visible cada | ≤ 200 ms | 102 ms máx. | ✅ |
| Layout 10 000 fichas | p95 ≤ 300 ms | 75 ms (mínimo de 3 ejecuciones) | ✅ |
| Repintado 5 000 fichas | p95 ≤ 16 ms | 11.5 ms (n=60) | ✅ |
| Memoria 100 000 nodos | ≤ 300 MB adicionales | +49.5 MB tras escaneo | ✅ |
| Cancelación perceptible | — | 17 ms | ✅ |

Los informes crudos se regeneran en `benchmarks/tmp/bench-scan.md` y
`benchmarks/tmp/bench-scan.json` (no versionados). Notas de honestidad:

- El repintado se midió con `QWidget.render()` sobre un `QPixmap` persistente
  con plataforma `offscreen`; no incluye composición de ventana en pantalla.
- El repintado con el umbral por defecto de este fixture concreto genera
  60 000 fichas y tarda ~59 ms; la app ofrece el ajuste «Ficha mín.» para
  reducirlas. La agregación por superficie es configurable precisamente por
  esto.
- Los tiempos son de una máquina concreta; no se extrapolan a otros equipos.
