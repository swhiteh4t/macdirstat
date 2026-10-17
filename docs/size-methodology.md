# Metodología de tamaños y APFS

Documento de apoyo del [README](../README.md). Explica qué mide cada cifra de
MacDirStat, por qué ninguna es «el espacio que recuperarás» y cómo se tratan
los casos específicos de macOS.

## 1. Qué mide cada cifra

| Cifra en la UI | Origen | Qué es | Advertencia |
|---|---|---|---|
| **Tamaño lógico** | `st_size` | Bytes declarados por el archivo | No es espacio ocupado ni liberable |
| **Espacio asignado (est.)** | `st_blocks × 512` | Bloques reservados en disco | Compresión y clones lo distorsionan |
| **Asignado único (est.)** | Igual, deduplicando `(dev, ino)` | Asignado contando enlaces duros una vez | Solo enlaces duros; no detecta clones APFS |
| **Total / disponible del volumen** | `os.statvfs` (`f_blocks`, `f_bavail`, `f_frsize`) | Contexto del volumen analizado | macOS/APFS puede reportar distinto de lo liberable |

La métrica de visualización por defecto es el **espacio asignado** (`st_blocks × 512`),
el espacio real que los datos ocupan en disco; se cambia desde el
menú *Ver → Métrica* (⌘⌥1/2/3) y afecta al treemap, al árbol, a Mayores y a
los porcentajes. Los totales del directorio se recalculan de forma coherente
con la métrica activa (lo que cambia es cuánto aporta cada nodo al total).

Porcentajes: la app muestra siempre **total original** (lo escaneado) y
**total visible** (tras filtros) por separado. Un «42 %» sin etiqueta sería
ambiguo y no se usa.

## 2. Casos macOS documentados

- **Compresión APFS:** `st_size` puede ser muy superior a `st_blocks × 512`.
  La app etiqueta «posiblemente comprimido» cuando `st_flags` incluye
  `UF_COMPRESSED`; no promete detección completa.
- **Archivos dispersos (sparse):** asignado menor que lógico; ambos se
  muestran y son correctos.
- **Clones APFS:** comparten bloques físicos sin API pública para atribuir el
  ahorro. **No soportado**: no se resta ninguna estimación y así se declara;
  dos clones pueden contarse como dos archivos «asignados» aunque el volumen
  solo tenga una copia física.
- **Snapshots locales y archivos purgables:** no se pueden atribuir a archivos
  concretos; afectan a `statvfs` y se documentan como limitación del volumen.
- **Enlaces duros:** detectados por `(st_dev, st_ino)` con `st_nlink > 1`. Con
  la métrica lógica/asignada cada entrada cuenta; con «asignado único» el
  inodo cuenta una vez (primer camino encontrado) y los demás se marcan como
  duplicados en los detalles. Los totales de directorio cambian según la
  métrica, como es debido.
- **Enlaces simbólicos:** no se siguen nunca; se cuenta el tamaño del propio
  enlace. Un enlace a un directorio no provoca recursión.
- **Paquetes (`.app`, `.bundle`, `.framework`, `.pkg`):** se escanean para
  conocer su tamaño, pero la vista los colapsa como una unidad para que una
  app no aparezca como miles de fragmentos.
- **Montajes y otros volúmenes:** no se cruzan por defecto; el punto de montaje
  queda como nodo «otro volumen, no incluido». Hay una opción para incluirlos,
  con detección de ciclos por `(dev, ino)`. Los volúmenes de red pueden
  bloquear syscalls: la cancelación es cooperativa y no interrumpe una llamada
  bloqueada del sistema.
- **Directorios protegidos por TCC:** sin Acceso Total al Disco, carpetas como
  `~/Desktop`, `~/Documents`, `~/Downloads`, `~/Library/...` o partes de
  `/System/Volumes/Data` pueden devolver `EACCES`/`EPERM`. La app no pide
  permisos automáticamente ni usa `sudo`: registra el error, marca el
  resultado como **parcial** y muestra un banner con el número de errores.
  El selector nativo concede acceso a la carpeta elegida en esa sesión, no a
  todo el disco. Cómo conceder Acceso Total al Disco: `packaging.md` §5.
- **Cambios durante el escaneo:** si un archivo desaparece se registra un
  error y el escaneo continúa; si crece, se usa el `stat` del momento. No hay
  consistencia transaccional y el resultado se marca como parcial si hubo
  errores.

## 3. Cómo comparar con Finder y `du`

- Finder muestra el «tamaño en disco» (≈ asignado) redondeado; `du -sh` suma
  bloques asignados sin deduplicar enlaces duros. MacDirStat muestra varias
  métricas precisamente para que la comparación sea explicable.
- `du` de un volumen con snapshot Time Machine suele dar más que lo visible en
  Finder; es esperable y no un error de la app.
- Los errores de permisos hacen que `du -sh` (ejecutado sin `sudo`) también
  devuelva menos que el contenido real; compara siempre los dos conteos de
  errores, no solo los totales.

## 4. Reglas que la app nunca rompe

1. Nunca se afirma que una cifra sea el espacio liberable exacto.
2. Nunca se ocultan datos en silencio: todo lo agrupado por tamaño tiene su
   ficha «Otros (N)» con la suma exacta y su lista de elementos.
3. Los totales originales y filtrados se muestran por separado.
4. Las operaciones destructivas requieren confirmación explícita y solo usan
   la Papelera de macOS.
