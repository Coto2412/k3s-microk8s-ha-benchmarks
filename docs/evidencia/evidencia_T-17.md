# Evidencia de HU-17 (T-17.1 a T-17.5): Node Exporter, Prometheus, etiquetas, continuidad y kube-state-metrics

Fechas: 2026-10-13 (host y clúster K3s) y 2026-10-18 (clúster MicroK8s y cierre). Las salidas provienen de mi terminal en el host (ThinkPad). Los playbooks del host se ejecutaron con `--ask-become-pass` (el sudo del host pide contraseña); los de las VMs, por SSH con la llave del proyecto. No hay mediciones experimentales: solo verificaciones de despliegue.

Convención: la sección 2 contiene hechos medidos u observados; la 3, interpretaciones no verificadas; la 4, decisiones, hallazgos y desviaciones; la 5, limitaciones; la 6, lo pendiente; la 7, los archivos asociados; la 8, el criterio de aceptación.

## 1. Alcance y condiciones

| Parámetro | Valor |
|---|---|
| Tareas cubiertas | T-17.1 (Node Exporter en el host y en las 3 VMs), T-17.2 (Prometheus en el host), T-17.3 (etiquetas y separación de datos), T-17.4 (continuidad, frecuencia y snapshot) y T-17.5 (kube-state-metrics) |
| Fuera de alcance | k6, aplicación de referencia, `chrony`, escritor definitivo de metadatos (T-32.1) |
| Host | Lenovo ThinkPad T14 Gen 2A, Ubuntu 24.04 (ver `evidencia_T-16.md`, sección 1) |
| Sesión durante las verificaciones | no registrada; no es una medición energética |
| Clústeres probados | K3s (13 y 18 de octubre) y MicroK8s (18 de octubre), uno a la vez; ambos destruidos entre pruebas |
| VMs | `192.168.100.11`, `.12`, `.13`; gateway/host `192.168.100.1` |

## 2. Hechos medidos u observados

### 2.1 Versiones y sumas de verificación fijadas

Origen: API de GitHub `releases/latest` (`prerelease: false`) y archivo `sha256sums.txt` de cada release. Las etiquetas se consultaron el 13 de octubre (dos veces) y no se volvieron a consultar el 18.

| Componente | Versión | URL | SHA-256 del tarball (`linux-amd64`) |
|---|---|---|---|
| Node Exporter | 1.12.1 | `https://github.com/prometheus/node_exporter/releases/download/v1.12.1/node_exporter-1.12.1.linux-amd64.tar.gz` | `b51d8a76aa2a9156a55d501aca6276fae09e262259a5e4e831d2c2222f084e63` |
| Prometheus (incluye `promtool`) | 3.15.0 | `https://github.com/prometheus/prometheus/releases/download/v3.15.0/prometheus-3.15.0.linux-amd64.tar.gz` | `2a542df32eac02ee17b9d844fb2aa1de00dafa5476579ba8a3ba862e9d572ea0` |

Binarios instalados en el host (`--version` y `sha256sum`):

| Binario | Revisión | SHA-256 |
|---|---|---|
| `/usr/local/bin/node_exporter` 1.12.1 | `6044da783597cc3b57aef7580ddcdcff58a4ee99` | `1108f7453ecfe4a72f131c73b69537c171840ad4f1713a2402328ad56cf12e09` |
| `/usr/local/bin/prometheus` 3.15.0 | `5241a27fe3c6983549fccc32f6e65917408c63cd` | `dac83d1d1007961de3b9ba624942c9af0c192ee3df262ac47ef390bcade71c65` |
| `/usr/local/bin/promtool` 3.15.0 | `5241a27fe3c6983549fccc32f6e65917408c63cd` | `c736d55d3ccd959fe48329965fb5cb671d45585a9483954766448035100ff75c` |

Las tareas `get_url` de Ansible descargan con `checksum: sha256:<valor>`: una descarga que no coincide falla la corrida.

### 2.2 Node Exporter (T-17.1)

- `--help` de la 1.12.1 imprime los colectores como `--[no-]collector.X`, no como `--collector.X`. Los nombres `cpu`, `meminfo`, `diskstats`, `filesystem`, `netdev` y `loadavg` figuran en esa forma.
- Unidad del host (`127.0.0.1:9100`, usuario `node_exporter` sin shell):

```
ExecStart=/usr/local/bin/node_exporter --web.listen-address=127.0.0.1:9100 --collector.disable-defaults --collector.cpu --collector.meminfo --collector.diskstats --collector.filesystem --collector.netdev --collector.loadavg
```

- Unidad de las VMs: igual, con `--web.listen-address=<IP propia de la VM>:9100` (variable `ansible_host`).
- Familias de métricas `node_*` expuestas, idénticas en el host, en las 3 VMs de K3s y en las 3 de MicroK8s: `node_cpu`, `node_disk`, `node_filesystem`, `node_load1/5/15`, `node_memory`, `node_network` y `node_scrape` (métricas propias del exporter), más `node_exporter_*`.
- Conteo de líneas de `/metrics` (métodos distintos, no comparables entre filas): host, 661 líneas sin comentarios; K3s, líneas que empiezan con `node_`: 311 (nodo 1), 231 (nodos 2 y 3); MicroK8s nodo 1, 339 líneas sin comentarios. No se investigó por qué el nodo 1 de K3s tiene más líneas que los otros dos.
- `systemctl is-active node_exporter`: `active` en el host y en las 6 VMs (3 por clúster, en momentos distintos).
- Escucha en el host: `127.0.0.1:9100`, `127.0.0.1:9090` y `127.0.0.1:8080` (salida de `ss -tlnp`).

### 2.3 Firewall de las VMs (`ufw`)

Reglas idénticas en los 3 nodos de K3s y en los 3 de MicroK8s (salida de `ufw status numbered`):

```
[ 1] 9100/tcp         ALLOW IN    192.168.100.1
[ 2] 9100/tcp         DENY IN     Anywhere
[ 3] 9100/tcp (v6)    DENY IN     Anywhere (v6)
```

En el nodo 1 de MicroK8s aparecen además reglas que agregó Calico (`vxlan.calico`, `cali+`), sin afectar la regla de 9100.

Reinicio de una VM (18 de octubre, `microk8s-node3`; `sudo systemctl reboot`): el `boot_id` pasó de `092efccf-adf2-4a29-92fe-585cfa68043f` a `a74d6095-9421-42bc-821d-e78a08831062` (arranque a las 17:37:50). Sin intervención posterior, `node_exporter` y `ufw` quedaron `active` y `enabled`; las reglas 1 y 2 de `9100/tcp` seguían presentes; `node_exporter` escuchaba en `192.168.100.13:9100`; el host recibió HTTP `200` y el nodo 2 siguió bloqueado (rc=28). En Prometheus, `up` del target volvió a 1; en los 15 minutos que incluyeron el reinicio hubo 1 muestra con `up=0` de 91 (paso de 10 s).

Reinicio de una VM en K3s (18 de octubre, `k3s-node3`; `sudo systemctl reboot`): el `boot_id` pasó de `10bba5f2-597b-4d1a-9c4f-f2b05a252e90` a `1a4511f1-06cf-4c26-b9ba-a1ef8dbaa0d7` (arranque a las 18:06:38). Sin intervención posterior, `node_exporter` y `ufw` quedaron `active` y `enabled`; las reglas 1 y 2 de `9100/tcp` seguían presentes; `node_exporter` escuchaba en `192.168.100.13:9100`; el host recibió HTTP `200` y el nodo 2 siguió bloqueado (rc=28). No se midió la interrupción en Prometheus: apliqué `distribution=k3s` al host después del reinicio, por lo que durante el reinicio esas series llevaban `distribution=microk8s`.

Prueba de acceso (repetida en ambos clústeres, mismos resultados):

| Origen | Destino | Resultado |
|---|---|---|
| nodo 2 (`192.168.100.12`) | nodo 1 `:9100/metrics` | sin respuesta, `curl` rc=28 (timeout de 4 s), código HTTP `000` |
| host (`192.168.100.1`) | nodo 1 `:9100/metrics` | HTTP `200` |

### 2.4 Prometheus (T-17.2)

- Unidad: usuario `prometheus` sin shell, `127.0.0.1:9090`, `--storage.tsdb.path=/var/lib/prometheus/data`, `--storage.tsdb.retention.time=90d`, `--web.enable-admin-api`.
- `prometheus --help` (3.15.0) lista `--[no-]web.enable-admin-api`. En esa versión la ayuda marca `--storage.tsdb.retention.time` como **[DEPRECATED]** (indica usar el campo de la configuración).
- `promtool check config` es una tarea bloqueante del rol antes de desplegar la unidad; pasó en todas las corridas (también `SUCCESS` en la prueba manual de la plantilla con `fallback_scrape_protocol`).
- Directorio de datos con modo `0750` y propietario `prometheus`: mi usuario recibió «Permiso denegado» al listarlo.
- Configuración: `scrape_interval: 10s`, `external_labels: {distribution: <k3s|microk8s>}`; trabajos `node_exporter_host` (`role=host`), `node_exporter_vms` (`role=node`, IPs de `vm_ips`), `scaphandre` (`keep` con `scaph_(host|socket|self)_.*`) y `prometheus` (autoscrape con `keep` de `process_resident_memory_bytes|process_cpu_seconds_total|prometheus_tsdb_head_series`).
- Medidas del 18 de octubre, con MicroK8s arriba y `distribution: microk8s`:

| Dato | Valor |
|---|---|
| Targets en `/api/v1/targets` | 6, todos `up` (host, 3 VMs, `scaphandre`, `prometheus`) |
| Series activas (`headStats.numSeries`) | 1689 |
| RSS de Prometheus (`ps`) | 130 268 kB |
| Series por trabajo | `node_exporter_vms` 906; `node_exporter_host` 666; `scaphandre` 30; `prometheus` 8 |
| `scaph_host_energy_microjoules` | presente en Prometheus (valor 12 350 576 458 µJ en la consulta) |

| `scrape_duration_seconds` (18 de octubre) | s |
|---|---|
| `scaphandre` `127.0.0.1:8080` | 0,0384 |
| `prometheus` `127.0.0.1:9090` | 0,0058 |
| `node_exporter_host` `127.0.0.1:9100` | 0,0106 |
| VM `192.168.100.11:9100` | 0,0067 |
| VM `192.168.100.12:9100` | 0,0069 |
| VM `192.168.100.13:9100` | 0,0063 |

Medidas del 18 de octubre, con K3s recreado y `distribution: k3s` (`-e active_distribution=k3s`):

| Dato | Valor |
|---|---|
| Targets con `up{distribution="k3s"}` | 6, todos con valor 1 |
| `external_labels` en `/api/v1/status/config` | `distribution: k3s` |
| Series activas (`headStats.numSeries`) | 5144 (incluye series de las pruebas anteriores que aún están en la cabeza de la TSDB; no es comparable con las cifras anteriores) |
| RSS de Prometheus (`ps`) | 116 752 kB |
| `scrape_duration_seconds` | `scaphandre` 0,0417 s; `prometheus` 0,0042 s; `node_exporter_host` 0,0083 s; VMs `.11` 0,0079 s, `.12` 0,0067 s, `.13` 0,0057 s |

Medidas del 13 de octubre (host solo, sin VMs): 626 y 651 series; RSS 96 988 kB y 96 572 kB; el trabajo `scaphandre` figuraba `down` hasta aplicar el cambio de la sección 4.2.

- Persistencia: tras el reinicio del host (`journalctl --list-boots`: el arranque del 13 de octubre terminó a las 20:30:37, el siguiente comenzó el 18 de octubre a las 14:09:33) y varios reinicios del servicio, `up{job="node_exporter_host"}` sigue consultable para el 13 de octubre entre las 23:25:30 y las 23:35:00 UTC (20 puntos con paso de 30 s). Las VMs de K3s ya estaban destruidas en ese lapso.

### 2.5 Playbooks y repetibilidad

| Corrida | Resultado |
|---|---|
| Host, 13 de octubre, primera con los tres roles | falló en `Verificar que --web.enable-admin-api existe` (ver 4.1) |
| Host, siguiente | `ok=34 changed=4 failed=0` |
| Host, corrida con `fallback_scrape_protocol` (4.2) | no registré el resumen; después, el target `scaphandre` figuraba `up` |
| Host, siguiente, sin cambios | `ok=32 changed=0 failed=0 skipped=2` |
| Host, 18 de octubre con `-e active_distribution=microk8s` | `ok=35 changed=6 failed=0` (cambio esperado de `distribution`) |
| Host, 18 de octubre, con la etiqueta `distribution` en cada trabajo (4.3) | `ok=33 changed=2 failed=0 skipped=2` (configuración y reinicio de Prometheus) |
| K3s, primera corrida completa con el rol nuevo | falló (ver 4.1); tras las correcciones, `failed=0` en los 3 nodos (`ok=44/45/43`) |
| K3s, segunda pasada | `changed=0` en nodos 2 y 3; nodo 1 con `changed=2`, ambos de `k3s_server` |
| K3s recreado, 18 de octubre, corrida completa | `failed=0` (`ok=49/45/43`, `changed=27/24/24`) |
| Host, 18 de octubre con `-e active_distribution=k3s` | `ok=33 changed=2 failed=0 skipped=2` |
| MicroK8s, primera corrida | `failed=0` (`ok=61/58/58`) |
| MicroK8s, segunda pasada | nodo 1 `changed=4`, nodos 2 y 3 `changed=1`; todas del rol `microk8s_server` |

En ninguna segunda pasada cambió una tarea de `node_exporter` o `prometheus`.

### 2.6 Chrony (solo reporte, sin acción; estado de entonces, implementado después en `evidencia_T-34.md`)

- `chronyc` no existe en el host ni en ninguna de las VMs (K3s y MicroK8s).
- En las VMs de MicroK8s, `timedatectl` indica `NTPSynchronized=yes`; el servicio de hora es el predeterminado de Ubuntu, no `chrony`. Su configuración de servidores no se revisó.

### 2.7 kube-state-metrics, continuidad y snapshot (T-17.3 a T-17.5)

**kube-state-metrics (T-17.5).** Versión v2.20.0, imagen `registry.k8s.io/kube-state-metrics/kube-state-metrics:v2.20.0` con digest `sha256:42cfe3723a5f058171c627537fb57a3ea0f26e4380fa18555a95cb1a1b4cfc5b`, idéntica en K3s y MicroK8s. Se despliega con `k8s/kube-state-metrics.yaml` (ServiceAccount, ClusterRole, ClusterRoleBinding, Deployment y Service `NodePort` 30080 métricas / 30081 telemetría; contenedor en 8080/8081). Prometheus lo consulta en `192.168.100.100:30080` (VIP del plano de control). El despliegue es parte del *play* del nodo 1 en ambos playbooks (rol `kube_state_metrics`) y terminó sin fallos en los dos clústeres; en K3s la espera del *rollout* necesitó 2 reintentos.

**Criterio de continuidad (T-17.4), fijado antes de medir.** Por target: ≥ 99 % de las muestras esperadas (una cada 10 s), ningún hueco mayor a 30 s y `up=0` en ≤ 1 % de las muestras. Los 7 targets esperados por clúster son el host, las 3 VMs, `scaphandre`, `kube_state_metrics` y el propio Prometheus.

**Piloto en reposo de 20 minutos por clúster** (`analysis/verificacion/continuidad.py`, código de salida 0 en ambos):

| Clúster | Ventana (UTC-3, 18 de octubre) | Targets | Muestras por target | Hueco máximo | `up=0` |
|---|---|---|---|---|---|
| K3s | 15:26:27 a 15:46:27 | 7 | 120/120 | 10,0 s | 0 |
| MicroK8s | 15:57:51 a 16:17:51 | 7 | 120/120 | 10,0 s | 0 |

**Separación por distribución (T-17.3).** En la ventana de MicroK8s, `node_load1` promedió 0,154 (`.11`), 0,133 (`.12`) y 0,111 (`.13`); la misma consulta con `distribution="k3s"` devolvió 0 series. La ventana, el escenario y la repetición no son etiquetas (decisión de diseño); van en un JSON de metadatos por repetición, con la estructura de los archivos `data/verificacion/*/metadatos/piloto_T-17.4_<distribución>.json` (`data/` no se versionaba cuando los generé; copio aquí el contenido):

```json
{"distribution": "k3s", "escenario": "reposo", "repeticion": 1, "tarea": "T-17.4",
 "t_inicio": 1792347987.566, "t_fin": 1792349187.566,
 "inicio": "2026-10-18T15:26:27-0300", "fin": "2026-10-18T15:46:27-0300",
 "k3s_version": "v1.36.3+k3s1", "kube_state_metrics": "v2.20.0",
 "node_exporter": "1.12.1", "prometheus": "3.15.0"}
{"distribution": "microk8s", "escenario": "reposo", "repeticion": 1, "tarea": "T-17.4",
 "t_inicio": 1792349871.716, "t_fin": 1792351071.716,
 "inicio": "2026-10-18T15:57:51-0300", "fin": "2026-10-18T16:17:51-0300",
 "microk8s_version": "v1.36.2", "kube_state_metrics": "v2.20.0",
 "node_exporter": "1.12.1", "prometheus": "3.15.0"}
```

**Snapshot de la TSDB (T-17.4).** Con `POST /api/v1/admin/tsdb/snapshot` se generó el snapshot del piloto de K3s (`20261018T184657Z-4b8400683efd4f67`) y lo copié fuera del directorio de datos de Prometheus con `sudo` (el directorio pertenece al usuario `prometheus`, modo 0750), a `data/prometheus-snapshots/`. Lo revisé con `promtool tsdb list` y `promtool tsdb analyze`: 2 bloques, 2,1 MB, con la etiqueta `distribution` en las series. Al terminar el piloto de MicroK8s se generó un segundo snapshot (`20261018T191826Z-3bd5b8e4fd423564`), que copié después del mismo modo a `data/prometheus-snapshots/` (2,7 MB). `promtool tsdb list` muestra 2 bloques: uno del 13 de octubre (651 series, sin la etiqueta `distribution`) y otro que cubre del 13 al 18 de octubre hasta las 16:18 (7030 series, 1 145 437 muestras); `promtool tsdb analyze` lista `distribution=k3s` y `distribution=microk8s` entre las etiquetas de ese bloque (no interpreté los conteos individuales).

**Series y memoria.** El clúster K3s mostró 625 series de `kube_state_metrics` (95 nombres de métrica) y el de MicroK8s 781 (105). Comparé por nombre de métrica en el último minuto de cada ventana y la diferencia se explica por los objetos que cada distribución crea, no por una configuración distinta de kube-state-metrics: MicroK8s tiene 10 pods (K3s, 7) por `calico-node` ×3, `calico-kube-controllers` y `hostpath-provisioner`, además de un DaemonSet y un PodDisruptionBudget extra y *init containers* de Calico (`kube_pod_init_container_*`); K3s aporta 4 Secrets (`k3s-serving` y 3 `node-password`), `kube_node_role` y `kube_node_spec_pod_cidrs`, que MicroK8s no expone. El RSS de Prometheus difiere entre ambas ventanas, pero hubo reinicios entre medias, así que no lo uso para comparar.

**Condición de los nodos (cierre de HU-17, 18 de octubre).** Consulta: `kube_node_status_condition{status="true"} == 1`, ejecutada en Prometheus con cada clúster levantado (detalle de la aplicación de referencia en `evidencia_T-18.md`):

| Clúster | Series devueltas |
|---|---|
| K3s | 6: `Ready` y `EtcdIsVoter` en `k3s-node1`, `k3s-node2` y `k3s-node3` |
| MicroK8s | 3: `Ready` en `microk8s-node1`, `microk8s-node2` y `microk8s-node3` |

Todas con la etiqueta `distribution` de su clúster.

## 3. Interpretación (no verificada)

- La diferencia de series de `kube_state_metrics` es una diferencia de carga de trabajo del sistema (CNI Calico en MicroK8s, Secrets propios en K3s), no de configuración (2.7). Que esa diferencia afecte el consumo de CPU o energía de cada clúster no está medido.
- El nodo 1 de K3s expone más líneas `node_*` que los otros dos; podría deberse a más interfaces o sistemas de archivos montados en ese nodo, pero no se comprobó.
- `external_labels` no aparece en las series almacenadas (ver 4.3). La documentación de Prometheus lo describe como un mecanismo para sistemas externos (federación, escritura remota, alertas); se verificó en este host que no queda en las series locales.
- El RSS de Prometheus pasó de unos 97 MB a unos 130 MB al crecer las series de 651 a 1689, pero son dos muestras puntuales; no se determinó cómo escala.

## 4. Decisiones, hallazgos y desviaciones

### 4.1 Errores encontrados y corregidos durante la ejecución

1. **Comprobación de colectores**: buscaba la cadena `--collector.X ` y `--help` la imprime como `--[no-]collector.X`; la comprobación fallaba siempre. Ahora busca `collector.X ` (el espacio final evita confundir `cpu` con `cpufreq`).
2. **Plantilla systemd**: Ansible activa `trim_blocks` de Jinja2, que eliminaba el salto de línea tras `{% endfor %}`; `Restart=on-failure` quedó pegado al `ExecStart` (`unknown long flag '--collector.loadavgRestart'`). Se corrigió con `{% endfor +%}`. La prueba manual con `jinja2.Template()` no lo detectó porque usa otros valores por defecto; la verificación válida requiere `trim_blocks=True` o la corrida real.
3. **`ufw`**: `ufw insert N` rechaza cualquier posición con el conjunto de reglas vacío. Se eliminó `insert`; el orden de las tareas (permitir antes de denegar) basta, porque `ufw` evalúa en orden y la primera coincidencia gana.
4. **Comprobación de `--web.enable-admin-api`**: el mismo problema que en 1 (`--[no-]web.enable-admin-api`). La bandera existe en la 3.15.0.

### 4.2 Desviaciones y decisiones tomadas

- **Prometheus 3.15.0 (versión mayor 3.x)**: la versión estable vigente el 13 de octubre es la 3.x. Evalué fijar la 2.x por el salto de versión mayor. **Decidí mantener 3.15.0 el 18 de octubre**, porque lo que importa para la reproducibilidad es la versión y la suma de verificación fijadas. Efectos observados: la bandera de la API de administración sigue existiendo; `--storage.tsdb.retention.time` figura como obsoleta (no verificado qué versión la retirará; no afecta mientras la versión esté fijada); se agregó `fallback_scrape_protocol` (siguiente punto). No se verificó el estado de soporte de la rama 2.x.
- **`fallback_scrape_protocol: PrometheusText0.0.4` en el trabajo `scaphandre`**: el exportador responde HTTP 200 con 3533 líneas `scaph_`, pero sin cabecera `Content-Type`; Prometheus 3.x lo marcaba `down` con `non-compliant scrape target sending blank Content-Type and no fallback_scrape_protocol specified for target`. Con el campo, el target quedó `up` y `scaph_host_energy_microjoules` llega filtrada por el `keep`. El campo se validó con `promtool`.
- **`ufw` con política entrante `allow`**: se fijó `default allow incoming` antes de activar `ufw` y se restringió solo `9100/tcp` (permitir desde `192.168.100.1`, denegar el resto). Motivo: `ufw` instalado de fábrica activaría `deny` por defecto y bloquearía SSH, la API de Kubernetes, VXLAN y kubelet. Consecuencia: el resto de puertos de las VMs queda abierto como antes; no es un endurecimiento general.
- **Mecanismo de firewall**: no existía ninguno en el repositorio (ni en los roles de T-12.3). Elegí `ufw`, como tarea nueva en el rol `node_exporter` de las VMs.
- **Dirección de escucha en las VMs**: `ansible_host` (IP propia), según el diseño; el host escucha en `127.0.0.1`.
- Roles de las VMs duplicados en `k3sHA/ansible/roles/node_exporter/` y `microk8sHA/ansible/roles/node_exporter/`, con el mismo contenido, igual que `kube_vip`.
- `active_distribution` queda en `k3s` por defecto en `ansible/group_vars/all.yml`; para MicroK8s se usa `-e active_distribution=microk8s` en lugar de editar el archivo.

### 4.3 Hallazgo sobre `external_labels` y decisión tomada

El diseño prevé `external_labels` con la distribución activa. En este host, una serie consultada localmente (`up{job="node_exporter_host"}`) no llevaba la etiqueta `distribution`, y `up{distribution="microk8s"}` devolvía 0 resultados, aunque `/api/v1/status/config` mostraba `external_labels: distribution: microk8s`. Por lo tanto, la distribución no quedaba en las series de la TSDB; solo la identificaban la configuración vigente y el archivo de metadatos.

**Decisión (18 de octubre):** etiqueta estática `distribution: {{ active_distribution }}` en cada `static_configs` de `prometheus.yml.j2` (los cuatro trabajos); `external_labels` se mantiene como estaba. No cambia la cardinalidad: un valor constante por configuración.

Verificado después de aplicar el playbook (`ok=33 changed=2 failed=0`):
- `up{distribution="microk8s"}` devuelve los 6 targets con valor 1.
- `scaph_host_energy_microjoules{distribution="microk8s"}` devuelve la serie de energía.
- `count by (distribution)`: 1610 series con `distribution="microk8s"`; las series anteriores al cambio carecen de la etiqueta y siguieron consultables unos minutos por la ventana de retrospección de 5 min. Las muestras del 13 y 18 de octubre previas al cambio no tienen la etiqueta; son datos de prueba.

Esto afecta a T-17.3 (etiquetas) y deja la distribución dentro de cada snapshot de la TSDB.

### 4.4 Decisiones de T-17.3 a T-17.5

- **kube-state-metrics por `NodePort` a través de la VIP `.100`**: el diseño exige leer la API estándar de Kubernetes sin acoplarse a etcd/Dqlite. Elegí `NodePort` porque Prometheus (en el host, fuera del clúster) no necesita token ni CA, y el mecanismo es idéntico en K3s y MicroK8s (comparación simétrica). El Service `LoadBalancer` de kube-vip se deja para la aplicación de referencia (T-18): `svc_enable` sigue en `"false"` a propósito.
- **Versión fijada v2.20.0 con digest**: se usan los manifiestos `examples/standard` de la versión, con el Service cambiado de *headless* a `NodePort`. La misma imagen corre en las dos distribuciones.
- **Criterio de continuidad fijado antes de medir** (2.7), para no ajustarlo a los resultados.
- **Convención de metadatos**: la distribución va como etiqueta estática (4.3); escenario, repetición y ventana van en un JSON por repetición. El escritor definitivo de ese JSON quedó hecho después en `k6/orquestador.py` (T-32.1, `evidencia_T-34.md`); `continuidad.py` solo verifica.
- **Sin almacenamiento externo al host**: el respaldo de snapshots y resultados es el repositorio (`data/` versionado); no habrá copia fuera del equipo.
- **Prueba de continuidad con la VIP**: el target `kube_state_metrics` depende de la VIP; durante una conmutación de la VIP tendrá un hueco breve. Lo acepto: es parte de lo que mide el protocolo de fallo controlado.

## 5. Limitaciones

- Los pilotos de T-17.4 son solo en reposo (sin k6): no demuestran continuidad bajo carga media o alta.
- Hay una sola corrida de 20 minutos por clúster; no hay repeticiones.
- `continuidad.py` es una verificación, no el orquestador de repeticiones (T-32.1).
- Durante una conmutación de la VIP, el target `kube_state_metrics` tendrá un hueco que no medí.
- El reinicio se probó en una sola VM por clúster (`node3`), no en las otras.
- En K3s no medí la interrupción del reinicio en Prometheus (ver 2.3).
- Comparé K3s y MicroK8s con una sola corrida cada uno; no hay repeticiones.
- La persistencia de la TSDB se comprobó con una ventana de 10 minutos del 13 de octubre; no se comprobó un reinicio de todo el flujo con borrado y recreación del clúster mientras Prometheus tenía datos de ese clúster.
- Una sola muestra por medida (series, RSS, duración de scrape): no hay variabilidad ni costo del scrape bajo carga.
- Las versiones oficiales no se volvieron a consultar el 18 de octubre.
- `ufw` no restringe IPv6 con una regla `allow` propia; solo existe `DENY IN` para `9100/tcp (v6)`.
- Las tareas no idempotentes de `k3s_server` y `microk8s_server` (kubeconfig, `snap_refresh_timer`, DNS y almacenamiento) quedan fuera de este alcance y no se modificaron.

## 6. Pendiente

1. `chrony` como tarea separada (el diseño lo exige: host como fuente de referencia NTP, VMs como clientes solo de `192.168.100.1`; al momento de T-17 no estaba implementado). Quedó hecho después en `evidencia_T-34.md`.
2. Ingresar las horas reales de T-17.1 a T-17.5 en la hoja (no se estiman).
3. Hacer commit con esta evidencia (sección 7).

T-16.3 (consulta a Prometheus de la misma ventana) se cerró el 18 de octubre; ver `evidencia_T-16.md`, sección 2.6a.

## 7. Archivos asociados a esta evidencia

| Archivo | Contenido |
|---|---|
| `ansible/roles/node_exporter/` | Rol del host (`127.0.0.1:9100`) |
| `ansible/roles/prometheus/` | Rol del host (binario, usuario, configuración, unidad, validación con `promtool`) |
| `ansible/group_vars/all.yml` | Versiones, sumas de verificación, colectores, retención, `active_distribution`, `vm_ips` |
| `ansible/playbook.yml` | Añade `node_exporter` y `prometheus` a `scaphandre` |
| `k3sHA/ansible/roles/node_exporter/`, `microk8sHA/ansible/roles/node_exporter/` | Rol de las VMs, incluida la tarea `ufw` |
| `k3sHA/ansible/group_vars/all.yml`, `microk8sHA/ansible/group_vars/all.yml` | Variables del rol de las VMs |
| `k3sHA/ansible/playbook.yml`, `microk8sHA/ansible/playbook.yml` | Añaden `node_exporter` después de `kube_vip` en ambos *plays* |
| `ansible/roles/prometheus/templates/prometheus.yml.j2` | Trabajos y etiqueta `distribution`, incluido `kube_state_metrics` |
| `k8s/kube-state-metrics.yaml` | Manifiesto de kube-state-metrics v2.20.0 (Service `NodePort`) |
| `k3sHA/ansible/roles/kube_state_metrics/`, `microk8sHA/ansible/roles/kube_state_metrics/` | Despliegue del manifiesto en cada distribución |
| `analysis/verificacion/continuidad.py` | Verificación de continuidad por ventana de metadatos |
| `analysis/verificacion/consulta_prometheus.py` | Comparación de T-16.3 (ver `evidencia_T-16.md`) |
| `data/verificacion/*/metadatos/`, `data/prometheus-snapshots/` | Metadatos y snapshots de los pilotos (versionados; ver `data/README.md`) |
| este documento | Resumen de hechos, interpretaciones, decisiones y pendientes |

## 8. Criterio de aceptación

- T-17.1 «Node Exporter en el host y en las VMs»: cumplido en el host, K3s y MicroK8s, con solo los seis colectores y acceso restringido a `192.168.100.1` en las VMs. Reservas: sección 5.
- T-17.2 «Prometheus en el host»: cumplido (servicio activo, 6 targets `up` con MicroK8s, `promtool` validado, TSDB persistente, etiqueta `distribution` en las series). La versión 3.15.0 y la etiqueta quedaron decididas el 18 de octubre (4.2 y 4.3).

- T-17.3 «Etiquetas y separación de datos»: cumplido con etiqueta estática `distribution` y convención de metadatos; la consulta por distribución, nodo y ventana separa los datos (2.7). El escritor de metadatos queda para T-32.1.
- T-17.4 «Continuidad, frecuencia y snapshot»: cumplido en reposo en ambos clústeres (7 targets × 120/120 muestras, hueco máximo 10 s, `up=0` nulo) y snapshots creados, copiados e inspeccionados (K3s y MicroK8s). Reservas: sección 5.
- T-17.5 «kube-state-metrics»: cumplido en K3s y MicroK8s con la misma imagen y el mismo mecanismo de acceso (4.4).
