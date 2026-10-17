# Arquitectura de MacDirStat

Documento de apoyo del [README](../README.md). Describe las capas, el flujo de
datos y las decisiones de concurrencia del código real en `app/`.

## 1. Capas

```text
main.py                     arranque CLI (--scan/--smoke-test/--screenshot)
app/application.py          QApplication, tema, recursos
app/main_window.py          integración de UI, acciones, estado, papelera
app/workers/                concurrencia Qt (escaneo QThread, snapshot QThreadPool)
app/scanner/                recorrido puro con os.scandir (sin Qt)
app/models/                 FileNode, ScanResult, categorías (sin Qt)
app/treemap/                motor squarified + QWidget de pintado
app/views/                  árbol, panel de detalles, filtros, leyenda, mayores
app/services/               filtros, acciones de archivo, preferencias (QSettings)
app/theme.py                paleta clara/oscura y colores de categorías
```

Regla de dependencias: **el núcleo no conoce a Qt**. `file_node.py`,
`categories.py`, `filesystem_scanner.py`, `layout_engine.py` y `filter_engine.py`
funcionan sin `QApplication` y por eso las pruebas puras no crean Qt. La UI
(`main_window.py`, `views/`, `treemap_widget.py`, `workers/`) depende del núcleo,
nunca al revés.

## 2. Flujo de datos

```text
elegir carpeta
   │
   ▼
ScanController ── QThread ──► FileSystemScanner.scan()
   │  señales: started/finished/progress/failed          produce ScanResult
   ▼                                                     (árbol inmutable,
MainWindow._on_scan_finished                              errores, stats)
   │
   ├─► SnapshotController ── QThreadPool(QRunnable) ──► FilterEngine.build_snapshot()
   │      generaciones: resultados obsoletos se descartan        │ FilterSnapshot
   ▼                                                              ▼
vistas (Treemap / QTreeView / Mayores / detalles/leyenda) ◄── snapshot + métrica
```

- **`FilterSnapshot`** es la única fuente de verdad para las vistas: contiene
  los totales originales y filtrados, la métrica activa, los mayores N y, si
  hay filtros, los conjuntos visibles/agregados por nodo.
- Seleccionar una carpeta, filtrar, buscar, cambiar métrica o tema **no vuelve
  a tocar el disco**: solo se reconstruye el snapshot (normalmente < 40 ms para
  100 000 nodos; se ejecuta en hilo aparte cuando es grande).
- La papelera es la única operación que muta el árbol: tras confirmar y mover,
  `MainWindow` poda el nodo, recalcula los totales de los ancestros, invalida
  layout y snapshot y marca el resultado como «modificado».

## 3. Escaneo (Fase 1–3)

`FileSystemScanner` (sin Qt):

- Recorrido iterativo con `os.scandir` y `DirEntry.stat(follow_symlinks=False)`;
  post-orden para agregar totales por directorio.
- **Nunca sigue enlaces simbólicos**; detecta ciclos de directorios por
  `(st_dev, st_ino)`.
- Deduplicación de enlaces duros por `(st_dev, st_ino)` con `st_nlink > 1`:
  las métricas lógicas/asignadas cuentan cada entrada y la métrica «asignado
  único» cuenta el inodo una sola vez (ver `size-methodology.md`).
- No cruza `st_dev` salvo que `ScanOptions.cross_device=True`; los puntos de
  montaje quedan como nodos `SKIPPED_MOUNT` visibles.
- Los `OSError` no interrumpen: se guardan (con límite de errores), se cuenta
  el error y el resultado pasa a `PARTIAL`. La UI muestra un banner.
- Cancelación cooperativa con `threading.Event` comprobado en cada directorio
  y cada 256 entradas; progreso limitado por `progress_interval_ms` (100 ms).
  Una syscall de red bloqueada no puede interrumpirse y así se documenta.

`ScanWorker`/`ScanController` envuelven el escáner en un `QThread` con señales
Qt (`progress`, `finished`, `failed`). Nunca se usa `QThread.terminate()`; al
cerrar o rescanear se cancela y se espera.

## 4. Treemap (Fases 1–3)

- `TreemapLayoutEngine` implementa el algoritmo *squarified* sobre un área de
  `LayoutRequest`: agrupa por área mínima visible (`min_tile_area`), agrega
  fichas pequeñas en «Otros (N)» con suma exacta y limita profundidad
  (`max_depth`), fichas (`max_tiles`) y ancho de nivel (`max_children_per_level`).
  Si trunca, lo indica (`truncated=True`).
- Dos modos: `SUBTREE` (todos los descendientes agrupados visualmente con
  encabezado de directorio) y `CHILDREN` (solo hijos inmediatos; los
  directorios son una ficha). El modo activo se persiste en preferencias.
- `HitIndex`: malla de 32 px para resolver clics en O(1) aproximado cuando hay
  muchas fichas; con pocas fichas, búsqueda lineal.
- `TreemapWidget` pinta con `QPainter` y no mantiene estado pesado: dibuja el
  layout ya calculado, `clip` por evento y fuente reducida con elipsis. El
  layout se calcula en el hilo de UI solo si el snapshot es pequeño
  (≤ 5 000 elementos); si no, se ejecuta en `QThreadPool` con contador de
  generación y se descartan resultados obsoletos.
- Caché de layout por `(revision, root, métrica, modo, área mínima, tamaño)`.
- Selección/hover se resuelven con `HitIndex`; un clic selecciona, doble clic
  en directorio hace zoom y en archivo lo abre.

## 5. Filtros y snapshot (Fase 2–3)

`FilterEngine` (sin Qt) soporta: búsqueda por texto (nombre y extensión con
sintaxis `.ext`), extensiones, categorías, rango de tamaño, ocultos, 0 bytes,
directorios excluidos y umbral de ficha mínima. El caso identidad (todo
visible) no recorre el árbol: reutiliza los totales del `ScanResult`.

Reglas de visibilidad: un nodo es visible si cumple los filtros de atributos y
texto; los directorios sobreviven si algún descendiente sobrevive; los
expedientes agregados se dibujan como «Otros (N)» y nunca pierden suma. La UI
muestra **totales originales y filtrados** por separado para evitar confusiones.

`SnapshotController` ejecuta la construcción en `QThreadPool` con debounce de
búsqueda (200–250 ms en la UI) y número de generación.

## 6. Acciones y papelera (Fase 3)

`FileActions` valida antes de mutar: ruta absoluta contenida en la raíz del
análisis, no raíz, `lstat` nuevo y coincidencia de `st_dev`/`st_ino`/tipo para
todo el camino. La confirmación (`QMessageBox` o diálogo propio) muestra
nombre, ruta y tamaño. Solo entonces llama a `QFile.moveToTrash` (API nativa,
sin borrado permanente). Si algo falla, el árbol no se muta.

Las pruebas inyectan una función de papelera falsa; la integración real está en
`tests/test_macos_integration.py` (opt-in) y limpia `~/.Trash` al terminar.

## 7. Preferencias y tema

`SettingsManager` envuelve `QSettings` con claves tipadas: última carpeta,
tema (`system`/`claro`/`oscuro`), métrica, modo de treemap, filtros, umbral de
ficha, top-N, vistas visibles y geometría/splitter. La restauración de
geometría valida que la ventana siga visible en las pantallas actuales.

`theme.py` construye la paleta según `QStyleHints.colorScheme()` con colores
propios por categoría para claro/oscuro y aplica un stylesheet. La leyenda es
la fuente de verdad de las categorías (no solo el color).

## 8. Qué no hace (y por qué)

- Sin red, sin telemetría, sin analítica.
- Sin sandbox ni privilegios de administrador: en zonas TCC-protected el
  resultado será parcial y se marca como tal (ver `packaging.md`).
- Sin borrado permanente ni papelera automática.
- Sin hilos adicionales más allá de los tres puntos medidos (escaneo,
  snapshot, layout asíncrono de subárboles grandes).
