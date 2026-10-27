# data/

Resultados del laboratorio, versionados como respaldo. El JSON crudo de k6 no se versiona.

## Estructura

```
data/
├── calibracion/<fecha>_<distribución>/     calib_<distribución>_<fecha>.json (una por calibración)
├── pilotos/<fecha>_<distribución>/         una carpeta por secuencia de pilotos
├── campana/plan_campana_v1.json            plan de la campaña (borrador sin fijar; lo genera k6/medicion/plan_campana.py)
├── campana/<sesión>/                       corridas definitivas (aún no hay)
├── verificacion/<fecha>_<distribución>/    verificaciones del orquestador, fallos controlados y pilotos de T-17.4
│     cada carpeta de sesión lleva:  k6-resultados/  metadatos/  prometheus-ventanas/
├── exploratorio/<fecha>_<distribución>[_nota]/   corridas con otra política (boost encendido) o de sesiones previas;
│                                                 mismas subcarpetas, se citan en la evidencia pero no son resultados
├── reposo/                                 potencia del host sin VMs (reposo_host_s<NN>.json)
├── despliegue/                             tiempos de construcción y destrucción (despliegue_<distribución>.jsonl)
├── humo/                                   pruebas de humo de k6 (k6/medicion/correr.sh)
├── diagnostico/<fecha>/                    salidas de k6/diagnostico/diagnostico_desfase.py (T-24.4)
├── prometheus-snapshots/                   snapshots de la TSDB copiados con --copiar-snapshot
└── k6-crudo/<tipo>/<sesión>/               JSON crudo de k6, ignorado por git
```

La sesión por defecto es la fecha local y la distribución (`2026-10-27_k3s`); `k6/medicion/orquestador.py --sesion` la cambia y `k6/medicion/secuencia_piloto.sh` la fija una vez para toda la secuencia.

## Contenido de una sesión

| Carpeta | Archivos |
|---|---|
| `k6-resultados/` | `<base>.por_segundo.json.gz` (`t`, `solicitudes`, `fallidas`, `descartadas`, `p50_ms`, `p95_ms`, `p99_ms`, `max_ms`) y `<base>.resumen.json` |
| `metadatos/` | `<base>.json` con la ventana estable y el contexto de la medición; con fallo controlado, además `<base>.observador.json.gz` con las muestras del host |
| `prometheus-ventanas/` | `<base>.json.gz`: muestras de Prometheus de la ventana (host, VMs, Scaphandre, kube-state-metrics) |

`<base>` es `<prefijo><distribución>_<escenario>_r<NN>`. El prefijo es `piloto_` o `verif_`; las corridas definitivas no llevan. Con fallo controlado el escenario es `media-fallo`. El `sha256` del crudo queda en los metadatos.

Los snapshots de Prometheus son acumulativos: cada uno contiene a los anteriores, así que se conserva el último de cada bloque.

## Metadatos de una repetición

Los escribe `k6/medicion/orquestador.py`. Las rutas que contienen apuntan a esta misma estructura.

| Campo | Contenido |
|---|---|
| `t_inicio`, `t_fin` | fase estable (punto medio de las dos lecturas de RAPL); `t_ejecucion_*` es la ejecución completa de k6 |
| `parametros` | tasa, fases, `pre_vus`, `max_vus`, espera de estabilización |
| `tipo`, `valida_para_campana`, `motivos_no_valida` | `definitiva`, `piloto`, `calibracion` o `verificacion`; solo una corrida `definitiva` con el host dentro de la política es válida para la campaña |
| `rapl` | `energy_uj` al inicio y fin, `max_energy_range_uj`, `desbordamiento`, `delta_uj`, `potencia_media_W` (`package-0`) |
| `estado_host`, `reloj_antes`, `reloj_espera_s` | estado frente a la política de medición y `chronyc tracking` del host y las VMs; el orquestador aborta si el reloj no converge |
| `nodo_vip_plano_control`, `nodo_vip_servicio`, `nodo_pod`, `titulares` | quién sostiene la `.100` y la `.150` y dónde corre NGINX, al inicio y al fin |
| `k6` | código de salida, CPU, `sha256_json`, rutas de los archivos, tamaño del crudo, versión |
| `ventana_prometheus`, `snapshot` | archivo de la ventana y snapshot copiado (si hubo) |
| `fallo` | solo con `--fallo`: nodo fallado, eventos, reinicios de kube-vip y análisis de caídas y migración de las VIP |

## Tamaño

El crudo de k6 pesa hasta ~144 B por solicitud; sobre unos 3300 rps en la fase estable un archivo superaría los 100 MB que admite GitHub (extrapolación, no verificada a esas tasas). El orquestador avisa al llegar al 80 % de ese límite. Un snapshot de Prometheus es una copia completa de la TSDB y crece con el tiempo, por eso se copia solo cuando se pide.
