# Evidencia de la retroalimentación 3: CPU y RAM, energía y latencia de red, y tiempos de recuperación

Fecha: 2 de noviembre de 2026. Respuesta a la retroalimentación del profesor guía para el informe 3: (1) CPU y RAM de cada entorno, (2) gráficos comparativos con energía y latencia de red, (3) tiempos de recuperación de cada distribución. Lo cubro con análisis de lo ya medido (PT-A) y con mediciones nuevas que preparé el 2 de noviembre y ejecuté ese mismo día en ambas distribuciones (PT-B, PT-C, PT-D; resultados en la sección 9). No modifiqué los datos existentes de `data/` ni toqué `k6/medicion/plan_campana.py` (`plan-campana-v1` sigue sin fijarse).

Convención de este documento: «Hecho» es lo que existe en el repositorio; «Medido» es un valor calculado con datos del repositorio mediante `analysis/recursos_latencia.py`; «Supuesto» es lo no verificado; «Interpretación» es una lectura de lo medido, sin prueba. Los pilotos de la sesión definitiva (28-oct) son `--tipo piloto` con `valida_para_campana = false`; todas las figuras son preliminares, de una sesión.

## 1. Cambios por archivo

| Archivo | Cambio |
|---|---|
| `analysis/recursos_latencia.py` (nuevo) | PT-A: CSV por corrida (potencia, CPU y RAM del host y de cada VM, RSS de QEMU, latencia, fallidas y descartadas) y CSV de las corridas con fallo; histograma de latencia por corrida (`hist` en `cache_latencia.json`); resumen por condición para el control de PT-B y PT-C; autotest (`--autotest`). No genera figuras. |
| `analysis/figuras.py` (nuevo) | Lee esos CSV y la caché y genera los cinco gráficos en PDF (energía frente a latencia, CPU y RAM, espectro de percentiles de latencia, memoria del host, línea de tiempo de la recuperación); autotest (`--autotest`). |
| `analysis/requirements.txt` (nuevo) | `matplotlib==3.11.2` (versión con la que generé las figuras; no estaba instalada en el sistema, la usé en un entorno virtual fuera del repositorio). |
| `analysis/salidas/` (nuevo) | CSV, `cache_latencia.json` y PDF de cada salida (28-oct definitiva, 27-oct recuperación definitiva, 2-nov; la recuperación de la configuración inicial solo en CSV). |
| `k6/lib/recursos.py` (nuevo) | PT-B y PT-C: RTT con `ping`, memoria y swap del host, RSS de QEMU, lectura de cgroups del plano de control, red virtual de libvirt; autotest. |
| `k6/medicion/orquestador.py` | Opciones `--rtt`, `--rtt-muestras` y `--cgroup-cp` (desactivadas por defecto); campos `rtt`, `red_virtual`, `recursos_host` y `cgroup_cp` en los metadatos; `fallo.analisis.tiempos_s` en las corridas con fallo. |
| `k6/lib/fallo.py` | `tiempos()`: líder previo del `kube-controller-manager`, NotReady, migración de cada VIP, API restablecida y Ready tras la restauración, calculados solo con el bloque `analisis`; autotest. |
| `k6/medicion/secuencia_control.sh` (nuevo) | Control de `--rtt` y `--cgroup-cp`: escenario `media` en tres condiciones con el orden rotado. |
| `k6/medicion/secuencia_fallo.sh` (nuevo) | Protocolo de ≥ 5 corridas `media` con fallo por distribución. |
| `k6/medicion/estado_inicial.sh` (nuevo) | Escribe `estado_inicial.txt` de la sesión (mismos bloques que las pasadas del 28-oct, más el RSS de QEMU). |
| `k6/medicion/secuencia_piloto.sh` | Variable `ORQ_EXTRA` para pasar opciones al orquestador (por ejemplo `--rtt`). |
| `data/README.md`, `README.md` | Campos nuevos de los metadatos y sesiones `_control` y `_fallo`. |

Antes de medir corrí los autotests, el análisis de datos existentes y la validación de argumentos del orquestador (rechaza `--rtt` o `--cgroup-cp` junto con `--fallo` y `--rtt-muestras` menor que 20). Las mediciones están en la sección 9.

## 2. PT-A: análisis de lo ya medido

### 2.1 Método

- **Ventana.** `t_inicio` a `t_fin` de los metadatos (fase estable, puntos medios de las lecturas de RAPL).
- **CPU.** `1 − Δidle/Δtotal` de `node_cpu_seconds_total` (suma de todos los CPU y modos; `idle` es solo el modo `idle`, `iowait` cuenta como uso), entre la primera muestra dentro de la ventana y la última. Resolución de scrape: 10 s, unas 18 muestras por ventana. Se calcula para el host (16 hilos) y para cada VM (2 vCPU).
- **RAM.** Media de `MemTotal − MemAvailable` en las muestras de la ventana, por VM y para el host. En la figura, la RAM de las VM es la media de las tres.
- **Latencia.** `http_req_duration` (p50, p95 y p99) y medias de `blocked`, `connecting`, `waiting`, `sending` y `receiving`, de las solicitudes de la fase estable, desde el JSON crudo de k6 (columnas `ve_*`). Los percentiles usan `k6/lib/agregado.pct`, el mismo método de `por_segundo`. No se usa la mediana de los p95 por segundo.
- **Resumen de k6 (columnas `res_*`).** Lo incluyo aparte porque cubre la ejecución completa (rampa, fase estable y descenso) y no trae p99: `--summary-export` entrega `avg`, `min`, `med`, `max`, `p(90)` y `p(95)`. Por eso no puede dar la latencia de la fase estable pedida.
- **Crudo.** `data/k6-crudo/` no se versiona. `analysis/salidas/<salida>/cache_latencia.json` guarda lo calculado, con el `sha256` del crudo, para repetir el análisis sin él. La primera ejecución sobre 18 corridas tardó 93 s.
- **Histograma por corrida.** Además de p50, p95 y p99, guardo en la caché un histograma de `http_req_duration` de la fase estable con contenedores geométricos (primer contenedor desde 0,05 ms, razón 1,02): el error relativo de un cuantil leído del histograma es de hasta 2 %. Pesa unos 2 KB por corrida (36 KB la caché de 18 corridas) y permite rehacer el espectro de percentiles sin el crudo. Los valores exactos de p50, p95 y p99 siguen saliendo de la muestra completa.
- **Configuraciones.** El script se detiene si una misma salida mezcla tasas distintas por escenario o tipos distintos de corrida.

```
python3 -m analysis.recursos_latencia --sesion data/pilotos/2026-10-28_k3s --sesion data/pilotos/2026-10-28_microk8s \
    --salida analysis/salidas/2026-10-28_configuracion_definitiva
python3 -m analysis.figuras --recursos analysis/salidas/2026-10-28_configuracion_definitiva/recursos_latencia.csv \
    --salida analysis/salidas/2026-10-28_configuracion_definitiva --rotulo "Preliminar, una sesión"
```

### 2.2 Validación contra cifras ya informadas (medido)

| Cifra del informe (sesión del 28-oct) | Recalculado con el script | Coincide |
|---|---|---|
| Potencia K3s `idle`: 4,158 W | 4,158 W | Sí |
| Potencia MicroK8s `alta`: 5,608 W | 5,608 W | Sí |
| Potencia K3s `media` y `alta`; MicroK8s `idle` y `media` | 4,955; 5,553; 4,157; 4,964 W | Sí |
| p95 de `alta` K3s: 6,3 a 6,5 ms | 6,307; 6,339; 6,511 ms | Sí |
| p95 de `alta` MicroK8s: 42,0 a 48,8 ms | 41,952; 44,200; 48,793 ms | Sí |
| p99 de `alta`: K3s 16,5 a 23,1 ms; MicroK8s 72,5 a 77,4 ms | 16,474 a 23,085; 72,538 a 77,377 ms | Sí |
| Descartadas de `alta`: K3s 45, 29, 32; MicroK8s 34, 44, 39 | iguales | Sí |

Diferencia que sí hay: el p95 del **resumen de k6** de esas mismas corridas es 5,9 a 6,1 ms en K3s y 38,4 a 45,7 ms en MicroK8s, menor que el de la fase estable. Causa (interpretación): el resumen incluye la rampa y el descenso, con menos carga y menor latencia. Por eso las tablas del informe deben citar la fase estable (`ve_*`), no el resumen.

### 2.3 Resultados preliminares (medido; 28-oct, 3 repeticiones por celda, una sesión)

| Escenario | Distribución | CPU host (%) | CPU VM (%) | RAM usada por VM (MB) | RAM usada del host (MB) | p95 (ms) |
|---|---|---|---|---|---|---|
| `idle` | K3s | 4,2 | 6,05 | 857 | 8816 | sin carga |
| `idle` | MicroK8s | 5,0 | 7,05 | 977 | 13 088 | sin carga |
| `media` (450 rps) | K3s | 10,9 | 15,21 | 854 | 8908 | 2,11 |
| `media` (450 rps) | MicroK8s | 12,0 | 16,97 | 977 | 13 177 | 2,39 |
| `alta` (900 rps) | K3s | 19,8 | 29,33 | 858 | 8968 | 6,39 |
| `alta` (900 rps) | MicroK8s | 21,0 | 32,52 | 975 | 13 216 | 44,98 |

Son medias de 3 repeticiones, con potencias de 4,157 a 5,608 W (`evidencia_T-20.md`, 7.6). Sin barras de error ni pruebas de significancia (n = 3).

- **Interpretación (no probada).** La diferencia de RAM usada del host entre distribuciones (≈ 4,3 GB) es mucho mayor que la de las VM (≈ 120 MB por VM). `MemAvailable` de la VM excluye la caché de página, mientras que el RSS de QEMU en el host la incluye si el invitado la mantiene. Es la razón de PT-C (RSS de QEMU por proceso): hoy no se puede atribuir esa diferencia. Tampoco se descarta un efecto de sesión (el host se reinició a las 17:53 y el swap se liberó antes de cada secuencia).
- **Hecho.** El RSS de QEMU de K3s no se leyó el 28-oct (`estado_inicial.txt` de K3s solo registra el estado tras liberar el swap).

### 2.4 Figuras

Se generan con `analysis/figuras.py` a partir de los CSV y la caché (no se editan a mano). Cada figura muestra todos los puntos o todas las corridas (n = 3 por celda), sin barras de error ni cajas, porque con tres repeticiones esas formas ocultan los datos. Color por distribución (azul K3s, naranja MicroK8s; paleta validada para daltonismo) y forma distinta (círculo, triángulo) para que se distingan también en impresión en blanco y negro.

| Archivo | Contenido |
|---|---|
| `figura_energia_latencia.pdf` | Potencia frente a p95 de la fase estable (escala logarítmica): un punto por repetición, una flecha de `media` a `alta` por distribución y una línea de potencia en reposo. |
| `figura_cpu_ram.pdf` | Cuatro paneles (CPU del host, CPU de las VM, RAM usada por VM, RAM usada del host) con una fila por escenario; un punto por repetición, barra de mínimo a máximo y media escrita; ejes desde cero. |
| `figura_espectro_latencia.pdf` | Espectro de percentiles de `media` y `alta`: una línea por corrida, latencia en escala logarítmica frente al percentil (0, 90, 99, 99,9 %); incluye las solicitudes descartadas por k6 en `alta`. |
| `figura_memoria_host.pdf` | Barra apilada de la memoria del host: RSS de cada VM de QEMU, otros usos y memoria disponible. Solo si el CSV trae `rss_vm*_mb` (no existe para el 28-oct). |
| `figura_recuperacion.pdf` | Línea de tiempo por corrida con fallo, en segundos desde la inyección: API no disponible, migración de cada VIP, NotReady, restauración y Ready; agrupada por distribución y por liderazgo del controlador. |

**Hecho.** El percentil 99,9 % de una corrida de `media` (≈ 81 000 solicitudes) se apoya en unas 80 solicitudes; más allá, en pocas decenas o menos, así que el espectro se corta en 99,9 %. En `alta`, k6 descartó solicitudes (`dropped_iterations`) cuando se agotaron las VU; esas solicitudes no tienen latencia medida, de modo que las colas de `alta` están subestimadas. No verifiqué si k6 corrige esa omisión: el ejecutor es `ramping-arrival-rate` (modelo abierto) y las descartadas se registran aparte.

Formato: PDF vectorial con fuentes incrustadas, 16,0 cm de ancho, fuente de 8 pt, sin color de fondo, coma decimal. Se pueden rotular con `--rotulo`. La configuración inicial (100 rps) no se grafica junto a la definitiva; solo existe `recuperacion.csv` en `analysis/salidas/2026-10-20_recuperacion_inicial/`.

Revisé las figuras sobre una rasterización a 80 ppp; no revisé la maquetación final en el informe.

## 3. PT-B: RTT de la red virtual

**Hecho (código; ejecutado en la sección 9).** `--rtt` ejecuta `ping -c <n> -i 0.2 -q` con `n ≥ 20` (`--rtt-muestras`):

- desde el host a la VIP del servicio, la VIP del plano de control y cada nodo;
- entre nodos (cada nodo hacia los otros dos) por SSH.

Mido dos veces, **antes de la espera de estabilización y después de que termina k6**, nunca durante la fase estable ni la ventana de RAPL. Todo en serie para no cargar la red virtual. Resultado en `rtt.inicio` y `rtt.fin` (`min_ms`, `media_ms`, `max_ms`, `mdev_ms`, `perdida_pct`, `enviados`, `recibidos`). No se combina con `--fallo`.

**Red virtual (hecho).** `red_virtual` registra, en cada corrida y por dominio activo, la NIC (`virsh domiflist`: tipo, red, modelo y MAC) y el modo de la red de libvirt (`virsh net-dumpxml`: `forward`, puente y dirección). Terraform declara la red del clúster con `mode = "nat"` (`k3sHA/terraform/main.tf`, `libvirt_network`); el modelo de la NIC no está fijado en Terraform, así que su valor se conocerá en la primera corrida (supuesto: no se verificó, no hay VM encendidas). El formato de `virsh` se probó con la red `default` y un dominio apagado del host, no con las VM del proyecto.

**Limitación que debe declararse en el informe.** La red es virtual y comparte host con las VM, k6 y Prometheus. El RTT mide el camino host–puente de libvirt–NIC virtual (NAT, no una red física) y entre invitados el conmutador del puente. Sus valores no son transferibles a un clúster físico y comparten con la medición de potencia las mismas CPU del host. Entre distribuciones solo es comparable si la red de libvirt y el modelo de la NIC son los mismos, lo que se verifica con `red_virtual`.

**Corrida de control (resultado en la sección 9.2).** Diseño: `k6/medicion/secuencia_control.sh <distribución> 450` corre `media` en tres condiciones (`base`, `rtt`, `cgroup`), 3 repeticiones cada una, en el mismo clúster y sesión, con el orden rotado (`base, rtt, cgroup / rtt, cgroup, base / cgroup, base, rtt`) para que ninguna condición vaya siempre primero. El análisis (`--control`) da media y desviación por condición y la diferencia respecto de la base en potencia y p95.

- **Por qué en la misma sesión.** Entre sesiones el nivel de potencia se desplazó ≈ 1 W sin causa conocida (`evidencia_T-20.md`, 7.6): una comparación contra las corridas del 28-oct no serviría.
- **Poder de la prueba.** Con n = 3 por condición y desviaciones agrupadas de 0,005 W (MicroK8s) y 0,032 W (K3s) en la sesión del 28-oct, solo se detectarían efectos mayores que esas desviaciones. Un resultado sin diferencias no probaría equivalencia; se informaría la diferencia observada y su tamaño frente a la desviación.
- **Escenario `media`.** Es una elección (carga intermedia, p95 de ≈ 2 ms); no está justificada con una prueba.

## 4. PT-C: RAM del host y costo por distribución

**Hecho (código; resultados en la sección 9.3).** En cada corrida, sin opciones y fuera de la ventana, el orquestador guarda `recursos_host.inicio` (justo antes de lanzar k6) y `recursos_host.fin` (justo después de que k6 termina), leídos de `/proc` del host sin tocar la red ni las VM:

- `MemAvailable`, `MemTotal`, `SwapTotal` y `SwapFree`;
- contadores acumulados `pswpin` y `pswpout`;
- `VmRSS`, `RssAnon`, `RssFile` y `RssShmem` de cada proceso `qemu-system-x86`, con el nombre del dominio.

`recursos_host.resumen` resume las páginas de swap movidas entre ambas fotos y el mínimo de `MemAvailable` del host de la ejecución completa, consultado a Prometheus (`min_over_time`). El tamaño de página no se lee: la conversión a MB (4 kB por página) es un supuesto estándar de x86-64.

**Opcional, `--cgroup-cp`.** Lectura única de `cpu.stat` (`usage_usec`) y `memory.current` de las unidades del plano de control de cada nodo, por SSH y en paralelo:

- K3s: `k3s.service`;
- MicroK8s: `snap.microk8s.daemon-kubelite.service`, `snap.microk8s.daemon-k8s-dqlite.service` y `snap.microk8s.daemon-containerd.service`.

La primera lectura termina unos 3 s antes de la lectura inicial de RAPL y la segunda empieza justo después de la final, de modo que ninguna cae dentro de la ventana. Por eso el intervalo entre lecturas (`t_inicio`, `t_fin` de cada una) es un poco mayor que la fase estable (≈ 5 s antes y unos segundos del descenso después); la tasa de CPU de cada componente debe calcularse con el intervalo real entre lecturas. Qué incluye el cgroup de cada unidad no se verificó: en K3s, `containerd` está embebido en el proceso `k3s`, pero no se comprobó si los `containerd-shim` de los pods quedan dentro de `k3s.service` o fuera de él. Si la ruta `/sys/fs/cgroup/system.slice/<unidad>/` no existe, el campo queda `null` y la corrida continúa; en las corridas del 2-nov existió en los tres nodos de ambas distribuciones (9.2). El control de la sección 9.2 incluye la condición `cgroup`.

## 5. PT-D: corridas con fallo para la recuperación

### 5.1 Protocolo (ejecutado el 2-nov; resultados en 9.4)

`k6/medicion/secuencia_fallo.sh <distribución> 450 5` ejecuta 5 corridas `media` con `--fallo`, retención de 120 s, configuración definitiva y kube-vip vigente (el orquestador reinicia `kube-vip` hasta 3 veces si las dos VIP quedan en nodos distintos; es el comportamiento existente). En cada corrida el nodo fallado es el que sostiene a la vez la VIP del plano de control y la del servicio, y el pod de NGINX se mueve fuera de ese nodo si coincide. Sesión: `data/pilotos/<fecha>_<distribución>_fallo/`. Se detiene en la primera falla y puede reanudarse con la repetición inicial. Se repite hasta 5 por distribución; no se justificó estadísticamente (n = 5 sigue siendo pequeño).

**Efecto de `mover_pod` (hecho).** Cuando el pod coincide con el nodo a fallar, `fallo.mover_pod` cambia el `nodeSelector` del `Deployment` con `kubectl patch`, lo que avanza su revisión. El `Deployment` ya trae un `nodeSelector` desde el manifiesto original. Ocurrió en 1 de las 10 corridas (MicroK8s, corrida 5). Decidí no limpiar el parche entre corridas y declararlo.

### 5.2 Análisis agregado a cada corrida (hecho)

`fallo.analisis.tiempos_s` incluye: `lider_controller_manager_previo` y `nodo_fallado_lideraba` (último titular del lease `kube-controller-manager` anterior a la inyección, tomado del estado ya registrado cada 2 s), `notready` (kubectl, resolución 2 s), `migracion_vip_plano_control` y `migracion_vip_servicio`, `api_caida_desde` y `api_restablecida`, `restauracion`, `ready_tras_restauracion` y `fallidas_k6`. El nodo fallado, la restauración y las caídas ya estaban. La misma función se aplica a las corridas existentes, que traen el bloque `analisis`:

| Sesión | Distribución | Nodo fallado | ¿Lideraba el controlador? | NotReady (s) | Migración VIP `.100` (s) | API restablecida (s) | Ready tras restaurar (s) |
|---|---|---|---|---|---|---|---|
| 27-oct T-22 (definitiva, 450 rps) | K3s | node1 | Sí | 67,7 | 18,2 | 19,2 | 10,9 |
| 27-oct T-22 (definitiva, 450 rps) | MicroK8s | node1 | Sí | 117,2 | 18,3 | 19,3 | 8,5 |
| 19 y 20-oct (inicial, 100 rps) | K3s r1, r2, r3 | node2, node3, node1 | No, Sí, Sí | 51,7; 69,6; 74,0 | sin migración; 18,7; 22,7 | 93,7; 19,7; 23,7 | 7,4; 7,2; 7,6 |
| 20-oct (inicial, 100 rps) | MicroK8s r2, r3 | node1, node2 | Sí, Sí | 96,1; 111,9 | 20,7; 20,7 | 21,7; 21,7 | 15,7; 5,6 |

Las corridas de la configuración inicial no se grafican con las definitivas. En la `r1` de K3s del 19-oct la VIP no migró y la API se restableció a los 93,7 s; no investigué la causa (supuesto sin verificar: corrida anterior al ajuste de kube-vip). Solicitudes fallidas en k6: 0 en las dos corridas definitivas.

**Medido.** En 6 de las 7 corridas con análisis disponible, el nodo fallado lideraba el `kube-controller-manager`. **Interpretación (no probada, n = 7 y configuraciones mezcladas en la lectura):** el nodo elegido para el fallo (titular de ambas VIP) coincide con el líder del controlador por azar de arranque, y la corrida de K3s del 19-oct es la única sin ese traslape. El NotReady de MicroK8s (96 a 117 s) fue mayor que el de K3s (52 a 74 s) en todas las corridas, pero no es posible separar el efecto de la distribución del efecto del liderazgo con estos datos.

### 5.3 Decisión: liderazgo del controlador

Decidí registrar el liderazgo del `kube-controller-manager` en cada corrida (`nodo_fallado_lideraba`) y reportar los tiempos por estrato, sin forzar el estrato antes de cada fallo.

Motivos (hechos): el nodo fallado queda determinado por las VIP, no por el liderazgo. Forzar el estrato exigiría reiniciar `kube-vip` o eliminar el lease del controlador hasta que coincida el titular de las VIP con el líder; cada intento cuesta al menos 30 s, el resultado es aleatorio y es una intervención nueva en el plano de control antes de medir. Fallar siempre al líder dejaría un solo caso y reduciría el alcance del resultado.

Consecuencia: los estratos quedan desbalanceados (2 y 3 corridas por distribución, 9.4). La comparación entre distribuciones es válida solo dentro de cada estrato, y declaro en el informe que con 5 corridas y sin forzar el estrato el caso «el nodo fallado no lideraba» podía quedar sin representar.

### 5.4 Decisión: fallo del nodo que aloja el pod de NGINX

**Hecho.** En las dos distribuciones el pod de referencia tiene las tolerancias `node.kubernetes.io/not-ready` y `node.kubernetes.io/unreachable` con `tolerationSeconds: 300` (registradas en `parametros_efectivos.tolerancias_pod` de las corridas del 27-oct). Con una réplica, el pod no se reprograma hasta cumplirse ese plazo, mayor que la retención de 120 s.

**Decisión.** No medí este caso en esta entrega. El protocolo mueve el pod fuera del nodo a fallar, de modo que las corridas miden el fallo de un nodo del plano de control sin pérdida de la aplicación (0 solicitudes fallidas en las 10 corridas).

**Motivos.** Medirlo exigiría cambiar algo que hoy es igual en las dos distribuciones y en las demás corridas: extender la retención a más de 300 s dejaría esas corridas sin comparación con las de 120 s; fijar `tolerationSeconds` o usar 2 réplicas cambiaría la aplicación definitiva y obligaría a repetir calibración y pilotos (supuesto: no lo verifiqué con una corrida). Queda declarado como limitación y trabajo futuro; si lo mido, extenderé la retención a más de 300 s, que es el cambio que menos altera la aplicación.

## 6. Guía de ejecución

Orden de sesiones por distribución, en un mismo clúster, de menor a mayor perturbación. Medí MicroK8s primero y K3s después, como en la pasada del 28-oct (sin justificación estadística). Cada secuencia empieza con el swap liberado y el estado inicial registrado. Lanzo las secuencias desde la consola de texto.

```bash
# 0. Construcción (sesión gráfica abierta); ciclos siguientes: MicroK8s 8, K3s 9
cd ~/universidad/5to_año/tesis
k6/operacion/despliegue.sh <distribución> construir <ciclo>
cd ansible && ansible-playbook playbook.yml --ask-become-pass -e active_distribution=<distribución> && cd ..

# 1. Modo medición y swap (consola de texto)
sudo /usr/local/sbin/tesis-modo-medicion salir && sudo /usr/local/sbin/tesis-modo-medicion entrar
sudo swapoff -a && sudo swapon -a

# 2. Estado inicial (antes de cada secuencia)
k6/medicion/estado_inicial.sh data/pilotos/$(date +%F)_<distribución>_control

# 3. Control de PT-B y PT-C: 9 corridas media
k6/medicion/secuencia_control.sh <distribución> 450

# 4. Pasada completa con RTT, si el control no muestra efecto (idle, media y alta × 3)
sudo swapoff -a && sudo swapon -a
k6/medicion/estado_inicial.sh data/pilotos/$(date +%F)_<distribución>
ORQ_EXTRA="--rtt" k6/medicion/secuencia_piloto.sh <distribución> 450 900 3

# 5. Corridas con fallo (PT-D)
sudo swapoff -a && sudo swapon -a
k6/medicion/estado_inicial.sh data/pilotos/$(date +%F)_<distribución>_fallo
k6/medicion/secuencia_fallo.sh <distribución> 450 5

# 6. Destrucción y análisis
k6/operacion/despliegue.sh <distribución> destruir <ciclo>
python3 -m analysis.recursos_latencia --sesion data/pilotos/<sesión> --control --salida analysis/salidas/<nombre>
```

Tras cada ejecución del `ansible-playbook` hay que repetir `salir` y `entrar` (como el 28-oct). El análisis se corre por sesión: las sesiones `_control`, la pasada completa y `_fallo` comparten configuración, pero conviene no mezclar escenarios distintos en una misma figura.

**Duración estimada y fuente del cálculo.**

| Paso | Estimación | Fuente |
|---|---|---|
| Construcción | K3s 278 s; MicroK8s 820 s | `despliegue_*.jsonl`, ciclos 8 y 7 del 28-oct |
| Control (9 corridas `media`) | ≈ 56 min + ≈ 5 min de RTT = ≈ 61 min | 9 corridas del 28-oct tardaron 55,7 y 55,8 min (≈ 372 s por corrida); RTT: 5 destinos del host y 6 pares entre nodos, 4 s de ping cada uno más SSH, dos veces por corrida, ≈ 100 s por corrida con `--rtt` (cálculo, no medido) × 3 corridas |
| Pasada con RTT (9 corridas) | ≈ 56 min + ≈ 15 min de RTT = ≈ 71 min | igual que arriba, 9 corridas con `--rtt` |
| 5 corridas con fallo | ≈ 32 min como mínimo, ≈ 42 min con reinicios de kube-vip o movimiento del pod | corridas con fallo de T-22: 376 y 382 s de duración total con `estabilización` de 120 s (`validacion_*.json`); cada reinicio de kube-vip agrega ≥ 30 s y el movimiento del pod hasta 120 s (cota del código, no medida) |
| Destrucción | ≈ 7 s | ciclos 7 y 8 del 28-oct |

Suma por distribución: ≈ 2,7 h de corridas (61 + 71 + 32 min), 2,8 a 3,1 h con construcción y las cotas altas, sin contar el estado inicial ni los pasos manuales. Las dos distribuciones: ≈ 5,6 a 6,2 h. Es una suma de las estimaciones anteriores; las duraciones medidas el 2-nov están en 9.1.

## 7. Decisiones y pendientes

Decisiones tomadas el 2 de noviembre de 2026:

1. **Liderazgo del controlador:** solo registrar `nodo_fallado_lideraba` y reportar por estrato (5.3).
2. **Fallo del nodo que aloja el pod de NGINX:** no se mide en esta entrega; queda como limitación y trabajo futuro (5.4).
3. **`nodeSelector` de `mover_pod`:** se deja y se declara; no se limpia entre corridas (5.1).
4. **Snapshots de Prometheus:** conservo solo el último de los seis copiados el 2-nov (`20261102T213240Z-62172146fba6aca9`), porque cada uno contiene a los anteriores. Los metadatos de las corridas finales de los otros bloques siguen nombrando su propio snapshot, que está contenido en el conservado.

Pendientes:

1. Resolver con el diseño de la campaña (no con estas sesiones) la diferencia de nivel de potencia entre sesiones (9.5).
2. Hacer el commit de código y datos del 2-nov para fijar el estado del código con el que medí.

## 8. Límites

- Todo número de las secciones 2 y 10 es de una sesión por distribución, con 3 repeticiones por celda (5 en las corridas con fallo); no hay pruebas de hipótesis.
- El nivel de potencia cambia entre sesiones hasta ≈ 1,9 W sin causa conocida (9.5): los valores solo son comparables dentro de su sesión y la potencia de K3s no es comparable con la de MicroK8s cuando se midieron en sesiones distintas.
- Estratos del liderazgo del controlador desbalanceados (2 y 3 corridas por distribución); sin forzar el estrato.
- Ruta de cgroup, modelo de NIC y `ping -i 0.2` en las VM quedaron verificados por las corridas del 2-nov (9.2 y 9.3); la atribución de memoria de cada cgroup y qué procesos incluye (por ejemplo los `containerd-shim` de K3s) no se verificó.
- La RTT es de una red virtual NAT que comparte host con las VM, k6 y Prometheus; no es transferible a una red física.

## 9. Resultados de las mediciones del 2 de noviembre de 2026

### 9.1 Ejecución

Un clúster a la vez, MicroK8s primero y K3s después. Cada clúster se construyó desde el código con `k6/operacion/despliegue.sh` (MicroK8s ciclo 10, 757,9 s; K3s ciclo 9, 296,3 s), con la sesión gráfica abierta (`modo_medicion: false`), y se verificó antes de medir: 3 nodos `Ready`, `nginx-referencia` en la revisión 1 con límite `2` y solicitud `500m`, VIP `.100` respondiendo 401 sin credenciales, VIP `.150` devolviendo el SHA-256 ×300 esperado. Después entré en modo medición, liberé el swap con `swapoff -a && swapon -a` antes de cada bloque, registré `estado_inicial.txt` (swap usado: 0 B en 5 de los 6 registros y 4 kB en el de fallo de MicroK8s) y lancé cada secuencia desde la consola de texto.

| Bloque | Sesión (`data/pilotos/`) | MicroK8s | K3s |
|---|---|---|---|
| Control (9 corridas `media`) | `2026-11-02_<distribución>_control` | 12:31 a 13:32 (60,8 min) | 15:44 a 16:45 (60,7 min) |
| Pasada con `--rtt` (idle, media y alta × 3) | `2026-11-02_<distribución>` | 13:35 a 14:46 (70,5 min) | 16:46 a 17:56 (70,4 min) |
| 5 corridas `media` con fallo | `2026-11-02_<distribución>_fallo` | 14:52 a 15:28 (36,0 min) | 17:58 a 18:32 (34,6 min) |

Las duraciones quedan dentro de las estimaciones de la sección 6 (61, 71 y 32 a 42 min). Todas las corridas son `--tipo piloto` y `valida_para_campana = false`. En las 23 corridas por distribución: código de salida de k6 0, 0 solicitudes fallidas, titulares de las VIP sin cambios salvo en las de fallo, espera de reloj de 4,2 a 6,4 s, sin abortos. Cada sesión tiene sus metadatos, resúmenes, `por_segundo` y ventanas de Prometheus completos; el último snapshot de cada bloque está en `data/prometheus-snapshots/`.

### 9.2 Control de `--rtt` y `--cgroup-cp` (medido)

Escenario `media` (450 rps), 3 corridas por condición en la misma sesión, con el orden rotado. Medias (desviación muestral) de la fase estable:

| Distribución | Condición | Potencia (W) | Dif. de potencia vs. base (W) | p95 (ms) | Dif. de p95 vs. base (ms) |
|---|---|---|---|---|---|
| K3s | base | 6,836 (0,009) | | 2,188 | |
| K3s | `--rtt` | 6,820 (0,014) | −0,016 | 2,203 | +0,015 |
| K3s | `--cgroup-cp` | 6,827 (0,012) | −0,009 | 2,214 | +0,026 |
| MicroK8s | base | 4,957 (0,010) | | 2,402 | |
| MicroK8s | `--rtt` | 4,950 (0,004) | −0,007 | 2,416 | +0,014 |
| MicroK8s | `--cgroup-cp` | 4,954 (0,003) | −0,003 | 2,478 | +0,076 |

- **Medido.** Las diferencias de potencia son de 0,003 a 0,016 W (≤ 0,24 % del nivel) y las de p95 de 0,014 a 0,076 ms, del orden de la dispersión de la condición base. La menor potencia con opciones (K3s 6,803 W y MicroK8s 4,946 W, ambas con `--rtt`) queda 0,027 y 0,003 W bajo el mínimo de las tres bases. El p99 de K3s fue 4,31 (base), 4,27 y 4,28 ms; el de MicroK8s, 5,01; 4,97 y 5,40 ms (con dispersión de 0,9 ms en `cgroup`).
- **Medido, sin explicación.** Una corrida de MicroK8s con `--rtt` tuvo 15,8 % de CPU del host frente a 11,2 a 13,0 % en las demás, sin cambio en potencia ni en latencia. No la investigué.
- **Interpretación.** No observo efecto de las opciones en estas dos sesiones. Con n = 3 no es una prueba de equivalencia: solo descarta efectos grandes frente a la dispersión. Usé `--rtt` en la pasada completa y no usé `--cgroup-cp`, porque su objetivo era medir el costo de los componentes en las corridas de control.
- **Verificado en estas corridas.** `ping -i 0.2` funciona dentro de las VM (0 % de pérdida entre nodos), las rutas de cgroup existen y en MicroK8s las lecturas por SSH duraron de 1,1 a 2,8 s, con intervalo entre lecturas de 183,7 a 183,9 s (fase estable de 180 s); no calculé esos valores en K3s.

### 9.3 RAM del host, cgroups y RTT (medido)

**RSS de QEMU** (suma de las 3 VM, 36 lecturas por distribución al inicio y fin de cada corrida de las sesiones de control y de pasada):

| Distribución | RSS medio (MB) | Rango (MB) | Por VM (MB) | Parte anónima (MB) |
|---|---|---|---|---|
| K3s | 7643 | 7461 a 7890 | ≈ 2550 de 4096 | 7567 |
| MicroK8s | 11 993 | 11 743 a 12 143 | ≈ 4000 de 4096 | 11 953 |

- **Medido.** La RAM usada del host (`MemTotal − MemAvailable`) fue 8,0 a 8,3 GB con K3s y 13,5 GB con MicroK8s; la diferencia (5,2 a 5,5 GB) es del orden de la del RSS de QEMU (≈ 4,35 GB), aunque no coincide exactamente. Dentro de las VM, la RAM usada (sin caché) fue ≈ 860 MB con K3s y ≈ 985 MB con MicroK8s por VM.
- **Interpretación (no probada).** El RSS de QEMU incluye la memoria que el invitado tocó (por ejemplo, caché de página), por lo que no equivale a la RAM que requiere cada distribución. Con los datos no puedo separar una cosa de la otra. No es una afirmación de que MicroK8s «necesite» más RAM.
- **Margen del host.** MicroK8s: mínimo de `MemAvailable` de 1239 MB en la fase estable (215 MB sobre el umbral de 1024) y actividad de swap en varias corridas (hasta 5941 páginas escritas en una corrida de `alta`; ≈ 23 MB si la página es de 4 kB, supuesto estándar). K3s: mínimo de 5612 MB y 0 páginas de swap en todas las corridas.

**CPU y memoria de los componentes del plano de control** (`--cgroup-cp`, media de 3 nodos × 3 corridas de `media`):

| Distribución | Unidad | CPU (núcleos) | `memory.current` (MB) |
|---|---|---|---|
| K3s | `k3s.service` | 0,094 | 1095 |
| MicroK8s | `kubelite` | 0,048 | 268 |
| MicroK8s | `k8s-dqlite` | 0,034 | 57 |
| MicroK8s | `containerd` | 0,020 | 1293 |
| MicroK8s | suma | 0,102 | 1618 |

`memory.current` incluye caché de página. En K3s, `containerd` está embebido en `k3s.service`; no verifiqué si los procesos de contenedores de los pods quedan dentro o fuera de ese cgroup, por lo que las unidades de ambas distribuciones no son exactamente comparables. Interpreto solo el orden de magnitud (≈ 0,1 núcleo de CPU del plano de control por nodo en ambas).

**RTT** (`ping`, 20 muestras a 0,2 s; 24 mediciones por distribución, antes y después de cada corrida con `--rtt`; media de las medias):

| Camino | K3s (ms) | MicroK8s (ms) |
|---|---|---|
| Host a la VIP del servicio | 0,263 | 0,258 |
| Host a la VIP del plano de control | 0,266 | 0,264 |
| Host a los nodos | 0,264 a 0,284 | 0,260 a 0,275 |
| Entre nodos | 0,458 | 0,425 |

0 % de pérdida en todas. La NIC de cada VM es `virtio` sobre una red de libvirt en modo `nat` (puente `virbr1`, `192.168.100.1`; `microk8s-tesis` en MicroK8s). No calculé dispersión entre corridas; no interpreto diferencias de 0,03 a 0,04 ms entre distribuciones. Es una red virtual que comparte host y CPU con las VM, k6 y Prometheus: son valores del camino virtual, no de una red física.

### 9.4 Recuperación ante fallo (medido; 5 corridas por distribución, retención de 120 s)

| Distribución | Corrida | Nodo fallado | ¿Lideraba el controlador? | NotReady (s) | Migración VIP `.100` (s) | Migración VIP `.150` (s) | API restablecida (s) | Ready tras restaurar (s) | Fallidas k6 |
|---|---|---|---|---|---|---|---|---|---|
| K3s | 1 | node1 | Sí | 74,2 | 25,5 | 22,4 | 26,5 | 13,4 | 0 |
| K3s | 2 | node3 | Sí | 67,2 | 19,3 | 16,2 | 19,3 | 12,4 | 0 |
| K3s | 3 | node1 | No | 49,4 | 20,3 | 19,3 | 21,3 | 13,0 | 0 |
| K3s | 4 | node1 | No | 49,2 | 18,2 | 20,3 | 19,3 | 12,4 | 0 |
| K3s | 5 | node1 | No | 47,2 | 18,3 | 17,3 | 19,3 | 12,4 | 0 |
| MicroK8s | 1 | node3 | No | 53,1 | 19,2 | 18,2 | 20,2 | 8,4 | 0 |
| MicroK8s | 2 | node3 | No | 51,2 | 19,3 | 16,2 | 20,3 | 8,6 | 0 |
| MicroK8s | 3 | node1 | Sí | 111,5 | 16,3 | 19,3 | 17,3 | 8,0 | 0 |
| MicroK8s | 4 | node3 | Sí | 113,1 | 17,3 | 15,2 | 18,3 | 7,2 | 0 |
| MicroK8s | 5 | node2 | Sí | 113,0 | 17,3 | 24,4 | 18,4 | 7,2 | 0 |

Los tiempos son segundos desde la inyección; la resolución es de 1 s (VIP y API), 2 s (NotReady, vía `kubectl`) y la inyección tiene una cota de ≈ 0,8 s. Las dos corridas de T-22 (`verificacion`, 450 rps) siguen el mismo patrón (K3s 67,7 s y MicroK8s 117,2 s, con el nodo fallado liderando el controlador).

- **Medido.** NotReady según el liderazgo del nodo fallado: K3s, 67,2 y 74,2 s si lideraba (n = 2) y 47,2 a 49,4 s si no (n = 3); MicroK8s, 111,5 a 113,1 s si lideraba (n = 3) y 51,2 y 53,1 s si no (n = 2). La migración de las VIP (15,2 a 25,5 s) y el restablecimiento de la API (17,3 a 26,5 s) no muestran esa separación. Ready tras restaurar: K3s 12,4 a 13,4 s y MicroK8s 7,2 a 8,6 s. Solicitudes fallidas de k6: 0 en las 10 corridas.
- **Interpretación (no probada).** El liderazgo del controlador separa los tiempos de NotReady en ambas distribuciones (≈ +22 s en K3s y ≈ +60 s en MicroK8s). Una hipótesis es que, si cae el líder, el controlador de ciclo de vida de nodos tarda en reasumir en el nodo nuevo. No lo probé. Con estratos de 2 y 3 corridas, una comparación del NotReady promedio entre distribuciones queda confundida por el liderazgo; la comparación válida es dentro de cada estrato.
- **Hecho.** Para igualar las VIP antes del fallo, el orquestador reinició `kube-vip` 0 a 3 veces por corrida (K3s: 0, 0, 0, 3, 2; MicroK8s: 0, 2, 0, 2, 2). En la corrida 5 de MicroK8s el pod coincidía con el nodo a fallar y se movió de node2 a node1. El `Deployment` ya trae un `nodeSelector` a un nodo desde el manifiesto original (revisión 1 al construir).
- **Figura.** `figura_recuperacion.pdf` agrupa las corridas por distribución y por liderazgo, porque el NotReady tiene dos grupos y un promedio no los representa.

### 9.5 Pasada completa con RTT: recursos, energía y latencia (medido; 3 repeticiones por celda)

| Escenario | Distribución | Potencia (W) | CPU host (%) | CPU VM (%) | RAM usada por VM (MB) | RAM usada del host (MB) | p95 (ms) | p99 (ms) |
|---|---|---|---|---|---|---|---|---|
| `idle` | K3s | 5,749 (0,007) | 4,0 | 5,16 | 870 | 8343 | sin carga | sin carga |
| `idle` | MicroK8s | 4,157 (0,003) | 5,4 | 6,91 | 987 | 13 455 | sin carga | sin carga |
| `media` | K3s | 6,830 (0,019) | 11,7 | 15,03 | 860 | 8103 | 2,31 (2,23 a 2,36) | 4,6 |
| `media` | MicroK8s | 4,946 (0,003) | 12,4 | 16,81 | 985 | 13 486 | 2,40 (2,37 a 2,42) | 4,9 |
| `alta` | K3s | 7,533 (0,027) | 20,5 | 30,86 | 861 | 8000 | 8,36 (8,12 a 8,75) | 23,9 |
| `alta` | MicroK8s | 5,596 (0,003) | 21,1 | 32,58 | 985 | 13 508 | 66,71 (63,52 a 69,15) | 97,3 |

Descartadas en `alta`: K3s 55, 53 y 48; MicroK8s 56, 65 y 123. En `media`, 0. Las figuras están en `analysis/salidas/2026-11-02_figuras/` (preliminar, una sesión; ver 9.6).

**Hallazgo que debe declararse: el nivel de potencia depende de la sesión.**

| Sesión | K3s idle / media / alta (W) | MicroK8s idle / media / alta (W) |
|---|---|---|
| 27-oct, pilotos (configuración inicial) | 4,894 / 6,212 / 6,792 | 5,867 / 7,206 / 7,775 |
| 27-oct, T-22 (una repetición) | 4,965 / 6,000 / 6,676 | 4,962 / 5,903 / 6,621 |
| 28-oct (3 repeticiones) | 4,158 / 4,955 / 5,553 | 4,157 / 4,964 / 5,608 |
| 2-nov (3 repeticiones) | 5,749 / 6,830 / 7,533 | 4,157 / 4,946 / 5,596 |

- **Medido.** El 2-nov, K3s consumió 1,59, 1,88 y 1,94 W más que MicroK8s en `idle`, `media` y `alta`, con utilización de CPU del host y de las VM similar entre ambas (la de K3s incluso menor). El 28-oct las dos distribuciones coincidían a ≈ 0,01 W. Entre el 28-oct y el 2-nov, MicroK8s se mantuvo (diferencias de ≤ 0,02 W) y K3s subió 1,59 a 1,98 W.
- **Medido.** El estado del host registrado antes de cada corrida fue igual (perfil `balanced`, boost 0, corriente alterna, gobernador `powersave`), salvo la temperatura de CPU de la primera corrida: 51,2 °C (K3s) frente a 44,8 °C (MicroK8s) del mismo día, y 47,5 °C en el 28-oct.
- **Interpretación (no probada).** No conozco la causa. Es compatible con efectos de la sesión que no controlo (hora del día, temperatura, tiempo encendido del equipo), pero no lo verifiqué. Consecuencia: la potencia de una distribución medida en una sesión no es comparable con la de la otra medida en otra, y los valores absolutos de la tabla no sirven para decidir cuál distribución consume menos. Lo que es robusto es el diseño de bloques intercalados de la campaña (HU-21), que mide ambas distribuciones dentro de la misma sesión.
- **Medido.** Latencia de `alta`: p95 de 8,36 ms en K3s (6,39 ms el 28-oct) y 66,7 ms en MicroK8s (45,0 ms el 28-oct), con la misma configuración. La latencia también cambió entre sesiones.

### 9.6 Figuras

| Archivo | Datos |
|---|---|
| `analysis/salidas/2026-11-02_figuras/figura_energia_latencia.pdf` | Pasada del 2-nov (9.5), ambas distribuciones |
| `analysis/salidas/2026-11-02_figuras/figura_cpu_ram.pdf` | Pasada del 2-nov (9.5) |
| `analysis/salidas/2026-11-02_figuras/figura_espectro_latencia.pdf` | Pasada del 2-nov, histogramas por corrida |
| `analysis/salidas/2026-11-02_figuras/figura_memoria_host.pdf` | Pasada del 2-nov, RSS de QEMU de 9.3 |
| `analysis/salidas/2026-11-02_figuras/figura_recuperacion.pdf` | 10 corridas con fallo del 2-nov (9.4) |
| `analysis/salidas/2026-11-02_<distribución>_control/` y `..._fallo/` | CSV y resúmenes de control y de recuperación por distribución |

Las figuras del 28-oct (`2026-10-28_configuracion_definitiva`) y de recuperación del 27-oct (`2026-10-27_recuperacion_definitiva`) no se mezclan con las del 2-nov: son sesiones distintas. Las revisé sobre una rasterización a 80 ppp.
