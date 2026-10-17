# MacDirStat — Plan de implementación

**Aplicación:** analizador de espacio en disco para macOS, inspirado en GrandPerspective y WinDirStat.
**Repositorio:** raíz de este proyecto (local; ver `README.md`)
**Versión del plan:** 1.0 — 2026-10-17
**Estado:** plan aprobado; **no hay código implementado todavía**. Este documento es el contrato de ejecución.

---

## 1. Resumen ejecutivo

MacDirStat será una aplicación de escritorio nativa para macOS, 100 % local y sin red, construida con Python 3.13, PySide6 6.10.3 y un widget propio de `QPainter`. El usuario seleccionará una carpeta o volumen, un escaneo en segundo plano construirá un árbol de `FileNode` con tamaños lógicos y asignados, y la interfaz mostrará:

- un treemap *squarified* navegable, con agregación explícita de elementos diminutos;
- una vista de árbol y una vista de mayores consumidores;
- búsqueda, filtros y categorías por extensión;
- un panel de detalles con métricas diferenciadas y acciones seguras;
- envío a la Papelera de macOS únicamente mediante acción explícita y confirmada.

La implementación se divide en cuatro fases con criterios de salida verificables. La Fase 1 debe dejar una aplicación utilizable de extremo a extremo; las fases 2–4 añaden exploración, precisión y distribución. Cada fase termina con ejecución real de la app, pruebas y corrección de defectos antes de avanzar.

**Criterio de éxito final:** abrir la app en macOS, elegir una carpeta, ver el mapa sin bloqueos, seleccionar y navegar elementos, consultar detalles, identificar los mayores consumidores y cancelar/repetir escaneos, todo sin que la interfaz deje de responder.

---

## 2. Entorno verificado (2026-10-17)

Comprobaciones ejecutadas en este equipo antes de escribir el plan:

| Elemento | Resultado verificado | Implicación |
|---|---|---|
| SO | macOS 26.6.2, build 25G83 | Plataforma de desarrollo y prueba real |
| Arquitectura | Apple Silicon (`arm64`) | Build nativo por defecto; universal2 a verificar |
| Python | 3.13.3, framework `/Library/Frameworks/Python.framework/Versions/3.13` | Cumple «3.12 o compatible»; binario **universal2** (`x86_64 arm64`) |
| PySide6 | No instalado | Se instalará en `.venv` |
| pytest / pytest-qt / PyInstaller | No instalados | Se instalarán como dependencias de desarrollo |
| Repositorio | Directorio vacío | Se crea toda la estructura |
| Espacio libre | ~30 GiB en el volumen de datos (94 % usado) | Suficiente para el fixture de 100 000 archivos; vigilar durante benchmarks |
| Herramientas macOS | Command Line Tools, `/usr/bin/codesign`, `iconutil`, `sips` presentes | Icono y firma ad-hoc posibles; notarización requiere certificado |
| PyPI | `PySide6 6.10.3` → wheel `macosx_13_0_universal2`, requiere Python `<3.15` | **macOS mínimo: 13.0 Ventura** |
| PyPI | `PySide6 6.12.0` → wheel `macosx_14_0_universal2` | No se usa: elevaría el mínimo a macOS 14 |
| PyPI | `pytest-qt 4.5.0`, `PyInstaller 6.22.3`, `pytest 9.1.1` disponibles | Versiones candidatas; se fijan las compatibles en Fase 0 |

Notas:

- No se ha instalado ni ejecutado nada de la aplicación todavía. Los resultados de pruebas y rendimiento se registrarán **solo** tras ejecutarlos.
- El entorno no demuestra compatibilidad con Intel; el wheel universal2 de PySide6 y el Python universal2 la hacen viable, pero se verificará con `lipo` y, si hay acceso, en un Mac Intel o bajo Rosetta.

---

## 3. Decisiones de producto y técnicas

### 3.1. Identidad y compatibilidad

| Decisión | Valor |
|---|---|
| Nombre visible | **MacDirStat** |
| Bundle ID | `com.sergiovalle.macdirstat` |
| Versión inicial | `0.1.0`; `1.0.0` al cerrar Fase 4 |
| macOS mínimo | **13.0 Ventura** (impuesto por PySide6 6.10.3) |
| Python | `>=3.12,<3.15`; entorno de desarrollo 3.13.3 |
| PySide6 | `==6.10.3` |
| Frameworks | Qt Widgets, Qt Core, Qt Gui; sin WebEngine, sin QML |
| Dependencias runtime | Solo PySide6 |
| Dependencias dev | pytest, pytest-qt, PyInstaller |
| Red | Ninguna llamada de red; sin telemetría ni analítica |
| Sandbox | App **no sandboxed**; sujeta a TCC de macOS |

### 3.2. Modo de treemap

Se implementan dos modos, ambos con el mismo motor puro:

1. **Subárbol (predeterminado en 1.0):** muestra todos los descendientes del directorio actual, agrupados visualmente por directorio. Cada archivo visible tiene su propio rectángulo; los directorios dibujan borde/encabezado y contienen a sus hijos. El detalle se limita por área mínima visible, no por profundidad arbitraria.
2. **Nivel actual:** muestra solo los hijos inmediatos; los directorios son una ficha agregada. Es el modo de la Fase 1 y el *fallback* para subárboles enormes.

La Fase 1 usa «Nivel actual» para entregar rápido un MVP correcto. La Fase 2 añade «Subárbol» con agregación y lo convierte en predeterminado. Todo elemento agrupado por tamaño mínimo se representa con una ficha sintética «Otros (N)» cuyo tamaño es la suma exacta; al hacer clic se listan los elementos originales. **Nunca se ocultan datos en silencio.**

### 3.3. Métricas de tamaño

Se almacenan y muestran por separado:

| Métrica | Cálculo | Uso |
|---|---|---|
| Lógico | `st_size` | Métrica alternativa (tamaño declarado, no ocupado) |
| Asignado | `st_blocks * 512` | **Métrica de visualización y porcentajes por defecto** (espacio real en disco) |
| Asignado único | Asignado, contando cada inodo una sola vez | Estimación con deduplicación de enlaces duros |
| Volumen | `os.statvfs`: total y disponible | Contexto; **no** se suma al análisis |

Nunca se afirmará que el tamaño lógico, ni siquiera el asignado, es el espacio recuperable exacto. Clones APFS, compresión transparente, snapshots, archivos purgables y metadatos hacen que el espacio liberable real sea distinto. El panel de detalles incluirá esa advertencia junto a las cifras.

### 3.4. Enlaces duros, simbólicos, paquetes y montajes

- **Enlaces simbólicos:** se usa `lstat`; nunca se siguen. Se cuenta el tamaño del propio enlace. Un enlace a un directorio no provoca recursión ni ciclos.
- **Enlaces duros:** se detectan por `(st_dev, st_ino)` cuando `st_nlink > 1`. La métrica lógica/asignada cuenta cada entrada por defecto; la métrica «asignado único» cuenta el inodo una vez (primer camino encontrado) y marca los duplicados. El panel de detalles indica el número de enlaces y qué política se aplicó. Los totales de directorios se recalculan coherentemente con la métrica activa.
- **Paquetes macOS:** todo directorio con sufijo `.app` (y, configurable, `.bundle`, `.framework`, `.pkg`) se marca como paquete. Se escanea su interior para conocer el tamaño, pero la vista lo colapsa como una unidad; un ajuste permite explorarlo. Esto evita que una app aparezca como decenas de miles de fragmentos.
- **Montajes y volúmenes:** por defecto no se cruza `st_dev` distinto al de la raíz escaneada. Un punto de montaje se registra como nodo omitido con aviso «otro volumen, no incluido». Un ajuste permite incluirlos, con detección de ciclos por `(dev, ino)` de directorios. Volúmenes de red pueden bloquear llamadas del sistema; se documenta que la cancelación es cooperativa y no puede interrumpir una syscall bloqueada.
- **Archivos que desaparecen o cambian:** cada `OSError` se captura, se cuenta y se asocia al directorio; el escaneo continúa y el resultado se marca como parcial. No se reintenta en bucle.

### 3.5. Eliminación segura

Se usa `QFile.moveToTrash()` (Qt 6.10; API nativa de macOS), sin borrado permanente. Antes de mover:

1. Se valida que la ruta sea absoluta, esté contenida en la raíz escaneada y no sea la raíz.
2. Se vuelve a hacer `lstat` y se comprueba que coinciden dispositivo, inodo y tipo con el nodo escaneado.
3. Se pide confirmación con nombre, ruta y tamaño; para directorios se resume el contenido.
4. Se ejecuta en el hilo de UI (operación corta) con manejo de errores; nunca en el hilo de escaneo.
5. Si funciona, se elimina el nodo del árbol, se recalculan los ancestros, se invalida el layout/filtros y se marca el resultado como «modificado». Si falla, no se muta nada.

No hay eliminación automática ni opción de borrado permanente. Los tests unitarios inyectan una función de papelera falsa; una prueba de integración opcional toca la Papelera real con un archivo temporal y lo restaura/limpia.

### 3.6. Concurrencia

- **Escaneo:** `QThread` + objeto trabajador movido al hilo (no se subclasifica lógica en el widget). El escáner puro recibe un `threading.Event` de cancelación y un callback de progreso; el worker los adapta a señales Qt. Progreso limitado a ~10 Hz. Cancelación comprobada cada 256 entradas y en cada directorio.
- **Filtros/ordenaciones grandes:** `QThreadPool` + `QRunnable` con contador de generación; resultados obsoletos se descartan. Debounce de búsqueda de 200–250 ms.
- **Layout de treemap:** síncrono si es pequeño (< ~5 000 nodos y < ~30 ms estimados); asíncrono con generación para volúmenes grandes o modo subárbol. El hilo de pintado solo dibuja un layout ya calculado.
- **Ciclo de vida:** antes de un nuevo escaneo se cancela y se espera al anterior; nunca se usa `QThread.terminate()`. El árbol de resultados es inmutable una vez emitido; solo se poda en UI tras una papelera confirmada.

---

## 4. Arquitectura y estructura de archivos

```text
macdirstat/
├── plan.md
├── README.md                     # en español, deliverable principal
├── pyproject.toml                # metadatos, deps, pytest
├── requirements.txt              # runtime fijado
├── requirements-dev.txt          # test + empaquetado fijados
├── .gitignore
├── main.py                       # entrypoint: QApplication + MainWindow
├── build_macos.sh                # build reproducible + verificaciones
├── MacDirStat.spec               # configuración PyInstaller
├── app/
│   ├── __init__.py               # __version__, APP_NAME, BUNDLE_ID
│   ├── application.py            # QApplication, tema, arranque
│   ├── main_window.py            # ventana, toolbar, splitter, estado
│   ├── theme.py                  # paleta clara/oscura, colores de categorías
│   ├── models/
│   │   ├── __init__.py
│   │   ├── file_node.py          # FileNode, ScanResult, métricas, enums
│   │   └── categories.py         # extensión → categoría
│   ├── scanner/
│   │   ├── __init__.py
│   │   └── filesystem_scanner.py # recorrido puro con os.scandir
│   ├── workers/
│   │   ├── __init__.py
│   │   └── scan_worker.py        # ScanWorker + ScanController (QThread)
│   ├── treemap/
│   │   ├── __init__.py
│   │   ├── layout_engine.py      # squarified + agregación + hit index
│   │   └── treemap_widget.py     # QWidget/QPainter, ratón, tooltip, zoom
│   ├── views/
│   │   ├── __init__.py
│   │   ├── file_tree_model.py    # QAbstractItemModel
│   │   ├── details_panel.py      # panel lateral
│   │   └── largest_view.py       # top-N archivos/directorios
│   ├── services/
│   │   ├── __init__.py
│   │   ├── filter_engine.py      # búsqueda, filtros, snapshot
│   │   ├── file_actions.py       # abrir, Finder, portapapeles, papelera
│   │   └── settings_manager.py   # QSettings tipado
│   └── resources/
│       ├── icons/app.svg         # fuente del icono
│       └── icons/.gitkeep        # .icns generado en build
├── scripts/
│   └── make_icon.py              # SVG/PNG → .iconset → .icns con Qt
├── tests/
│   ├── conftest.py
│   ├── test_scanner.py
│   ├── test_scan_cancel.py
│   ├── test_categories.py
│   ├── test_treemap_layout.py
│   ├── test_treemap_widget.py
│   ├── test_filters.py
│   ├── test_file_actions.py
│   ├── test_settings.py
│   └── test_main_window.py
├── benchmarks/
│   ├── make_fixture.py           # 100 000 archivos sintéticos
│   └── bench_scan.py             # tiempos + RSS reales
└── docs/
    ├── architecture.md
    ├── size-methodology.md
    ├── testing.md                # resultados reales, no inventados
    └── packaging.md
```

No se crearán módulos vacíos: cada archivo anterior tiene responsabilidad propia. `main_window.py` puede importar widgets auxiliares, pero no contendrá lógica de escaneo, layout ni borrado.

### 4.1. Contratos entre componentes

```python
# app/models/file_node.py
class SizeMetric(StrEnum):
    LOGICAL = "logical"
    ALLOCATED = "allocated"
    ALLOCATED_UNIQUE = "allocated_unique"

class NodeKind(IntEnum):
    FILE = 1
    DIRECTORY = 2
    SYMLINK = 3
    PACKAGE = 4
    SKIPPED_MOUNT = 5
    OTHER = 6

@dataclass(slots=True)
class FileNode:
    name: str
    parent: FileNode | None
    children: list["FileNode"] | None
    kind: NodeKind
    ext: str
    category: Category
    logical_size: int
    allocated_size: int
    mtime_ns: int
    dev: int
    ino: int
    nlink: int
    st_flags: int
    flags: NodeFlags          # hidden, hardlink_duplicate, incomplete, package
    total_files: int          # descendientes, calculado en post-orden
    total_dirs: int
    error_count: int
    # métodos: path(), walk(), appears_in(metric), displayed_size(metric)

@dataclass(frozen=True, slots=True)
class ScanOptions:
    follow_symlinks: bool = False
    cross_device: bool = False
    scan_package_contents: bool = True
    collapse_packages_for_view: bool = True
    keep_max_errors: int = 500
    progress_interval_ms: int = 100

@dataclass(slots=True)
class ScanResult:
    root: FileNode
    root_path: str
    stats: ScanStats
    errors: list[ScanError]
    volume_total: int | None
    volume_free: int | None
    status: ScanStatus        # COMPLETE | PARTIAL | CANCELLED
    elapsed_s: float
```

```python
# app/scanner/filesystem_scanner.py
class FileSystemScanner:
    def scan(self, root_path: str, options: ScanOptions,
             cancel: threading.Event,
             progress: Callable[[ScanProgress], None] | None = None) -> ScanResult: ...
```

```python
# app/treemap/layout_engine.py
class TreemapLayoutEngine:
    def layout(self, request: LayoutRequest) -> LayoutResult: ...
    # LayoutRequest: root node, view mode, rect, metric, min_tile_area,
    #                max_depth, excluded ids, generation
    # LayoutResult: tiles: list[Tile], hit_index, bounds, generation, stats

class HitIndex:
    def hit_test(self, x: float, y: float) -> Tile | None: ...
```

```python
# app/workers/scan_worker.py
class ScanController(QObject):
    progress = Signal(object)      # ScanProgress
    finished = Signal(object)      # ScanResult
    cancelled = Signal(object)     # ScanResult parcial
    failed = Signal(str)
    def start(self, path: str, options: ScanOptions) -> None: ...
    def cancel(self) -> None: ...
    def is_running(self) -> bool: ...
```

```python
# app/services/filter_engine.py
@dataclass(frozen=True, slots=True)
class FilterState:
    query: str = ""
    extensions: frozenset[str] = frozenset()
    categories: frozenset[Category] = frozenset()
    min_bytes: int = 0
    max_bytes: int | None = None
    show_hidden: bool = True
    show_zero: bool = False
    excluded_dirs: tuple[str, ...] = ()
    min_tile_area: float = 6.0

@dataclass(slots=True)
class FilterSnapshot:
    revision: int
    state: FilterState
    visible_total_bytes: int
    visible_files: int
    visible_dirs: int
    visible_ids: set[int]
    aggregate_bytes: dict[int, int]   # id(nodo) → suma filtrada
    largest_files: list[FileNode]
    largest_dirs: list[FileNode]
```

`FilterEngine.build_snapshot(root, state, metric, generation, cancel)` es puro y cancelable; la UI lo ejecuta en `QThreadPool` cuando el volumen lo justifica y, si no, en el hilo de UI con límite de trabajo. Un snapshot viejo se descarta por generación; nunca se etiqueta como actual.

### 4.2. Responsabilidades y dependencias

- `models` y `scanner` no importan Qt. `layout_engine`, `filter_engine` y `categories` tampoco. Esto permite tests rápidos sin `QApplication`.
- `workers`, `views`, `treemap_widget`, `services/file_actions` y `main_window` dependen de Qt.
- `file_actions` recibe `trash_fn=QFile.moveToTrash` inyectable y funciones de reloj/stat inyectables para pruebas.
- `settings_manager` no conoce widgets; expone propiedades tipadas y guarda al cerrar.
- Un `SelectionController` mínimo (en `main_window` o `views`) sincroniza selección entre treemap, árbol, mayores y detalles mediante señales.

---

## 5. Algoritmos

### 5.1. Escaneo

1. Normalizar la raíz con `os.path.abspath`; si es symlink, resolver solo la raíz y registrar el camino original.
2. Crear nodo raíz; `os.statvfs` para total/disponible.
3. Recorrido iterativo con pila explícita de directorios (evita límite de recursión):
   - `os.scandir(dir)` y, por entrada, **una sola** llamada `entry.stat(follow_symlinks=False)`.
   - Derivar tipo de `st_mode`; no llamar además a `is_dir()`/`is_file()`.
   - Archivos: crear nodo hoja; tamaño lógico y asignado.
   - Symlinks: nodo hoja; no seguir; tamaño del enlace.
   - Directorios: crear nodo, decidir si se recorre (paquete, montaje, exclusión, cancelación).
   - Detectar enlaces duros con `(dev, ino)` cuando `nlink > 1`; marcar duplicados.
   - Errores: `ScanError(path, errno, message)`; incrementar contador del directorio; continuar.
   - Progreso: contadores y ruta actual; emitir solo si pasó el intervalo.
   - Cancelación: comprobar el evento; al cancelar, cerrar nodos en curso, calcular agregados parciales y devolver `CANCELLED`.
4. Post-orden iterativo para acumular `total_files`, `total_dirs`, `error_count`, bytes lógicos/asignados/únicos y categorías visibles. Una sola pasada, sin sumar dos veces.
5. Ordenar a demanda (no durante el escaneo) para evitar trabajo innecesario.
6. Devolver `ScanResult`; el worker lo emite y la UI lo adopta.

Reglas de conteo, documentadas en `docs/size-methodology.md`:

- `total_files` cuenta archivos, symlinks y entradas especiales; no cuenta directorios.
- `total_dirs` cuenta subdirectorios; la raíz no se cuenta a sí misma.
- Los paquetes escaneados aportan sus descendientes a los conteos, aunque la vista los colapse.
- Los archivos de 0 bytes cuentan en archivos y en el total lógico (0), pero no generan superficie.

### 5.2. Squarified treemap

Implementación pura, determinista y testeable:

1. Entradas con tamaño efectivo > 0; ordenar descendente por `(size, name, path)` para desempates estables.
2. Escalar áreas al rectángulo útil (sin gaps) menos un gap configurable.
3. Construir filas con el criterio *worst aspect ratio*: añadir el siguiente elemento mientras la peor relación de aspecto de la fila no empeore; colocar la fila a lo largo del lado más corto del rectángulo libre.
4. Rectángulos internos en `float`; el recorte a píxeles se hace al dibujar con rectángulos semiabiertos `[x, x+w)`, sin antialiasing en bordes, para evitar solapamientos por redondeo.
5. Invariantes verificados en tests:
   - todos los rectángulos dentro del área útil;
   - ningún par se solapa (tolerancia 0, semiabierto);
   - suma de áreas == área útil (error ≤ 1e-6 relativo antes del snapping);
   - área relativa de cada ficha == tamaño relativo, dentro de `max(1 px², 1e-4 × área)` antes de redondear;
   - sin dimensiones negativas o cero.
6. **Elementos pequeños:** si el área escalada < `min_tile_area` (px²), se agrupan por directorio en una ficha «Otros (N elementos)». El tamaño de la ficha es la suma exacta de los agrupados; el área total se conserva. La ficha es seleccionable y abre la lista de originales. El ajuste explica: «Los elementos menores que N px² se agrupan; no desaparecen ni cambian los totales».
7. **Cero bytes:** fuera del treemap; contador visible y lista complementaria. Si todos son cero, el mapa muestra un estado vacío explicativo.
8. **Modo subárbol:** layout recursivo por niveles dentro del rectángulo interior de cada directorio, con encabezado de altura fija solo si el rectángulo lo permite. Se detiene y agrega cuando el área interior es insuficiente. La proporcionalidad se garantiza **por nivel**; se documenta que los hijos se escalan al área interior de su directorio.
9. **Caché:** clave `(scan_revision, root_id, mode, metric, filter_revision, min_area, width, height, excluded_set)`. Se reutiliza en `paintEvent`. Un cambio de selección o hover **no** recalcula geometría.
10. **Índice espacial:** malla uniforme (≈ `ceil(sqrt(n))` celdas por eje, con celdas mínimas de 16 px) que mapea celda → índices candidatos; `hit_test` elige el rectángulo más profundo que contiene el punto. Para < 5 000 fichas se usa búsqueda lineal inversa; la malla se activa solo si las mediciones muestran beneficio. Se reconstruye solo con el layout.

### 5.3. Pintado

- Un único `QWidget` con `QPainter`; **cero widgets por archivo**.
- `paintEvent` solo dibuja fichas del layout cacheado, texto si hay espacio, borde de directorio, selección y hover. No calcula geometría ni filtra datos.
- Fondo por categoría usando colores del tema; directorios en tono neutro; duplicados de enlace duro con marca discreta.
- Etiquetas con `QFontMetrics.elidedText` solo cuando caben; nunca tooltips por ficha creados como widgets.
- Tooltip: al cambiar la ficha bajo el cursor, `QToolTip.showText` con texto escapado (`html.escape`) — los nombres de archivo son datos no confiables.
- `update()` solo cuando cambia layout, selección, hover, tema o tamaño. `WA_OpaquePaintEvent` para evitar doble borrado de fondo.
- Resize: debounce 16–33 ms; se solicita un layout nuevo con generación; mientras llega, se muestra el anterior o «Calculando mapa…». Sin animaciones que oculten datos.

### 5.4. Búsqueda y filtros

- Predicado único sobre `FileNode`: nombre (`casefold`, subcadena), extensión, ruta opcional, categoría, tamaño (métrica activa), ocultos, cero, directorios excluidos.
- Un directorio es visible si cumple el predicado o tiene algún descendiente visible.
- `aggregate_bytes` se recalcula en post-orden usando la métrica activa y los descendientes visibles. Los porcentajes y el treemap usan esa suma filtrada.
- Se muestran **siempre** dos referencias: «Total analizado» y «Total filtrado/visible». Las etiquetas de porcentaje indican la base: `% del total analizado` o `% de lo visible`.
- Los filtros no vuelven a recorrer el disco; solo recalculan sobre el árbol en memoria.
- Extensiones y categorías se aplican con lógica AND entre grupos y OR dentro de cada grupo; documentado en la UI.
- Umbral de tamaño mínimo para el mapa (`min_tile_area`) es independiente del filtro de tamaño de archivo; se explican ambos en el panel de filtros.

### 5.5. Mayores consumidores

- Al terminar el escaneo se calcula una vez el top-500 con `heapq.nlargest` por métrica (archivos y directorios), sin ordenar todo.
- La vista permite N = 20/50/100/500 y alternar Archivos/Directorios/Todos, reutilizando el ranking precalculado; al cambiar de filtro se recalcula solo sobre nodos visibles y se cachea por revisión.
- Acciones: localizar en mapa, revelar en Finder, copiar ruta, abrir.

---

## 6. Metodología de tamaños y APFS

### 6.1. Qué mide cada cifra

| Cifra en UI | Origen | Advertencia |
|---|---|---|
| Tamaño lógico | `st_size` | No es espacio ocupado ni liberable |
| Espacio asignado (estimado) | `st_blocks × 512` | Bloques reservados; compresión/clones lo distorsionan |
| Asignado único (estimado) | Igual, deduplicando `(dev, ino)` | Solo enlaces duros; no detecta clones APFS |
| Total / disponible del volumen | `os.statvfs` (`.f_blocks`, `.f_bavail`, `.f_frsize`) | macOS/APFS puede reportar distinto de lo liberable |

### 6.2. Casos macOS documentados

- **Compresión APFS:** `st_size` puede superar ampliamente `st_blocks*512`; se etiqueta «posiblemente comprimido» si `st_flags` incluye `UF_COMPRESSED`, sin prometer detección completa.
- **Archivos dispersos:** asignado menor que lógico; correcto mostrar ambos.
- **Clones APFS:** comparten bloques físicos; no hay API pública fiable para contabilizar el ahorro por clon. Se declara no soportado y no se resta ninguna estimación.
- **Snapshots/purgables:** no se pueden atribuir a archivos concretos; se muestran como limitación del volumen.
- **Enlaces duros:** política explícita en UI y docs; la deduplicación cambia los totales de directorio (el primer camino recibe el bloque; los demás aparecen como duplicados).
- **Paquetes:** se escanean y se muestran colapsados por defecto; los totales incluyen su interior.
- **Directorios protegidos/TCC:** sin Acceso Total al Disco, carpetas como `~/Library/...`, `~/Desktop`, `~/Documents`, `~/Downloads`, `/System/Volumes/Data/...` pueden devolver `EACCES/EPERM`. La app no solicita permisos automáticamente, no usa `sudo` y marca el resultado como parcial. Se documenta cómo conceder Acceso Total al Disco en Ajustes del Sistema y que el selector nativo concede acceso puntual a la carpeta elegida, no a todo el disco.
- **Volúmenes externos/red:** se pueden seleccionar; no se cruzan montajes por defecto. Un volumen de red puede tardar; la cancelación es cooperativa.
- **Cambios durante el escaneo:** archivos que desaparecen → error registrado; archivos que crecen → se usa el `stat` del momento; no se garantiza consistencia transaccional.

---

## 7. Interfaz de usuario

### 7.1. Distribución

```text
┌──────────────────────────────────────────────────────────────────────┐
│ Toolbar: [Analizar] [Actualizar] [Cancelar]   Búsqueda   [Filtros]   │
│ Ruta: /Users/.../Downloads        [Mapa] [Árbol] [Mayores]           │
│ Breadcrumb: Macintosh HD › Users › sergiovalle › Downloads           │
├──────────────────────────────────────────────┬───────────────────────┤
│                                              │ Detalles              │
│   Treemap (QPainter) / QTreeView / tabla     │ Nombre                │
│                                              │ Ruta                  │
│   Leyenda de categorías                      │ Lógico / Asignado     │
│                                              │ % total / % visible   │
│                                              │ Fechas, categoría     │
│                                              │ [Abrir] [Finder] ...  │
├──────────────────────────────────────────────┴───────────────────────┤
│ Progreso (indeterminado)  Estado  N archivos · X GB · 12 errores     │
└──────────────────────────────────────────────────────────────────────┘
```

- `QSplitter` principal: vista central + panel de detalles (mínimo 280 px, colapsable).
- Barra superior con selector de ubicación (botón + ruta), acciones y búsqueda.
- Tres vistas en `QStackedWidget`, seleccionables con un control segmentado; comparten selección y snapshot de filtros.
- Leyenda bajo el treemap: una muestra por categoría + directorio + «Otros/agrupados»; clic en categoría aplica/quita filtro.
- Barra de estado: estado del escaneo, tiempo, archivos, directorios, tamaño total, errores y aviso de resultado parcial.
- Progreso indeterminado (no se conoce el total antes de recorrer) con contadores en vivo; cancelar siempre accesible.
- Modo claro/oscuro según el sistema (`QStyleHints.colorScheme()`), con paleta de categorías propia y contraste comprobado; sin animaciones.
- Tema: colores sobrios, tipografía del sistema, espaciado consistente; cero ventanas emergentes innecesarias. Errores en banner/status y un diálogo de detalle solo si el usuario lo abre.

### 7.2. Interacciones

| Acción | Gesto / atajo |
|---|---|
| Analizar carpeta | `Cmd+O` |
| Repetir escaneo | `Cmd+R` |
| Cancelar | `Esc` o `Cmd+.` |
| Buscar | `Cmd+F` |
| Subir un nivel | `Cmd+Up` |
| Atrás / adelante | `Cmd+[` / `Cmd+]` |
| Abrir archivo | doble clic o `Cmd+Enter` |
| Mostrar en Finder | `Cmd+Shift+R` |
| Copiar ruta | `Cmd+Shift+C` |
| Enviar a Papelera | `Cmd+Delete` con confirmación |
| Cambiar vista | `Cmd+1/2/3` |
| Zoom de directorio | doble clic en ficha de directorio o `Enter` |
| Volver a vista general | botón/atajo dedicado en breadcrumb |

- Un clic selecciona; doble clic en archivo abre; doble clic en directorio hace zoom.
- Hover resalta y muestra tooltip con nombre, tamaño legible, categoría, ruta resumida y, para directorios, conteo.
- La selección desde árbol/mayores navega al padre en el mapa, selecciona y, si el elemento está agrupado o filtrado, lo explica con una acción para limpiar filtros.
- Teclado: foco visible, etiquetas accesibles (`setAccessibleName`), navegación con Tab, selección con flechas en árbol/tabla; `Enter` abre; `Supr` no borra directamente.
- Ventana pequeña: el panel de detalles se puede colapsar; toolbar y breadcrumb se ajustan; tamaño mínimo razonable (p. ej. 900×600) y persistencia de geometría/splitter.
- Drag & drop de carpeta sobre la ventana: opcional en Fase 2, con validación.

### 7.3. Categorías y colores

Categorías iniciales: Documentos, Imágenes, Vídeos, Audio, Comprimidos, Aplicaciones/paquetes, Bibliotecas/Código, Sistema, Otros. La tabla extensión→categoría vive en `categories.py` (sin Qt), con tests de casos `.jpg`, `.jpeg`, `.HEIC`, sin extensión, mayúsculas y desconocidas. Colores distinguibles en claro/oscuro y para daltonismo razonable; la leyenda es la fuente de verdad, no solo el color. Directorios: tono neutro; agrupados: gris rayado; enlaces duros duplicados: marca discreta.

---

## 8. Pruebas automatizadas

### 8.1. Configuración

- `pytest` + `pytest-qt`; `QT_QPA_PLATFORM=offscreen` para CI/local sin pantalla, y una pasada manual con pantalla real.
- `pytest -q` ejecuta todo salvo `slow`; `pytest -q -m slow` ejecuta la carga de 100 000 archivos.
- Tests puros del escáner/layout/filtros no crean `QApplication`.
- Fixtures temporales con `tmp_path`; permisos restaurados en `finally`; no se toca el disco del usuario.
- Cualquier prueba que requiera macOS real (papelera nativa, Finder) se marca `macos_integration` y se ejecuta manualmente.

### 8.2. Matriz obligatoria (20 casos del enunciado)

| # | Caso | Test previsto |
|---|---|---|
| 1 | Directorio vacío | `test_scanner.py::test_empty_directory` |
| 2 | Un único archivo | `test_scanner.py::test_single_file` |
| 3 | Archivos de tamaño cero | `test_scanner.py::test_zero_byte_files` |
| 4 | Archivos pequeños y grandes | `test_scanner.py::test_size_accounting` |
| 5 | Directorios anidados | `test_scanner.py::test_nested_directories` |
| 6 | Nombres Unicode | `test_scanner.py::test_unicode_names` |
| 7 | Extensiones diferentes | `test_categories.py`, `test_scanner.py` |
| 8 | Enlaces simbólicos | `test_scanner.py::test_symlink_not_followed` |
| 9 | Ciclos potenciales | `test_scanner.py::test_symlink_cycle_does_not_recurse` |
| 10 | Archivos inaccesibles | `test_scanner.py::test_permission_denied_is_recorded` (skip si root) |
| 11 | Archivos que desaparecen | `test_scanner.py::test_file_disappears_mid_scan` (monkeypatch de `scandir`) |
| 12 | Cancelación | `test_scan_cancel.py::test_cancel_returns_partial_result` |
| 13 | Tamaños acumulados | `test_scanner.py::test_directory_aggregates` |
| 14 | Aplicar/retirar filtros | `test_filters.py::test_apply_and_clear_filters` |
| 15 | Ordenación por tamaño | `test_filters.py::test_sort_by_size` y modelo |
| 16 | Selección/identificación de rectángulos | `test_treemap_layout.py::test_hit_test`, widget con clic |
| 17 | Cambio de directorio en el mapa | `test_treemap_widget.py::test_zoom_and_back` |
| 18 | Enlaces duros | `test_scanner.py::test_hardlink_policies` |
| 19 | Redimensionado | `test_treemap_widget.py::test_resize_relayout` |
| 20 | Apertura/papelera seguras | `test_file_actions.py` (fake trash) + integración opcional |

### 8.3. Casos sintéticos del treemap

- Todos los elementos del mismo tamaño.
- Un archivo que domina casi toda la superficie.
- Cientos de tamaños muy dispares.
- Muchos elementos diminutos → agregación; suma de la ficha «Otros» == suma original.
- Todos los archivos de tamaño cero → sin rectángulos, estado vacío y contador.
- Directorios con cantidades de descendientes muy diferentes (modo subárbol).
- Umbral mínimo visible: no se pierde ni se duplica superficie.
- Invariantes: sin dimensiones inválidas, sin coordenadas fuera del área, sin solapamientos, proporcionalidad dentro de tolerancia.

### 8.4. Pruebas de UI

- `MainWindow` arranca y muestra estado vacío.
- Selección sincronizada treemap ↔ árbol ↔ detalles.
- Tooltip escapado con nombres que contienen `<script>`.
- Zoom a directorio, breadcrumb y atrás.
- Cambio de métrica actualiza porcentajes/etiquetas.
- Diálogo de papelera cancelado no muta el árbol.
- Resultado parcial muestra banner de errores.
- Tema claro/oscuro no rompe colores de categorías (verificación de contraste básica).

### 8.5. Carga y rendimiento

- `benchmarks/make_fixture.py --files 100000`: crea 100 carpetas × 1 000 archivos (vacío o con bytes controlados) en un directorio temporal; registra tiempo de creación y limpia.
- `benchmarks/bench_scan.py`: mide escaneo (s), layout en modo subárbol y nivel actual (s), número de fichas, RSS máximo (`resource.getrusage`), y guarda una tabla Markdown. **No forma parte de `pytest` por defecto.**
- Primero se mide; solo se optimiza si se incumplen los objetivos. No se añaden hilos adicionales sin evidencia.

Objetivos (no resultados):

| Escenario | Objetivo |
|---|---|
| UI durante escaneo | evento de UI < 100 ms; progreso visible cada ≤ 200 ms |
| 100 000 entradas escaneadas | completar sin bloquear la UI; cancelación perceptible |
| Layout 10 000 fichas | p95 ≤ 300 ms, fuera del hilo de UI si es necesario |
| Repintado 5 000 fichas | p95 ≤ 16 ms |
| Memoria 100 000 nodos | ≤ 300 MB adicionales (medido) |
| Fichas dibujadas | se agrupan si exceden el umbral configurado; sin pérdida de datos |

Los números reales se pegarán en `docs/testing.md` y en el README solo después de ejecutarlos.

---

## 9. Fases de implementación

Cada fase se considera cerrada solo con su app ejecutable, sus pruebas en verde y una verificación manual registrada.

### Fase 0 — Bootstrap (base ejecutable)

Tareas:

- [x] `git init`, `.gitignore` (`__pycache__/`, `.venv/`, `build/`, `dist/`, `*.spec` solo si se decide; `benchmarks/tmp/`).
- [x] `pyproject.toml` con metadatos, dependencias y configuración de pytest; `requirements.txt` y `requirements-dev.txt` fijados.
- [x] Crear `.venv` con Python 3.13.3, actualizar pip e instalar dependencias.
- [x] Verificar imports: `PySide6`, `pytest`, `pytestqt`, `PyInstaller`.
- [x] Verificar `QFile.moveToTrash` / `supportsMoveToTrash` en la versión instalada.
- [x] `main.py` + `application.py` con ventana vacía; smoke test offscreen y con pantalla real.
- [x] Estructura de paquetes y conftest con `QT_QPA_PLATFORM=offscreen`.

Criterio de salida: ventana Qt abre y cierra; `pytest -q` arranca (0 tests o smoke); `python -c "from PySide6.QtCore import QFile; print(QFile.supportsMoveToTrash())"` responde.

### Fase 1 — MVP funcional (Fase 1 del enunciado)

Tareas:

- [x] `FileNode`, `ScanOptions`, `ScanResult`, `ScanStats`, categorías, métricas.
- [x] `FileSystemScanner` con `os.scandir`, post-orden, errores, symlinks no seguidos, cancelación y callback de progreso.
- [x] `ScanWorker`/`ScanController` con `QThread`, señales, progreso limitado, cancelación y limpieza.
- [x] `MainWindow`: toolbar Analizar/Actualizar/Cancelar, selección nativa de carpeta, estado, progreso, resumen.
- [x] `TreemapLayoutEngine` squarified + `TreemapWidget` con hijos directos, selección, hover/tooltip, resize, caché y hit-test lineal.
- [x] Panel de detalles con archivos y directorios; acciones Abrir, Finder, Copiar ruta.
- [x] Pruebas de escáner (casos 1–9, 13, 18 básico), layout e invariantes, widget mínimo.
- [x] Ejecución real: fixture con archivos conocidos, comprobación manual de totales y selección; captura de pantalla real.
- [x] README inicial en español con instalación, ejecución y estado.

Criterio de salida: elegir carpeta → escanear → mapa proporcional → clic selecciona → detalles correctos → abrir/revelar → cancelar → analizar otra carpeta sin reiniciar. Sin bloqueo perceptible.

### Fase 2 — Exploración avanzada

Tareas:

- [x] Historial de navegación, zoom, breadcrumb, subir/atrás/vista general.
- [x] Modo subárbol del treemap con agregación por área mínima; conmutador Nivel/Subárbol.
- [x] `FileTreeModel` + `QTreeView`: jerarquía, columnas, orden, expansión perezosa, sincronización de selección.
- [x] Vista «Mayores» con top-N configurable, archivos/directorios/todos, acciones.
- [x] `FilterEngine` + `FilterSnapshot`: búsqueda, extensiones, categorías, tamaño, ocultos, cero, excluidos, umbral de mapa; ejecución en hilo para volúmenes grandes; debounce.
- [x] Totales original vs filtrado visibles en toda la UI; porcentajes etiquetados.
- [x] Leyenda interactiva y categorías; lista complementaria de archivos de 0 bytes.
- [x] Tests de filtros, ordenación, árbol, zoom, snapshot, mayores.
- [x] Verificación manual con carpeta real y carpeta sintética.

Criterio de salida: navegar por directorios con breadcrumb, alternar mapa/árbol/mayores, buscar y filtrar sin reescanear, localizar resultados en el mapa, y que los porcentajes distingan total original y filtrado.

### Fase 3 — Robustez, precisión y rendimiento

Tareas:

- [x] Métricas lógica/asignada/única, deduplicación de enlaces duros y explicación en UI.
- [x] Paquetes colapsados/explorables; política de montajes; detección de compresión básica vía `st_flags`.
- [x] Manejo de errores: banner de resultado parcial, resumen de accesos denegados, límite de errores guardados, paths escapados.
- [x] Agregación de fichas pequeñas y umbral configurable; lista de agrupados.
- [x] Índice espacial si las mediciones lo justifican; caché de layout completa; layout asíncrono por generación.
- [x] `FileActions` con validación de inodo/ruta, `QFile.moveToTrash`, confirmación, poda y recálculo tras éxito.
- [x] `SettingsManager` con todas las preferencias; restauración segura de geometría.
- [x] Tema claro/oscuro, accesibilidad, atajos completos.
- [x] Benchmark de 100 000 archivos y optimizaciones basadas en datos; registrar resultados.
- [x] Suite completa (20 casos + sintéticos + UI + carga) y corrección de fallos.
- [x] Documentar permisos TCC, limitaciones APFS y privacidad.

Criterio de salida: resultados parciales claramente marcados, enlaces duros y paquetes coherentes, papelera segura, preferencias persistentes, 100 000 elementos con UI fluida y métricas reales registradas.

### Fase 4 — Distribución

Tareas:

- [x] Icono propio: `app.svg` → `scripts/make_icon.py` (Qt) → `.iconset` → `.icns`.
- [x] `MacDirStat.spec`: `windowed`, bundle ID, versión, `LSMinimumSystemVersion 13.0`, `NSHighResolutionCapable`, exclusión de módulos Qt no usados.
- [x] `build_macos.sh`: comprobar macOS/herramientas, crear/validar venv, tests rápidos, icono, PyInstaller `--clean --noconfirm`, verificación de arquitectura y firma ad-hoc, salida `dist/MacDirStat.app`.
- [x] Verificar la app empaquetada: lanzar desde Finder y desde terminal, escanear, abrir, papelera (con archivo temporal), cerrar. Verificado: arranque desde terminal y tipo Finder (`open`), escaneo real con captura y cierre; «Abrir» y Papelera con ratón desde la `.app` quedan como verificación manual (el código está cubierto por `test_macos_integration.py`).
- [x] Documentar build arm64, Intel y universal2; `lipo -archs`; no mezclar arquitecturas.
- [x] Documentar firma Developer ID y notarización (`codesign`, `notarytool`, `stapler`, `spctl`); dejar claro que **no se ha firmado ni notarizado** sin credenciales.
- [x] README final en español, `docs/architecture.md`, `size-methodology.md`, `testing.md` con resultados reales y `packaging.md`.
- [x] Revisión final de entregables y criterios de aceptación.

Criterio de salida: `.app` generada y ejecutada en este Mac (si el entorno lo permite), documentación completa, pruebas y benchmarks registrados, limitaciones explícitas. Si algún paso de firma/notarización no se ejecuta, se indica como pendiente con instrucciones exactas.

---

## 10. Empaquetado macOS

### 10.1. Dependencias y build

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
python main.py
pytest -q
./build_macos.sh
open dist/MacDirStat.app
```

`build_macos.sh` será idempotente y fallará con mensaje claro si falta una herramienta o si los tests fallan. Opciones previstas: `--skip-tests`, `--universal2`, `--clean`.

### 10.2. Arquitecturas

- **Apple Silicon (por defecto):** Python 3.13.3 universal2 ejecutándose arm64; PyInstaller genera un `.app` arm64. Verificar con `file`/`lipo`.
- **Intel:** ejecutar el build en un Mac Intel o con un Python x86_64 bajo Rosetta 2; no mezclar binarios. Wheels PySide6 universal2 lo permiten, pero se debe verificar en hardware/entorno x86_64.
- **Universal2:** el Python actual es universal2 y PySide6 publica wheel universal2; usar `--target-arch universal2` y verificar con `lipo -archs` que todos los binarios incluyen `x86_64 arm64`. Si algún artefacto no es universal2, se entregan dos builds separados y se documenta. No se afirmará universalidad hasta verificarla.

### 10.3. Firma y notarización

- Sin sandbox. Hardened Runtime con `--options runtime`.
- Firma con certificado «Developer ID Application»: `codesign --force --deep --options runtime --timestamp --sign "Developer ID Application: …" dist/MacDirStat.app`.
- Notarización: `ditto -c -k --keepParent dist/MacDirStat.app dist/MacDirStat.zip`, `xcrun notarytool submit … --wait`, `xcrun stapler staple dist/MacDirStat.app`, verificación `spctl -a -vv`.
- Sin credenciales en este entorno, **no** se firmará ni notarizará. Se documentará el procedimiento y el estado real. La build local usará firma ad-hoc de PyInstaller; Gatekeeper puede requerir «Abrir» con clic derecho.
- No se incluirán entitlements que eludan TCC ni sandbox.

### 10.4. Permisos macOS documentados

- La app no solicita privilegios de administrador ni ejecuta `sudo`.
- El selector nativo permite elegir la carpeta; macOS puede aplicar TCC a Desktop/Documents/Downloads y otras ubicaciones.
- Para analizar zonas protegidas se requiere conceder Acceso Total al Disco manualmente en Ajustes del Sistema; sin ello, el resultado será parcial y así se mostrará.
- Empaquetar como `.app` **no** concede acceso total; se documenta explícitamente.
- Sin telemetría; logs locales solo si el usuario activa diagnóstico, con rutas minimizadas.

---

## 11. Documentación (entregables)

`README.md` en español, con:

1. Qué es y captura real (cuando exista).
2. Requisitos: macOS 13+, Python 3.12–3.14, Apple Silicon/Intel.
3. Creación/activación de `.venv`, instalación.
4. Ejecución en desarrollo.
5. Uso: analizar, navegar, filtrar, buscar, mayores, detalles, papelera.
6. Atajos de teclado.
7. Arquitectura y flujo de datos.
8. Algoritmo squarified y agregación.
9. Métricas de tamaño y limitaciones APFS (resumen; detalle en docs).
10. Permisos/TCC y privacidad.
11. Pruebas: comandos y **tabla de resultados reales**.
12. Rendimiento: entorno, fixture, tiempos, memoria.
13. Empaquetado, arquitecturas, firma/notarización y diagnóstico de errores frecuentes.
14. Limitaciones conocidas y estado de cada fase.

Documentos de apoyo: `docs/architecture.md`, `docs/size-methodology.md`, `docs/testing.md`, `docs/packaging.md`. Sin resultados inventados: las tablas se completan tras cada ejecución.

---

## 12. Riesgos y mitigaciones

| Riesgo | Impacto | Mitigación |
|---|---|---|
| PySide6 6.10.3 en macOS 26.6 presenta regresiones | App no arranca o falla el pintado | Smoke test en Fase 0; fallback documentado a 6.12 (sube mínimo a macOS 14) |
| Wheel/PyInstaller no universal2 en algún artefacto | Build universal2 inválido | Verificar con `lipo`; entregar builds por arquitectura y documentar |
| TCC bloquea carpetas habituales | Escaneos parciales percibidos como fallo | Banner explícito, conteo de errores, guía de Acceso Total al Disco; nunca ocultar |
| 100 000 archivos agotan memoria o bloquean UI | Mala experiencia | Medir primero; post-orden iterativo, `__slots__`, agregación, layout async, límites de concurrencia |
| Fichas minúsculas ilegibles | Pérdida de confianza | Agregación «Otros (N)» con suma exacta y acceso a la lista; umbral explicado |
| Enlaces duros/clones distorsionan totales | Cifras engañosas | Métricas separadas, política explícita, aviso de clones/snapshots no cuantificables |
| Papelera mueve el elemento equivocado | Pérdida de datos | Revalidación de inodo/tipo, contención de ruta, confirmación, sin borrado permanente |
| Montajes/red cuelgan el escaneo | Cancelación no responde | No cruzar montajes por defecto; documentar límite de syscalls; evitar escaneo de red por defecto |
| Tests de permisos pasan por ejecutar como root | Falso verde | `skipif(os.geteuid() == 0)`; restaurar permisos en `finally` |
| Prueba de papelera contamina `~/.Trash` | Efecto secundario | Inyección fake por defecto; integración marcada y con limpieza/restauración |
| Firma/notarización sin certificados | Distribución limitada | Documentar como pendiente; no afirmar firma; build ad-hoc verificable localmente |

---

## 13. Verificación por fase (comandos)

```bash
# Entorno
source .venv/bin/activate
python --version
python -c "import PySide6; print(PySide6.__version__)"

# App en desarrollo
python main.py

# Tests rápidos (sin pantalla)
QT_QPA_PLATFORM=offscreen pytest -q

# Tests completos, incluida carga
pytest -q
pytest -q -m slow

# Benchmark manual
python benchmarks/make_fixture.py --files 100000
python benchmarks/bench_scan.py --fixture <ruta>

# Empaquetado
./build_macos.sh
open dist/MacDirStat.app
file dist/MacDirStat.app/Contents/MacOS/MacDirStat
lipo -archs dist/MacDirStat.app/Contents/MacOS/MacDirStat
codesign -dv --verbose=4 dist/MacDirStat.app
```

En cada cierre de fase se ejecutará además una comprobación manual con pantalla real: escanear una carpeta conocida, verificar totales contra `du`/Finder (entendiendo sus diferencias), seleccionar, navegar, cancelar y repetir.

---

## 14. Entregables y estado

| # | Entregable | Fase | Estado |
|---|---|---|---|
| 1 | Código fuente completo | 1–3 | **Hecho** |
| 2 | Proyecto organizado y ejecutable | 1 | **Hecho** |
| 3 | `requirements` + `pyproject.toml` | 0 | **Hecho** (versiones fijadas) |
| 4 | Pruebas automatizadas | 1–3 | **Hecho** (140 pruebas + 3 de integración macOS opt-in) |
| 5 | README en español | 1–4 | **Hecho** (14 secciones, capturas reales) |
| 6 | Instrucciones de `.venv` | 0/4 | **Hecho** (README §2, `build_macos.sh` crea el venv si falta) |
| 7 | Instrucciones de ejecución | 1/4 | **Hecho** (README §3–4, atajos) |
| 8 | Compilación y empaquetado macOS | 4 | **Hecho** (`build_macos.sh` + `MacDirStat.spec` + `dist/MacDirStat.app` arm64 ad-hoc) |
| 9 | Descripción de arquitectura | 4 | **Hecho** (`docs/architecture.md`) |
| 10 | Algoritmos y métricas | 3/4 | **Hecho** (`docs/size-methodology.md`, README §5–6) |
| 11 | Limitaciones conocidas | 4 | **Hecho** (README §10, `docs/packaging.md`) |
| 12 | Pruebas ejecutadas y resultados reales | 3/4 | **Hecho** (`docs/testing.md`, §15) |
| 13 | `.app` generada | 4 | **Hecho** (local, firma ad-hoc). Pendiente: build Intel/universal2 no verificado y firma Developer ID/notarización sin credenciales, con procedimiento exacto en `docs/packaging.md` |
| — | Este plan | 0 | **Hecho** |

**Estado actual:** aplicación completa y verificada. Suite rápida en verde
(140 passed, 3 deselected; integración de Papelera 3 passed), benchmark real de
100 000 archivos registrado (§15), `.app` arm64 construida y ejecutada desde
terminal y tipo Finder, documentación completa en README + `docs/`. No se ha
firmado con Developer ID ni notarizado (sin credenciales) y no se ha verificado
un build Intel ni universal2.

**Siguiente acción concreta:** verificación manual con pantalla real de gestos
(doble clic, hover, splitter, Abrir y Papelera desde la `.app` empaquetada);
después, con credenciales de Apple, firmar y notarizar siguiendo
`docs/packaging.md` §6 — o, para Intel/universal2, ejecutar
`./build_macos.sh --universal2` en un Python universal2 verificado con `lipo`.

---

## 15. Registro de resultados reales

Ejecuciones reales en el Mac de desarrollo (macOS 26.6.2 arm64, 10 CPUs,
Python 3.13.3, PySide6 6.10.3, pytest 9.1.1, pytest-qt 4.5.0, PyInstaller 6.22.3).

| Fecha | Entorno | Fixture | Escaneo | Layout | RSS | Resultado |
|---|---|---|---|---|---|---|
| 2026-10-17 | macOS 26.6.2 arm64, 10 CPUs | `benchmarks/tmp/fixture-100000` (100 000 archivos, 100 carpetas, 163.7 MB lógicos, semilla 20261017) | 1.264 s (0.55–0.69 s en ejecuciones previas), 0 errores, progreso cada ≤ 0.102 s, cancelación en 0.017 s | subárbol completo 0.195 s (60 000 fichas, truncado); ~10 000 fichas (9 110) 0.075 s; nivel actual ≈ 0 s | +49.5 MB tras escanear; pico total 200.6 MB | Objetivos cumplidos; repintado p95 11.5 ms con 4 218 fichas (n=60); métrica por defecto: espacio asignado |

Pruebas:

- `QT_QPA_PLATFORM=offscreen pytest -q` → **140 passed, 3 deselected** en 3.3 s.
- `pytest -m macos_integration -v` → **3 passed** (Papelera real de macOS;
  limpieza de `~/.Trash` verificada).
- Casos 1–20 del enunciado: todos cubiertos y en verde; mapeo caso → prueba en
  `docs/testing.md`.
- Pruebas de carga con marcador `slow`: ninguna (la carga se mide con
  `benchmarks/`, fuera de pytest).
- Requiere máquina real (no trasladable): integración de Papelera
  (`macos_integration`, ejecutada aquí) y permiso TCC de Acceso Total al Disco
  para carpetas protegidas. No verificado: build Intel y universal2, firma
  Developer ID y notarización.
