# Evidencia T-22: validación preliminar integral (HU-22)

Estado al 27-oct-2026. Corrí la validación una vez en K3s y una vez en MicroK8s desde la consola de texto. Separo lo medido en esta validación, lo medido en tareas anteriores y lo que supongo. Son verificaciones de funcionamiento con una repetición por escenario: no comparo distribuciones ni saco conclusiones de energía de estos datos.

## 1. Alcance y estado

Criterio de HU-22: «Todos los componentes críticos validados antes de la campaña definitiva.»

| Tarea | Criterio | Qué cubre ya lo hecho | Qué falta | Estado |
|---|---|---|---|---|
| T-22.1 (OE1) | Se confirma estado operativo y recuperación básica | `evidencia_T-18.md`, `evidencia_T-19.md`, ciclos de `evidencia_T-20.md` (sección 8) | Hecho: construcción completa con la aplicación definitiva y comprobaciones de HA (sección 3) | Hecha en K3s y MicroK8s |
| T-22.2 (OE2) | Las cuatro fuentes de datos generan registros utilizables | T-20.3 (`evidencia_T-20.md`, 7.3) y T-21.1 (`evidencia_T-21.md`, sección 2) | Hecho: fuentes comprobadas con el orquestador actual y la aplicación definitiva (sección 4) | Hecha en K3s y MicroK8s |
| T-22.3 (OE2, OE3) | Escenario de resiliencia ejecutable y medible | `evidencia_T-19.md`: 5 corridas con fallo, aplicación estática, `500m`, 100 rps | Hecho: una corrida con fallo por distribución con el código nuevo y 450 rps (sección 5) | Hecha en K3s y MicroK8s |
| T-22.4 (OE1, OE2) | Memoria y swap del host monitoreados con el stack completo en carga alta, por distribución; asignación por nodo confirmada o ajustada | Memoria disponible al inicio de los pilotos del 27-oct, con la aplicación vieja (sección 6) | Hecho: memoria, swap y presión en las cuatro corridas por distribución (sección 6); con una incidencia de swap en MicroK8s | Hecha en K3s y MicroK8s |

## 2. El script de validación (`k6/operacion/validacion.py`)

Un script por distribución. Lo lanzo desde la raíz del repositorio, con el modo medición activo y la etiqueta de Prometheus de esa distribución:

```bash
python3 -m k6.operacion.validacion --distribucion <k3s|microk8s> --solo-precondiciones   # comprueba el host y sale
python3 -m k6.operacion.validacion --distribucion <k3s|microk8s>
```

Hace, en este orden, y se detiene en el primer paso que falla (sin reintentar y sin destruir el clúster, que queda arriba con el comando para destruirlo en el resumen):

| Paso | Qué hace | Tarea |
|---|---|---|
| 0 | Precondiciones del host: política y estado de medición (`estado_host`), sin `k6`, etiqueta de Prometheus igual a la distribución, sin clúster previo (ping a los nodos y a las dos VIP) | todas |
| 1 | `k6/operacion/despliegue.sh <distribución> construir <ciclo>`: Terraform, huellas y playbook del clúster, con la aplicación definida en `group_vars`; cronometra las fases en `data/despliegue/despliegue_<distribución>.jsonl` | T-22.1 |
| 2 | Comprobaciones: 3 nodos `Ready`; VIP del plano de control (`.100`) responde en el puerto de la API; VIP del servicio (`.150`) devuelve el SHA-256 esperado (calculado con las iteraciones y el límite de `group_vars`); titulares de las dos VIP y del pod determinados; si alguna falla, repite cada 5 s hasta 60 s (Prometheus puede tardar un scrape en ver lo recién desplegado) y registra intentos y espera; `Deployment` con límite y solicitud de CPU, imagen y réplica lista iguales a `group_vars` | T-22.1, T-22.2 |
| 3 | Cuatro corridas del orquestador con `--tipo verificacion`, `--estabilizacion 120` y una repetición: `idle`, `media` (450 rps), `alta` (900 rps) y `media` con `--fallo`. Tras cada una comprueba las fuentes, el estado del host y la memoria | T-22.2, T-22.3, T-22.4 |
| 4 | `k6/operacion/despliegue.sh <distribución> destruir <ciclo>` | T-22.1 |

**Qué registra.** Escribe en `data/verificacion/<fecha>_<distribución>_T-22/validacion/`: `validacion_<distribución>_<fecha>.json` (pasos, comprobaciones, fuentes, resumen de memoria y del fallo por corrida, incidencias), `memoria_<distribución>_<fecha>.json` (muestras crudas) y `orquestador_<escenario>.log`. Los metadatos de las corridas quedan en las subcarpetas habituales de la sesión. Un muestreador corre todo el script: memoria disponible, swap, `pswpin`/`pswpout` y presión de memoria (PSI) del host cada 5 s (solo lee `/proc`). La memoria y el swap de cada VM salen de Node Exporter, en la ventana de Prometheus que el orquestador exporta (resolución de 10 s), sin conectarse a las VM. Los resúmenes se calculan por corrida completa y por fase estable. Una primera versión muestreaba las VM por SSH cada 15 s; la quité tras la primera validación de K3s (sección 4, «Hallazgo»).

**Reglas.** Todo es `verificacion` y `valida_para_campana: false`; si una corrida saliera válida, el script se detiene. Los datos no sirven para comparar distribuciones ni para concluir diferencias de energía (el desfase de ≈ 1 W sigue abierto, `evidencia_T-20.md`, 7.4 punto 6).

**Qué verifiqué del script antes de correrlo** (sin clúster): autotest del resumen por ventana (mínimos y diferencias de contadores), de la conversión de CPU de Kubernetes, del SHA-256 esperado y del conteo de series; las precondiciones corren y rechazan el host actual (sesión gráfica abierta, boost encendido y etiqueta de Prometheus distinta); `fuentes()` con los metadatos y las ventanas de Prometheus de los pilotos del 27-oct (`alta` e `idle`), donde las cinco fuentes dieron utilizables; `resumen_fallo()` con una corrida de T-19; el muestreador en el host durante 9 s. El primer recorrido completo fue la validación de K3s (sección 3).

**Errores míos encontrados al preparar y al correr esto.** Al reorganizar `k6/` en subcarpetas dejé `k6/lib/fallo.py` apuntando a la ruta vieja de `fallo-controlado.sh`; la corrida con fallo habría fallado. Lo corregí. También `fuentes()` agrupaba kube-state-metrics por `instance` (igual para todos los nodos) y contaba un nodo en vez de tres; lo vi al probarla con datos reales y lo corregí. El tercero apareció en la validación de K3s: el muestreo por SSH de las VM perturbó a k6 (sección 4).

## 3. T-22.1: infraestructura y HA de ambos clústeres

**Criterio:** «Se confirma estado operativo y recuperación básica.»

**Evidencia previa.**
- Estado operativo y VIP: `evidencia_T-18.md` (aplicación de referencia, `LoadBalancer` en `.150` con kube-vip).
- Recuperación básica: `evidencia_T-19.md`, sección 2.4: en 4 de las 5 corridas la VIP migró entre 16,7 y 22,7 s tras el fallo (sin dispersión calculada).
- Construcción y destrucción: `evidencia_T-20.md`, sección 8 (K3s ciclo 6: 608,9 s; MicroK8s ciclo 5: 1188,1 s). Esos ciclos no eran «sin ajustes»: el de K3s fue exploratorio con el pod en `2000m` y MicroK8s se construyó con el límite en `500m` y lo corregí a mano con `kubectl`.

**Qué corrí.** Pasos 1, 2 y 4 del script, una vez por distribución (sesiones `2026-10-27_k3s_T-22` y `2026-10-27_microk8s_T-22`), con el modo medición activo y la aplicación definitiva (SHA-256 con 300 iteraciones, límite `2000m`, solicitud `500m`).

**Medido.**

| | K3s (ciclo 7) | MicroK8s (ciclo 6) |
|---|---|---|
| Construcción total | 410,6 s | 952,0 s |
| Terraform / huellas / Ansible | 44,9 / 13,4 / 352,3 s | 41,7 / 11,9 / 898,4 s |
| `rc` de `despliegue.sh construir` | 0 | 0 |
| Comprobaciones de HA | pasaron al primer intento, en 1,5 s | pasaron al primer intento, en 1,9 s |
| Nodos `Ready` | 3 de 3 | 3 de 3 |
| VIP del plano de control `.100` | responde (HTTP 401 en `/healthz`, sin credenciales) | responde (HTTP 401) |
| VIP del servicio `.150` | devuelve el SHA-256 esperado (300 iteraciones) | devuelve el SHA-256 esperado |
| Titulares `.100` / `.150` / pod | `k3s-node1` / `k3s-node1` / `k3s-node2` | `microk8s-node1` / `microk8s-node1` / `microk8s-node2` |
| Límite / solicitud de CPU, réplicas listas | 2 (= `2000m`) / `500m`, 1 | 2 (= `2000m`) / `500m`, 1 |
| Destrucción | 6,5 s (`rc` 0) | 6,8 s (`rc` 0) |
| Duración total del script | 1926 s (32 min) | 2460 s (41 min) |

La recuperación básica se ejercitó en la corrida con fallo de cada distribución (sección 5).

**Ajustes manuales.** El script no ejecutó ninguno: construyó con `despliegue.sh` y ambos `construir` terminaron con `rc` 0. Confirmo que no intervine durante las ejecuciones: solo lancé el script y lo dejé correr.

**Supongo** que `despliegue.sh construir` con `rc` 0 y sin intervención equivale a «sin ajustes manuales».

**Límites.** Una construcción por distribución, sin dispersión de los tiempos. Los tiempos difieren de los ciclos anteriores (K3s 410,6 s frente a 608,9 s; MicroK8s 952,0 s frente a 1188,1 s) y no investigué por qué; ningún ciclo anterior es comparable en condiciones (arriba). El `401` de la API significa que el servidor responde; no comprueba que el plano de control acepte operaciones, eso lo cubre `kubectl get nodes` por SSH. Los tiempos de construcción de ambas distribuciones no son una comparación entre ellas.

**Estado propuesto:** Realizado.

## 4. T-22.2: observabilidad de energía, recursos y rendimiento

**Criterio:** «Las cuatro fuentes de datos generan registros utilizables.»

**Evidencia previa.** T-20.3 (`evidencia_T-20.md`, 7.3): sincronía de Scaphandre, Prometheus y k6. T-21.1 (`evidencia_T-21.md`, sección 2): 18 muestras por ventana de 180 s en todas las series, con intervalos de 9,997 a 10,003 s.

**Cómo defino «utilizable»** (criterio mío, no derivado de una prueba): la fuente tiene registros en la ventana exportada y al menos el 90 % de las muestras esperadas (ventana / 10 s).

| Fuente | Qué compruebo |
|---|---|
| RAPL | `delta_uj` positivo en la fase estable (se registra también si hubo desbordamiento) |
| Scaphandre | `scaph_host_energy_microjoules` con muestras suficientes |
| Node Exporter | `node_memory_MemAvailable_bytes` del host y de las 3 VM con muestras suficientes |
| kube-state-metrics | `kube_node_status_condition` de los 3 nodos y `kube_pod_status_ready` del pod de NGINX con muestras suficientes |
| k6 | código de salida 0, JSON no vacío y, en `media` y `alta`, al menos el 90 % de los segundos de la fase estable con datos |

**Medido.** En las 8 corridas (4 por distribución) las cinco fuentes salieron utilizables: RAPL con `delta_uj` positivo y sin desbordamiento, Scaphandre y kube-state-metrics con 27 o 28 muestras de 27 esperadas, Node Exporter con 27 o 28 en el host y en las 3 VM, y k6 con código de salida 0 y 181 segundos de datos en `media`, `alta` y fallo. La tasa aplicada en la fase estable fue de 450,0 rps en `media` de ambas distribuciones; en `alta`, 888,5 rps en K3s y 899,5 rps en MicroK8s.

| Corrida | K3s: descartadas | MicroK8s: descartadas |
|---|---|---|
| `media` | 0 | 0 |
| `alta` | 2037 | 85 |
| `media` con fallo | 1 | 20 |

**Hallazgo: mi muestreo por SSH perturbó a k6 en la `alta` de K3s.** La primera versión del script leía la memoria de las 3 VM por SSH cada 15 s. En `alta` de K3s, los segundos con iteraciones descartadas fueron 3, 18, 34, 48, 63, 78, 93, 109, 123, 139, 154 y 168 de la fase estable, y las lecturas por SSH cayeron en 3,1; 18,1; 33,9; 48,1; 63,1; 78,1; 93,1; 108,7; 123,1; 138,2; 153,1 y 168,1 s: coinciden las 12. En esos segundos el p95 de k6 subió a 210–470 ms (mediana de la fase 8,8 ms). Por eso la tasa aplicada de 888,5 rps y los 2037 descartes de K3s no describen a K3s: son efecto de mi instrumento. En la calibración (sin ese muestreo) K3s aplicó 893,8 rps en el escalón de 900 con 0 descartes.
- Lo quité: la memoria de las VM sale ahora de Node Exporter, y el muestreo del host solo lee `/proc`. MicroK8s se corrió con la versión corregida; K3s, con la primera.
- En la `alta` de MicroK8s hubo 85 descartes en 7 segundos (15, 25, 35, 45, 54, 55 y 134 s; p95 máximo 141 ms). Hay una periodicidad de ≈ 10 s en cinco de ellos que coincide con el intervalo de scrape de Prometheus; **no lo verifiqué**. Que la corrección sea la causa de que MicroK8s tenga menos descartes que K3s no se puede afirmar: son distribuciones distintas y no repetí la `alta` de K3s.
- Consecuencia: la `alta` de K3s de esta validación sirve para el criterio de «registros utilizables», no para latencia ni para tasa aplicada. No la repetí.

**Dos fallas de muestreo en K3s** (`memoria_errores_muestreo` = 2): no identifiqué en qué momento. En MicroK8s fueron 0.

**Desviación a resolver:** el criterio de la hoja dice «cuatro fuentes» y comprobé cinco; las cuento por separado. Las agrupo en cuatro así: energía (RAPL y Scaphandre), recursos (Node Exporter), estado de Kubernetes (kube-state-metrics) y rendimiento (k6). Las cinco salieron utilizables, así que el criterio se cumple con cualquier agrupación.

**Qué supongo:** que el 90 % es un umbral razonable; que 27 o 28 muestras de 27 esperadas en la ventana exportada bastan para un análisis posterior.

**Límites.** Una repetición por escenario. No comparé la potencia entre distribuciones. La comprobación de las fuentes mira presencia y cantidad de muestras, no su exactitud (la sincronía la cubre T-20.3).

**Estado propuesto:** Realizado.

## 5. T-22.3: protocolo de fallo y recuperación

**Criterio:** «Escenario de resiliencia ejecutable y medible.»

**Evidencia previa.** `evidencia_T-19.md`: 5 corridas con fallo (3 en K3s, 2 en MicroK8s), aplicación estática, `500m`, 100 rps; `SIGKILL` al proceso de orquestación del nodo que sostiene las VIP, con retención de 90 o 120 s según la corrida.

**Qué corrí.** Una corrida `media` con `--fallo` por distribución (450 rps, retención de 120 s, `--fallo-en` 30 s), con el código reorganizado y la aplicación definitiva. En ambas el nodo fallado fue el de `node1` y el pod estaba en `node2`, así que el orquestador no lo movió (`pod_movido` = null).

**Medido** (segundos desde `t_fallo`; cota de `t_fallo` 0,86 s en K3s y 0,79 s en MicroK8s):

| | K3s | MicroK8s |
|---|---|---|
| API por la VIP `.100` sin respuesta | 1,1 a 19,2 s | 1,2 a 19,3 s |
| Titular de `.100` (antes → después) | `node1` → `node2` a 18,2 s | `node1` → `node3` a 18,3 s |
| Titular de `.150` (antes → después) | `node1` → `node2` a 18,2 s | `node1` → `node2` a 18,3 s |
| App por la VIP `.150` sin respuesta | ningún intervalo | ningún intervalo |
| Nodo `NotReady` según `kubectl` | 67,7 a 131,8 s | 117,2 a 129,3 s |
| Nodo `NotReady` según kube-state-metrics | 74,1 a 144,1 s | 124,2 a 134,2 s |
| Solicitudes fallidas de k6 | 0 (de 73 899 al final) | 0 (de 73 925) |
| Nodo `Ready` al final | sí | sí |

El procedimiento corrió de principio a fin con el código nuevo en ambas distribuciones y produjo el análisis: es ejecutable y medible. Contra T-19: la migración de las VIP a 18,2 y 18,3 s cae dentro de 16,7 a 22,7 s; la detección de MicroK8s (117,2 s) queda por encima de lo registrado en T-19 (51,7 a 111,9 s), con una sola corrida no puedo decir si es variabilidad.

**Qué supongo:** que lo medido con la aplicación definitiva es comparable en forma, no en valor, con T-19. En MicroK8s las dos VIP quedaron en nodos distintos tras el fallo (`.100` en `node3`, `.150` en `node2`); ya había ocurrido en una corrida de K3s de T-19 y no lo investigué de nuevo.

**Límites.** Un solo fallo por distribución y un solo modo (`SIGKILL` del proceso); no estima variabilidad. Apagado de VM, corte de red y más de un fallo quedan para la etapa siguiente. Como el pod no estaba en el nodo fallado, esta corrida no mide el efecto de perder el nodo de la aplicación sobre las solicitudes.

**Estado propuesto:** Realizado.

## 6. T-22.4: reserva de recursos del host (memoria y swap)

**Criterio:** «Memoria y swap del host monitoreados con el stack completo en carga alta, de forma independiente para K3s y MicroK8s; asignación por nodo confirmada o ajustada.»

**Evidencia previa** (aplicación vieja, solo al inicio de cada corrida): memoria disponible del host entre 5632 y 6139 MB en K3s y entre 1519 y 1776 MB en MicroK8s en los 9 pilotos de cada una del 27-oct. Presión `some avg60` de 0,00 en las 18.

**Qué corrí.** Las cuatro corridas por distribución con el muestreo de memoria del host cada 5 s. El umbral de 1024 MB es el de `estado_host.MEM_MIN_MB`, un valor mío sin derivar de una prueba.

**Medido.** Host (mínimo de `MemAvailable` durante la corrida completa; entre paréntesis, margen sobre 1024 MB):

| Corrida | K3s | MicroK8s |
|---|---|---|
| `idle` | 6195 MB (5171) | 1576 MB (552) |
| `media` | 6131 MB (5107) | 1482 MB (458) |
| `alta` | 6061 MB (5037) | 1430 MB (406) |
| `media` con fallo | 5782 MB (4758) | 1420 MB (396) |

Swap y presión del host:

| | K3s | MicroK8s |
|---|---|---|
| `SwapFree` mínimo en las corridas | 2048 de 2048 MB | 1988 de 2048 MB |
| `pswpin` / `pswpout` (páginas) en `idle` | 0 / 0 | +382 / +245 |
| ... en `media` | 0 / 0 | +31 / +1691 |
| ... en `alta` | 0 / 0 | +53 / +2048 |
| ... en `media` con fallo | 0 / 0 | +25 / 0 |
| PSI `some avg10` máximo | 0,18 (en la corrida con fallo) | 0,51 (en `idle`, completa) y 0,0 en las demás |

En la fase estable de `alta`, MicroK8s tuvo +32 / +1024 páginas. Si la página es de 4 kB (supuesto estándar de x86-64, no lo verifiqué), +2048 páginas son ≈ 8 MB. Durante la construcción de MicroK8s el host sacó a swap ≈ 79 MB (`SwapFree` de 2047 a 1968 MB entre dos muestras de 5 s, con picos de hasta 12 472 páginas por muestra); K3s no usó swap en las corridas.

Dentro de las VM (mínimo de `MemAvailable` de 4096 MB asignados, desde Node Exporter, `alta`): K3s 2925 / 3101 / 3125 MB; MicroK8s 2819 / 2956 / 2989 MB. En la corrida con fallo: K3s 2749 / 2904 / 3069 MB y MicroK8s 2814 / 2960 / 2949 MB. Ninguna VM usó swap.

**Incidencia (swap).** En las cuatro corridas de MicroK8s el host registró actividad de swap. Según lo acordado, la registro y no ajusto nada: `SwapFree` quedó en ≥ 1988 MB (de 2048), la presión PSI fue ≈ 0 en las corridas y no hubo aborto ni memoria bajo 1024 MB.

**Asignación de 4096 MB por nodo.**
- **K3s:** se confirma. El host nunca bajó de 5782 MB disponibles, sin swap, y las VM conservaron ≥ 2749 MB disponibles.
- **MicroK8s:** la confirmo en 4096 MB (decisión del 27-oct), con un riesgo declarado. El margen mínimo sobre 1024 MB fue de 396 MB, hubo swap pequeño y las VM tenían ≥ 2814 MB disponibles. Ningún dato cruza un umbral que yo haya fijado antes, así que la regla acordada (no cambiar la memoria salvo que T-22.4 lo exija) no obliga a cambiarla. Ajustar a menos de 4096 MB en ambas distribuciones habría dado más margen al host, pero cambia una decisión cerrada de la Etapa 2 y obliga a repetir las validaciones; los datos no lo exigen, así que lo descarté.

**Sin explicar.** El host tiene ≈ 4,5 GB menos de memoria disponible con MicroK8s que con K3s (≈ 1,4 frente a ≈ 6,0 GB), y la memoria disponible dentro de las VM es parecida (≈ 2,8 a 3,1 GB). Una hipótesis **no verificada**: la memoria que el invitado tocó durante la construcción (descarga e instalación de snaps, caché) queda residente en el host, sin devolverse, y la construcción de MicroK8s es más pesada (898,4 s de Ansible frente a 352,3 s). Se puede probar leyendo el RSS de cada proceso QEMU en la siguiente etapa.

**Límites.** Una repetición por escenario. El mínimo de memoria depende del muestreo de 5 s: puede perderse un valle más corto. Los resúmenes de memoria del host y de las VM de K3s salen de la primera versión del script (VM por SSH en el JSON de K3s, mínimos de 2906 a 3122 MB, consistentes con los de Node Exporter); los de las tablas de arriba son de Node Exporter. El orquestador no corta una corrida por memoria; el script comprueba después de cada una (sección 7).

**Estado propuesto:** Realizado: asignación de 4096 MB por nodo confirmada en ambas distribuciones, con la incidencia de swap y el margen de MicroK8s declarados.

## 7. Desviaciones respecto de lo planificado

1. **El orquestador no aborta por memoria.** `estado_host` solo comprueba `MemAvailable` ≥ 1024 MB una vez, al inicio, y lo registra en `motivos_no_valida`; no corta la corrida. La comprobación durante la corrida está en el script de validación y es posterior a cada corrida. No lo cambié en el orquestador para no tocarlo antes de la campaña. En MicroK8s, con un margen mínimo de 396 MB, esto importa para la campaña.
2. **El swap del host no empieza en cero.** Había ≈ 64 MB en uso antes de empezar. «Usa swap» lo definí por el aumento de `pswpin`/`pswpout` o la baja de `SwapFree` dentro de la corrida, no por el valor absoluto. Con esa definición K3s no tuvo incidencias y MicroK8s sí (sección 6).
3. **«Cuatro fuentes» frente a cinco comprobadas** (sección 4): las agrupé en cuatro; el resultado no depende de la agrupación.
4. **Orden del trabajo del host.** El playbook de la etiqueta de Prometheus pide contraseña y no lo puede lanzar el script; se corre antes, y tras él hay que repetir `salir` y `entrar`. El script comprueba la etiqueta en el paso 0.
5. **Una repetición.** Cada escenario se corrió una vez y el fallo una vez por distribución, como se pidió; no hay variabilidad estimable.
6. **K3s y MicroK8s no corrieron la misma versión del script.** K3s con la memoria de las VM por SSH (que perturbó la `alta`); MicroK8s con la lectura por Node Exporter (sección 4).
7. **Estimaciones de tiempo.** Calculé 40 a 45 min para K3s y 50 a 55 min para MicroK8s; salieron 32 y 41 min. Las corridas duraron entre 366 y 382 s cada una.

## 8. Cómo se ejecuta y qué devolví

Una distribución a la vez, con Claude Code cerrado y en la consola de texto, después del playbook de la etiqueta (`-e active_distribution=<dist>`) y de `salir` y `entrar`: `python3 -m k6.operacion.validacion --distribucion <dist> --solo-precondiciones` (≈ 6,4 s) y luego el mismo comando sin el flag. Al terminar, `salir`. Si el script se detiene, el clúster queda arriba y el resumen indica el comando para destruirlo.

Archivos: `data/verificacion/2026-10-27_k3s_T-22/` y `data/verificacion/2026-10-27_microk8s_T-22/` (≈ 0,7 MB cada una) y las líneas de los ciclos 7 (K3s) y 6 (MicroK8s) de `data/despliegue/despliegue_<distribución>.jsonl`. El JSON crudo de k6 queda fuera del repositorio.

## 9. Pendiente

- Investigar en la etapa siguiente por qué MicroK8s deja al host con menos memoria (RSS de QEMU), qué proceso sacó a swap y si la campaña de 96 corridas mantiene el margen sobre 1024 MB.
- Repetir la `alta` de K3s sin el muestreo por SSH solo si se necesita una lectura limpia de latencia; la validación no la exige.
- Horas reales de T-22.1 a T-22.4: las ingreso yo en la hoja; no las estimo aquí.
- Fuera de esta evidencia, hasta la etapa siguiente: campaña, pruebas estadísticas, `plan-campana-v1`, diagnóstico del desfase de ≈ 1 W, `emulatorpin`, pilotos de energía con la aplicación definitiva (T-24.4 a), otros modos de fallo y cambios de umbrales, tasas, N de SHA-256 o memoria por nodo.
