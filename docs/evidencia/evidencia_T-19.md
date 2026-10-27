# Evidencia de HU-19 (T-19.1 a T-19.5) y cierre de T-32.1: fallo controlado de un nodo y migración de la VIP

Fechas: 19 y 20 de octubre de 2026. Las salidas provienen de mi terminal en el host (ThinkPad). Probé un clúster a la vez: K3s, que destruí antes de levantar MicroK8s. Todas las ejecuciones son **verificaciones del procedimiento, no pilotos ni mediciones experimentales**: la tasa de carga (100 solicitudes por segundo) es provisional hasta T-20.5, los tiempos de inyección y retención son provisionales y se hicieron con la sesión gráfica abierta. T-20.5 es posterior a este trabajo.

Convención: la sección 2 contiene hechos medidos u observados; la 3, interpretaciones no verificadas; la 4, decisiones, hallazgos y desviaciones; la 5, limitaciones; la 6, lo pendiente; la 7, los archivos asociados; la 8, el criterio de aceptación.

## 1. Alcance y condiciones

| Parámetro | Valor |
|---|---|
| Tareas cubiertas | T-19.1 (script de fallo), T-19.2 (marcas de inicio, detección y recuperación), T-19.3 (solicitudes afectadas con k6), T-19.4 (ubicación del pod y parámetros de detección y tolerancia), T-19.5 (revalidación de la migración de la VIP con kube-vip v1.2.4) y la repetición completa de T-32.1 |
| Fuera de alcance | calibración de la tasa de carga media (T-20.5), caracterización del reposo del host (T-20.7), ejecuciones definitivas de resiliencia (HU-25) |
| Protocolo base | Etapa 2, sección 4.4: `SIGKILL` al proceso de orquestación del nodo titular de la VIP, durante la fase estable de la carga media, un solo nodo de los tres |
| Clústeres | K3s `v1.36.3+k3s1` y MicroK8s `v1.36.2` (canal `1.36/stable`), kube-vip `v1.2.4` |
| Red | VMs `192.168.100.11` a `.13`, VIP del plano de control `.100`, VIP del Service `.150`, host `.1` |
| Carga | k6 `v2.3.0` en el host, `ramping-arrival-rate`, 100 solicitudes por segundo, fases de 30 s, 180 s y 30 s (≈ 21 000 solicitudes por corrida) |
| Reloj | `chronyc tracking` registrado antes de cada corrida en los metadatos; ver 2.7 |

## 2. Hechos medidos u observados

### 2.1 El `SIGKILL` tal como está escrito no ejercita el fallo (K3s)

Observación de una exploración con scripts de apoyo que **no versioné**, en un clúster K3s con la configuración original de kube-vip:

- `systemctl show k3s` indica `Restart=always`, `RestartUSec=5s` y `KillMode=process` en los tres nodos.
- Tras `SIGKILL`, systemd reinicia `k3s` a los 5 s; la unidad volvió a `active` a los ≈ 13 s. El nodo **nunca pasó a `NotReady`**, la `.150` respondió `200` todo el tiempo y la `.100` devolvió errores de conexión durante ≈ 9 s (hasta ≈ 5 s `URLError`, luego `503`).
- La VIP **no migró**: el titular siguió siendo el mismo nodo.
- `sudo systemctl kill -s SIGKILL k3s` (la orden literal del protocolo) mata el proceso principal pero devuelve `Failed to send signal SIGKILL to auxiliary processes: Invalid argument`, por el `KillMode=process`. Con `--kill-whom=main` no hay error.
- MicroK8s: `snap.microk8s.daemon-kubelite` tiene `Restart=on-failure`, `RestartUSec=100ms` y `KillMode=control-group`.

### 2.2 Con el proceso caído, la VIP no migraba (configuración original de kube-vip)

Para que el fallo exista dejo el proceso caído mientras dura la retención (un archivo temporal en `/run/systemd/system/<unidad>.service.d/` con `Restart=no`, que se quita al restaurar). En la exploración (75 s y 110 s de retención, no versionada) y en la corrida versionada `verif_k3s_media-fallo_r01`:

- El **lease `plndr-cp-lock` siguió renovándose cada ≈ 10 s** mientras `k3s` estaba caído en el titular; el titular de ambas VIP no cambió.
- La API por la `.100` estuvo caída todo el tiempo que el proceso estuvo muerto (0,7 s a 93,7 s del fallo en `r01`); la app por la `.150` no registró errores (0 solicitudes fallidas de 20 999).
- El nodo pasó a `NotReady` a los 51,7 s según `kubectl` y a los 64,7 s según `kube-state-metrics`, y volvió a `Ready` a los ≈ 98 s.

### 2.3 Cambio en kube-vip para que la VIP migre

El manifiesto de kube-vip (idéntico en ambas distribuciones) no montaba ningún kubeconfig: usaba la configuración dentro del clúster, así que el pod del nodo caído seguía llegando a la API por la IP del Service (las reglas de iptables persisten aunque el proceso muera) y renovaba su lease. Agregué a las dos plantillas:

```
KUBERNETES_SERVICE_HOST=127.0.0.1
KUBERNETES_SERVICE_PORT={{ kube_vip_port }}
```

Con eso la elección de líder usa el apiserver del propio nodo (6443 en K3s, 16443 en MicroK8s). Es el acoplamiento que describe el diseño de la Etapa 2.

### 2.4 Corridas con fallo (configuración nueva)

Todas con `--verificacion`, 100 solicitudes por segundo y 20 999 solicitudes de k6. `r03` de K3s se repitió después, con los mismos valores provisionales que `r03` de MicroK8s y con la captura de parámetros corregida (2.6). Los tiempos son segundos desde `t_fallo` (marca del script, cota de ± 0,2 a 0,35 s). Resolución: 1 s (host), 2 s (`kubectl`) y 10 s (`kube-state-metrics`).

| Corrida | Configuración de kube-vip | Nodo fallado | Inyección / retención | API por `.100` caída | Titular `.100` | Titular `.150` | `NotReady` por `kubectl` (hasta) | `NotReady` por `ksm` (hasta) | Reelección del `kube-controller-manager` |
|---|---|---|---|---|---|---|---|---|---|
| `verif_k3s_media-fallo_r01` | original | `k3s-node2` | +40 s / 90 s | 0,7 a 93,7 s | no cambió | no cambió | 51,7 s (97,7 s) | 64,7 s (104,7 s) | el líder estaba en otro nodo |
| `verif_k3s_media-fallo_r02` | nueva | `k3s-node3` | +40 s / 90 s | 0,6 a 19,7 s | `node3` → `node2` a 18,7 s | `node3` → `node1` a 16,7 s | 69,6 s (97,6 s) | 79,6 s (99,6 s) | `node3` → `node1` a 17,6 s |
| `verif_microk8s_media-fallo_r02` | nueva | `microk8s-node1` | +40 s / 90 s | 0,7 a 21,7 s | `node1` → `node2` a 20,7 s | `node1` → `node2` a 17,7 s | 96,1 s (106,1 s) | 99,6 s (109,6 s) | `node1` → `node2` a 60,1 s |
| `verif_microk8s_media-fallo_r03` | nueva | `microk8s-node2` | +30 s / 120 s | 0,7 a 21,7 s | `node2` → `node3` a 20,7 s | `node2` → `node3` a 17,7 s | 111,9 s (125,9 s) | 119,7 s (129,7 s) | `node2` → `node3` a 61,9 s |
| `verif_k3s_media-fallo_r03` | nueva | `k3s-node1` | +30 s / 120 s | 0,6 a 23,7 s | `node1` → `node2` a 22,7 s | `node1` → `node2` a 22,7 s | 74,0 s (128,0 s) | 84,6 s (134,6 s) | `node1` → `node3` a 22,0 s |

- **Solicitudes fallidas de k6: 0 en las cinco corridas**, antes y después del fallo, y 0 iteraciones descartadas. La app por la `.150` no tuvo caídas visibles a 1 Hz.
- En `r01` de K3s la VIP no migró; en las otras cuatro sí, entre 16,7 y 22,7 s tras el fallo.
- En `verif_k3s_media-fallo_r02` las dos VIP terminaron en nodos distintos (`.100` en `k3s-node2`, `.150` en `k3s-node1`). En las dos corridas de MicroK8s y en `r03` de K3s migraron al mismo nodo.
- En `verif_microk8s_media-fallo_r03` el pod estaba en el nodo que se iba a fallar y el orquestador lo movió de `microk8s-node2` a `microk8s-node1` antes de lanzar k6 (`pod_movido`).
- En MicroK8s `r02` el nodo apareció `NotReady` a los 96,1 s, es decir, **después** de restaurar el proceso (a los 90,4 s); por eso subí los valores provisionales a 30 s y 120 s en `r03`, donde la detección (111,9 s) ocurrió 8 s antes de restaurar.
- La rama de reinicio de kube-vip por titulares distintos no se ejercitó en ninguna corrida (`reinicios_kube_vip` = 0). Probé el reinicio por separado en MicroK8s: `rollout restart` y `rollout status` terminaron bien en 5,7 s.

### 2.5 Exploración con la configuración nueva y reinicio automático intacto (K3s, no versionada)

Con el `SIGKILL` y sin desactivar el reinicio de systemd: la VIP **migró igual** (la `.150` a los 11,7 s y la `.100` a los 13,7 s, del nodo 2 al nodo 3), la API tuvo dos tramos caídos (0,6 a 9,7 s y 11,7 a 14,7 s) y el nodo **nunca llegó a `NotReady`** (no hay detección que medir).

### 2.6 Parámetros efectivos de detección y tolerancia (T-19.4)

- Tolerancias del pod de NGINX (las inyecta Kubernetes, en ambas distribuciones): `node.kubernetes.io/not-ready` y `node.kubernetes.io/unreachable`, `NoExecute`, `tolerationSeconds: 300`.
- K3s: en `verif_k3s_media-fallo_r03` el campo `parametros_efectivos.argumentos_explicitos` trae, del kubelet (`00-k3s-defaults.conf`), `nodeStatusUpdateFrequency: 10s`, `nodeStatusReportFrequency: 5m0s`, `evictionPressureTransitionPeriod: 5m0s` y las claves `evictionHard` y `evictionMinimumReclaim`. Los argumentos del `kube-controller-manager` embebido que muestra el *journal* son `--cluster-cidr=10.42.0.0/16` y `--controllers=*,tokencleaner,-service,-route,-cloud-node-lifecycle` (leídos a mano en una corrida anterior); **no hay ningún argumento explícito de detección** (`node-monitor-grace-period` y similares). En `r01` y `r02` ese campo quedó vacío por un error de permisos al expandir el `*.conf`, ya corregido en `k6/lib/fallo.py` y reprobado en `r03`.
- MicroK8s: el único argumento explícito que coincide con el patrón es `--eviction-hard="memory.available<100Mi,nodefs.available<1Gi,imagefs.available<1Gi"` (del kubelet, sin relación con la detección de nodo caído).
- Por tanto, el tiempo hasta `NotReady` que medí es el resultado de los valores por defecto del binario. Verifiqué el valor efectivo consultando el endpoint `/configz` del `kube-controller-manager` (puerto `10257`) en cada distribución, sección `NodeLifecycleController`: `NodeMonitorGracePeriod` = `50s`, `NodeStartupGracePeriod` = `1m0s`, `PodEvictionTimeout` = `0s`.
  - K3s `v1.36.3+k3s1`: consulté los tres nodos con el certificado cliente de administrador (`/var/lib/rancher/k3s/server/tls/client-admin.crt`); los tres devolvieron `50s`.
  - MicroK8s `v1.36.2`: el endpoint responde 403 a usuario anónimo y el `kube-controller-manager` de `kubelite` no autentica certificados ni *tokens* por defecto (no tiene `--client-ca-file`). Para la consulta agregué `--client-ca-file=${SNAP_DATA}/certs/ca.crt` a `args/kube-controller-manager` **solo en `microk8s-node1`**, reinicié `kubelite`, consulté con `certs/client.crt` y restauré el archivo original (`diff` limpio) con otro reinicio. Devolvió `50s`. No consulté node2 ni node3; como los `args` no traen ninguna bandera de detección en ninguno, asumo el mismo valor, pero no lo medí.
  - Otros valores del kubelet de MicroK8s que devolvió el mismo endpoint: `nodeStatusUpdateFrequency: 10s`, `nodeLeaseDurationSeconds: 40`. `NodeMonitorPeriod` = `5s`.
  - Ese valor de 50 s no es la causa única del tiempo hasta `NotReady` medido (51,7 a 111,9 s): el valor de la tabla depende además de la reelección del líder del `kube-controller-manager` (sección 3).

### 2.7 Repeticiones completas y reloj (T-32.1)

Repetición `idle` con las fases del diseño (30 s, 180 s, 30 s), configuración nueva:

| Corrida | Ventana estable | Potencia media (W) | Continuidad de Prometheus | `chronyc tracking` antes de k6 (host / VMs) |
|---|---|---|---|---|
| `verif_k3s_idle_r02` | 180,0 s | 5,134 | 7/7 targets, cobertura 1,000 | host 3,7 ms atrasado; VMs hasta 6,0 ms |
| `verif_microk8s_idle_r02` | 180,0 s | 5,659 | 7/7 targets, cobertura 1,000 | host 0,03 ms; VMs hasta 0,10 ms |

La potencia es de una ventana de 3 min con la sesión gráfica abierta: **no la comparo entre distribuciones**. La corrida `verif_k3s_idle_r01` (configuración original) dio 4,998 W y 7/7 targets. En las corridas con fallo, la continuidad de Prometheus dio 7/7 targets con cobertura 1,000 y el tamaño del `.json.gz` de k6 fue de 2,86 a 2,92 MB.

## 3. Interpretación (no verificada)

- Que la VIP no migrara con la configuración original se explica por que el pod de kube-vip del nodo caído seguía renovando su lease por la IP del Service. Lo respalda la renovación cada ≈ 10 s que medí y el efecto del cambio, pero no inspeccioné el tráfico de ese pod.
- Que `kube-vip` pierda el lease al fallar el apiserver local depende del tiempo de renovación; no leí ni cambié los parámetros de elección de líder (los de la imagen).
- El tiempo hasta `NotReady` parece depender de si el nodo fallado tenía el liderazgo del `kube-controller-manager`: 51,7 s cuando no lo tenía y 69,6 s, 74,0 s, 96,1 s y 111,9 s cuando sí. En MicroK8s la reelección tardó ≈ 60 s y en K3s entre ≈ 18 y 22 s, y la detección llegó ≈ 36 a 52 s después de la reelección; no investigué el mecanismo ni medí los parámetros del controlador.
- Que la `.150` no mostrara errores durante la migración de la VIP puede deberse a la resolución de 1 s del muestreo o a que la migración fue más rápida que eso. No lo investigué.

## 4. Decisiones, hallazgos y desviaciones

### 4.1 Errores encontrados y corregidos durante la ejecución

1. **`systemctl kill -s SIGKILL k3s` devuelve error** por el `KillMode=process`; el script aborta con `set -e`. Cambié a `--kill-whom=main`.
2. **`terraform init` faltante**: `limpia.sh` borra el estado local de Terraform, así que antes de cada `apply` hay que ejecutar `terraform init`.
3. **El orquestador abortaba tras cambiar de distribución** porque `up` seguía devolviendo las series de la etiqueta anterior durante la ventana de 5 min de Prometheus; acoté la consulta a `last_over_time(up[30s])`.
4. **`argumentos_explicitos` vacío en K3s** (2.6), corregido y reprobado en `verif_k3s_media-fallo_r03`.

### 4.2 Decisiones tomadas

- **kube-vip contra el apiserver local** (2.3), en las dos distribuciones y con la misma plantilla. Cambia el comportamiento de kube-vip respecto de T-18: con la configuración original, la VIP no migró ante este fallo en K3s (en MicroK8s no probé la configuración original); las pruebas de T-18 (humo de k6, `svc_election`) no se repitieron con esta configuración.
- **Reinicio automático desactivado durante la retención** (2.1): sin ello el nodo no llega a `NotReady` y la detección no se puede medir. El archivo temporal en `/run/systemd/system/` se quita al restaurar y en un bloque `finally`. Es una desviación del protocolo escrito, que solo habla de `systemctl kill` y de `systemctl start` al final.
- **`--kill-whom=main`** en vez de la orden literal (4.1).
- **Nodo a fallar: el titular de la `.100` y la `.150` a la vez** (opción B). Cada VIP tiene su propio lease y tras un fallo pueden quedar en nodos distintos (2.4). Si no coinciden, el orquestador reinicia el DaemonSet de kube-vip (hasta 3 veces, con 30 s de espera) y aborta si siguen distintos. Así cada repetición ejercita la ruta de la aplicación.
- **Ubicación del pod (T-19.4)**: el pod de NGINX no puede estar en el nodo fallado; si coincide, el orquestador lo mueve con `kubectl patch deployment` (`nodeSelector`) a otro nodo y espera el *rollout*. Eso deja el despliegue distinto de lo declarado en Ansible (`app_node`) hasta volver a aplicar el playbook.
- **Valores provisionales de inyección y retención**: `--fallo-en 30` y `--fallo-retener 120` (por defecto). En `r01` y `r02` usé 40 y 90 s.
- **Marcas de tiempo**: `t_fallo` es el punto medio entre el tiempo del host antes y después del `ssh` que ejecuta el `kill` (cota = mitad del intervalo). La detección se mide por `kubectl` (cada 2 s) y por `kube_node_status_condition` de `kube-state-metrics` (el criterio del protocolo; resolución de 10 s por el intervalo de scrape). La recuperación de infraestructura es el retorno a `Ready`; la de aplicación, la normalización de `http_req_failed`.
- **Control del reloj**: cada corrida guarda `chronyc tracking` del host y de las VMs antes de lanzar k6 (`reloj_antes`).
- **Nombres de los datos**: `verif_<dist>_media-fallo_r<NN>`. `r01` es la configuración original de kube-vip (solo K3s) y `r02` y `r03`, la configuración nueva.

### 4.3 Desviaciones respecto del prompt y del diseño

- Cambio en kube-vip (4.2) y reinicio automático desactivado (4.2). Ambos los documento aquí porque cambian lo que describía la Etapa 2 (sección 4.4: «`systemctl kill`» y «el proceso de orquestación deja de responder»).
- Las afirmaciones de «validado por mí» del failover de la VIP que figuraban en `README.md` (AC-04), `k3sHA/README.md` y `microk8sHA/README.md` no tenían registro versionado y **no pude reproducirlas en K3s con kube-vip `v1.2.4` y su configuración original** (2.2); en MicroK8s no probé esa configuración. Las reemplazo por las mediciones de este documento.

## 5. Limitaciones

- Dos o tres corridas con fallo por distribución (una con la configuración original en K3s); sin repeticiones suficientes para estimar variabilidad. Los tiempos de migración (16,7 a 22,7 s) y de detección (51,7 a 111,9 s) varían entre corridas y no calculé dispersión.
- La detección depende de quién lidera el `kube-controller-manager` (3), que el protocolo no controla. Con la retención de 120 s la detección en MicroK8s (111,9 s) quedó a 8 s de la restauración; con 90 s ya se vio un `NotReady` posterior a la restauración (`r02`).
- Resolución: 1 s en las muestras del host, 2 s en `kubectl` y 10 s en `kube-state-metrics`; en una verificación anterior con 70 s de retención (descartada, no versionada) `kube-state-metrics` no captó el `NotReady`, porque la ventana duró unos 10 s.
- La tasa de 100 solicitudes por segundo es provisional; con 0 solicitudes fallidas no hay variabilidad para analizar el efecto sobre la aplicación. No probé tasas cercanas a la saturación (alta).
- Probé solo `SIGKILL` del proceso de orquestación; no probé apagado de la VM ni corte de red (extensiones del diseño).
- La rama de reinicio de kube-vip por titulares distintos no se ejercitó con una divergencia real.
- No repetí la exploración sin override en MicroK8s ni versioné las exploraciones de K3s (2.1, 2.2 y 2.5).
- Los snapshots de Prometheus de las verificaciones son copias completas de la TSDB; con estas corridas `data/` pasó a ≈ 114 MB (≈ 91 MB en snapshots).
- Los README de HU-15 que declaraban la migración «validada» se corrigen en este mismo commit; la validación anterior (con kube-vip `v0.8.9`) no tiene registro y no la repetí.

## 6. Pendiente

1. T-20.5: calibrar la tasa de carga media y de saturación; hasta entonces estos datos son de verificación.
2. T-20.7: política de fuentes externas de chrony, criterio de reloj convergido y tratamiento de `ufw` (ya abiertos).
3. Repetir el fallo con las repeticiones definitivas (HU-25) y estimar la variabilidad de la detección y de la migración.
4. Decidir si se controla o se estratifica por el líder del `kube-controller-manager` (afecta el tiempo de detección).
5. Decidir qué hacer con los snapshots de Prometheus (uno por repetición o uno por bloque).
6. Ingresar las horas reales de T-19.1 a T-19.5 en la hoja (no se estiman).

## 7. Archivos asociados a esta evidencia

| Archivo | Contenido |
|---|---|
| `k6/operacion/fallo-controlado.sh` | Inyección del `SIGKILL` (`--kill-whom=main`) con marcas de tiempo del host |
| `k6/lib/fallo.py` | Preparación y restauración del reinicio automático, observador a 1 Hz, movimiento del pod, parámetros efectivos, reloj, análisis y conteo de solicitudes fallidas |
| `k6/medicion/orquestador.py` | `--fallo`, `--fallo-en`, `--fallo-retener`, regla de coincidencia de las VIP, reloj previo, bloque `fallo` en los metadatos |
| `k3sHA/ansible/roles/kube_vip/templates/kube-vip.yaml.j2`, `microk8sHA/ansible/roles/kube_vip/templates/kube-vip.yaml.j2` | Elección de líder contra el apiserver local |
| `data/verificacion/*/metadatos/verif_*_media-fallo_r*.json` y `.observador.json.gz` | Metadatos y muestras de las corridas con fallo |
| `data/verificacion/*/metadatos/verif_*_idle_r0[12].json`, `data/verificacion/*/k6-resultados/verif_*` | Repeticiones idle completas y resultados de k6 |
| `data/prometheus-snapshots/` | Snapshots de las verificaciones |
| `data/README.md`, `README.md`, `k3sHA/README.md`, `microk8sHA/README.md` | Estado real y campos nuevos |
| este documento | Resumen de hechos, interpretaciones, decisiones y pendientes |

## 8. Criterio de aceptación

- T-19.1 «Procedimiento/script de fallo»: cumplido (`k6/operacion/fallo-controlado.sh` y el orquestador) con las dos desviaciones de 4.2; reproducible sobre un único nodo, probado en K3s y MicroK8s.
- T-19.2 «Registro de inicio, detección y recuperación»: cumplido; `t_fallo`, `NotReady` (por `kubectl` y por `kube-state-metrics`), regreso a `Ready`, cambios de titular y caídas de la API y de la app, con la resolución de 2.4.
- T-19.3 «Solicitudes afectadas con k6»: cumplido como herramienta (`fallo.analisis.k6`); el resultado de las cinco corridas es 0 solicitudes fallidas, a una tasa provisional.
- T-19.4 «Ubicación del pod y parámetros de detección y tolerancia»: la regla (pod fuera del nodo fallado) está implementada y se ejecutó una vez con movimiento real (`verif_microk8s_media-fallo_r03`). Los parámetros efectivos están registrados por el propio orquestador en ambas distribuciones (2.6); el valor efectivo de `node-monitor-grace-period` (50 s) lo verifiqué por `/configz` en los tres nodos de K3s y en un nodo de MicroK8s (2.6).
- T-19.5 «Revalidar la migración de la VIP con kube-vip `v1.2.4`»: cumplido en K3s y MicroK8s **con el cambio de configuración de 2.3**; con la configuración original no migraba en K3s. Sin control del titular al arranque: se registra y se exige la coincidencia de ambas VIP antes de inyectar.
- T-32.1 «Orquestador»: repetición con las fases del diseño ejecutada en ambas distribuciones (`idle` completa y `media` con fallo, esta última con los mismos valores provisionales en ambas), con metadatos, resultados de k6 y snapshot de Prometheus.

Commit: el segundo de este trabajo (el primero fue `095d877`), con HU-19, la repetición completa de T-32.1 y las correcciones de documentación.
