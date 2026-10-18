# data/

Salida experimental, versionada como respaldo para revisión.

| Carpeta | Contenido | Esquema de nombres |
|---|---|---|
| `prometheus-snapshots/` | Snapshots de la TSDB (`/api/v1/admin/tsdb/snapshot`), copiados fuera del directorio de datos de Prometheus | carpeta `<timestamp>-<id>` que genera Prometheus |
| `k6-resultados/` | `--out json` (comprimido) y resumen de cada ejecución de k6 | `<distribución>_<escenario>_r<NN>.json.gz` y `.resumen.json`; `r00` = prueba de humo |
| `metadatos/` | Ventana de la fase estable de cada repetición (distribución, escenario, repetición, `t_inicio`, `t_fin`) | `<distribución>_<escenario>_r<NN>.json` (lo escribirá T-32.1); los pilotos de T-17.4 usan `piloto_T-17.4_<distribución>.json` |

Campos de los metadatos de cada repetición (los escribirá T-32.1), además de los de `piloto_T-17.4_*.json`:

| Campo | Contenido |
|---|---|
| `nodo_vip_plano_control` | nodo que sostiene la `.100` al inicio y al fin de la repetición (lease `plndr-cp-lock`) |
| `nodo_vip_servicio` | nodo que sostiene la `.150` (anotación `kube-vip.io/vipHost` del Service `nginx-referencia`) |
| `nodo_pod` | nodo donde corre el pod `nginx-referencia` |

Motivo: con `svc_election: "false"` el titular de las VIP lo decide qué pod de kube-vip toma el *lease* primero, y cambió entre distribuciones (nodo 1 en K3s y nodo 3 en MicroK8s). Si el titular no es el nodo del pod, el tráfico hace un salto adicional por VXLAN; estos campos permiten revisarlo si una repetición se desvía.

`k6/correr.sh` imprime `t_inicio` y `t_fin` de la ejecución completa; la fase estable empieza `RAMPA_S` segundos después de `t_inicio`.
