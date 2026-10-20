# data/

Salida experimental, versionada como respaldo para revisión.

| Carpeta | Contenido | Esquema de nombres |
|---|---|---|
| `prometheus-snapshots/` | Snapshots de la TSDB (`/api/v1/admin/tsdb/snapshot`), copiados fuera del directorio de datos de Prometheus | carpeta `<timestamp>-<id>` que genera Prometheus |
| `k6-resultados/` | `--out json` (comprimido) y resumen de cada ejecución de k6 | `<distribución>_<escenario>_r<NN>.json.gz` y `.resumen.json`; `r00` = prueba de humo |
| `metadatos/` | Ventana de la fase estable de cada repetición (distribución, escenario, repetición, `t_inicio`, `t_fin`) | `<distribución>_<escenario>_r<NN>.json`, escrito por `k6/orquestador.py` (T-32.1); con fallo controlado el escenario se nombra `media-fallo` (`<distribución>_media-fallo_r<NN>.json`) y se agrega `<...>.observador.json.gz` con las muestras del host; las verificaciones del orquestador llevan el prefijo `verif_` y los pilotos de T-17.4 usan `piloto_T-17.4_<distribución>.json` |

Campos de los metadatos de cada repetición (los escribe `k6/orquestador.py`; esquema `1`), además de los de `piloto_T-17.4_*.json`. `t_inicio` y `t_fin` delimitan la fase estable (puntos medios de las dos lecturas de RAPL); `t_ejecucion_inicio` y `t_ejecucion_fin`, la ejecución completa de k6:

| Campo | Contenido |
|---|---|
| `nodo_vip_plano_control` | nodo que sostiene la `.100` al inicio y al fin de la repetición (lease `plndr-cp-lock`) |
| `nodo_vip_servicio` | nodo que sostiene la `.150` (anotación `kube-vip.io/vipHost` del Service `nginx-referencia`) |
| `nodo_pod` | nodo donde corre el pod `nginx-referencia` |
| `titulares.inicio`, `titulares.fin`, `titulares.cambiaron`, `titulares.metodo` | los tres campos anteriores al inicio y al fin; `no determinado` si la MAC que ve el host no calza con exactamente un nodo |
| `rapl` | `energy_uj` crudo al inicio y al fin de la fase estable, `max_energy_range_uj`, `desbordamiento`, `delta_uj` y `potencia_media_W` (dominio `package-0`) |
| `parametros`, `verificacion` | tasa, fases, `pre_vus`, `max_vus`, espera de estabilización y si la ejecución es una verificación |
| `k6` | código de salida, CPU, rutas de los archivos, `tamano_json_bytes`, hora del primer punto del JSON y versión |
| `reloj_antes` | `chronyc tracking` del host y de cada VM justo antes de lanzar k6 (`Stratum`, `System time`, `Last offset`) |
| `fallo` | solo con `--fallo`: nodo fallado, `pod_movido`, `reinicios_kube_vip`, `parametros_efectivos` (argumentos explícitos de detección y tolerancias del pod), `eventos` (marcas de inyección, restauración y estado final) y `analisis` (caídas de la API por la `.100` y de la app por la `.150`, cambios de titular de cada VIP, `NotReady` visto por `kubectl` y por `kube-state-metrics`, leases y solicitudes fallidas de k6 antes y después del fallo) |
| `snapshot` | nombre del snapshot de Prometheus y si se copió a `prometheus-snapshots/` |

Motivo: con `svc_election: "false"` el titular de las VIP lo decide qué pod de kube-vip toma el *lease* primero, y cambió entre corridas de MicroK8s (nodo 1 en la primera, con kube-vip `v0.8.9`, y nodo 3 en la segunda, con `v1.2.4`); en K3s fue el nodo 1 en esas dos corridas (`docs/evidencia/evidencia_T-18.md`, secciones 2.4 y 2.7). Si el titular no es el nodo del pod, el tráfico hace un salto adicional por VXLAN; estos campos permiten revisarlo si una repetición se desvía.

`k6/correr.sh` imprime `t_inicio` y `t_fin` de la ejecución completa; la fase estable empieza `RAMPA_S` segundos después de `t_inicio`.

## Tamaño esperado por repetición

- JSON de k6 (`.json.gz`): unos 144 B por solicitud en el peor caso medido (133 a 144 B en cuatro corridas de humo de 50 solicitudes por segundo o menos). Con la ventana de 210 s equivalentes (15 s de rampa, 180 s estables, 15 s de descenso): unos 61 MB a 2000 solicitudes por segundo, 91 MB a 3000 y 151 MB a 5000. Sobre unos 3300 solicitudes por segundo un archivo supera los 100 MB que GitHub admite. Es una extrapolación; no la verifiqué a esas tasas, y la tasa de saturación aún no está calibrada (T-20.5).
- `k6/orquestador.py` avisa por stderr si la estimación previa o el tamaño real pasa del 80 % de 100 MB, y guarda el tamaño real en `k6.tamano_json_bytes`.
- Snapshot de Prometheus: copia completa de la TSDB. Crece con el tiempo (2,1, 2,7 y 5,2 MB en tres snapshots consecutivos observados), por lo que un snapshot por repetición duplica el historial en el repositorio.
- Metadatos y resumen de k6: unos 2 kB y 1 a 4 kB.
