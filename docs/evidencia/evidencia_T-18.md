# Evidencia de HU-18 (T-18.1 a T-18.5): aplicación de referencia, Service LoadBalancer con kube-vip y scripts de k6

Fecha: 18 de octubre de 2026. Las salidas provienen de mi terminal en el host (ThinkPad). Probé un clúster a la vez: primero K3s y, tras destruirlo, MicroK8s. Los playbooks del host se ejecutaron con `--ask-become-pass`; los de las VMs, por SSH con la llave del proyecto. Las pruebas de k6 son de humo (20 solicitudes por segundo durante 30 s): no son calibración ni medición experimental. Todo se hizo con la sesión gráfica abierta y solo dos terminales abiertas (la de Claude Code y otra); no son condiciones de ejecución definitiva.

Convención: la sección 2 contiene hechos medidos u observados; la 3, interpretaciones no verificadas; la 4, decisiones, hallazgos y desviaciones; la 5, limitaciones; la 6, lo pendiente; la 7, los archivos asociados; la 8, el criterio de aceptación.

## 1. Alcance y condiciones

| Parámetro | Valor |
|---|---|
| Tareas cubiertas | T-18.1 (NGINX de referencia), T-18.2 (acceso y endpoints), T-18.3 (scripts de k6), T-18.4 (organización de resultados) y T-18.5 (Service LoadBalancer con kube-vip en `.150`) |
| Cierres de HU-17 incluidos | consulta `kube_node_status_condition` en ambos clústeres y copia del snapshot de MicroK8s (detalle en `evidencia_T-17.md`, sección 2.7) |
| Fuera de alcance | calibración de tasas y de CPU (T-20.5), resiliencia (HU-19), orquestador y escritor de metadatos (T-32.1, hecho después: `evidencia_T-34.md`), `chrony` (HU-34, hecho después: `evidencia_T-34.md`) |
| Host | Lenovo ThinkPad T14 Gen 2A, Ubuntu 24.04 (ver `evidencia_T-16.md`, sección 1) |
| Clústeres probados | K3s `v1.36.3+k3s1` y MicroK8s `v1.36.2`, uno a la vez, ambos destruidos al terminar |
| Red | VMs `192.168.100.11` a `.13`, VIP del plano de control `.100`, VIP del Service `.150`, host `.1` |

## 2. Hechos medidos u observados

### 2.1 Versiones consultadas y fijadas

| Componente | Versión | Fuente y verificación | Valor fijado |
|---|---|---|---|
| NGINX | 1.30.6 (etiqueta `stable`) | API de Docker Hub: el digest de `stable` coincide con el de `1.30.6` | `nginx:1.30.6@sha256:eb1c896deef834f4e056829fd6dadac8305501f16cc71ba65fb252c8d0aa168e` |
| k6 | v2.3.0 | API de GitHub `releases/latest` (`prerelease: false`, publicada el 21 de septiembre) y `k6-v2.3.0-checksums.txt` | tarball `linux-amd64`, sha256 `39c3117b6af817592dcd0ce4242105c0a7af10948c2a425306f0be8f7a8a8ab1` |
| kube-vip | v1.2.4 (antes v0.8.9) | API de GitHub: la v1.3.0 se publicó el 16 de octubre y trae un cambio incompatible sobre IPs compartidas entre Services (no nos afecta, pero es de hace 2 días); la v1.2.4 es del 16 de septiembre | `ghcr.io/kube-vip/kube-vip:v1.2.4` |

- El digest de NGINX se verificó al desplegar: `imageID` del contenedor en K3s y en MicroK8s es `docker.io/library/nginx@sha256:eb1c896d…a168e`, y `crictl images --digests` en el nodo de K3s muestra `eb1c896deef83`.
- `k6 version` en el host: `k6 v2.3.0 (commit/e088784614, go1.26.8, linux/amd64)`. El rol del host terminó con `ok=37 changed=5 failed=0`.
- Dentro del contenedor: `nginx version: nginx/1.30.6`.

### 2.2 Despliegues

| Corrida | Resultado |
|---|---|
| K3s, primera corrida con el rol en el *play* del nodo 1 | falló: el pod quedó `Pending` porque `k3s-node2` aún no se había unido (ver 4.1) |
| K3s, corrida con el *play* 3 | `failed=0` (nodo 1 `ok=49 changed=2`, nodos 2 y 3 `ok=45/43 changed=24`) |
| K3s, segunda pasada | `failed=0`; nodo 1 `changed=2` (solo `k3s_server`, copia del kubeconfig), nodos 2 y 3 `changed=0` |
| MicroK8s, primera corrida | `failed=0` (`ok=68/58/58`, `changed=39/33/33`) |
| MicroK8s, segunda pasada | `failed=0`; `changed=4/1/1`, todas de `microk8s_server` |

En ninguna segunda pasada cambió una tarea de `kube_vip` ni de `nginx_referencia`.

Luego repetí el ciclo completo con kube-vip `v1.2.4` (sección 2.7): K3s `failed=0` (`ok=54/45/43`) y MicroK8s `failed=0` (`ok=68/58/58`).

### 2.3 Pod, QoS y recursos

| Dato | K3s | MicroK8s |
|---|---|---|
| Nodo del pod | `k3s-node2` (`192.168.100.12`) | `microk8s-node2` (`192.168.100.12`) |
| Estado y reinicios | `Running`, 0 | `Running`, 0 |
| Clase QoS | `Guaranteed` | `Guaranteed` |
| `cpu.max` dentro del contenedor | `50000 100000` | `50000 100000` |
| `memory.max` | 134 217 728 B (128 MiB) | 134 217 728 B (128 MiB) |
| `memory.current` tras la prueba de humo | 4 308 992 B | 4 153 344 B |
| `memory.peak` tras la prueba de humo | 7 192 576 B | 7 135 232 B |

`kube_pod_container_resource_limits` en Prometheus devuelve `cpu = 0.5` y `memory = 134217728` en ambos clústeres, y `kube_pod_status_qos_class` devuelve `Guaranteed`. `kube_pod_container_resource_requests` con los mismos valores lo consulté solo en K3s.

### 2.4 Service LoadBalancer y VIP

| Dato | K3s | MicroK8s |
|---|---|---|
| `status.loadBalancer` | `192.168.100.150`, `ipMode: VIP`, puerto 80/TCP | igual |
| Lease `plndr-cp-lock` (plano de control) | `k3s-node1` | `microk8s-node1` |
| Lease `plndr-svcs-lock` (Services) | `k3s-node1` | `microk8s-node1` |
| MAC en la tabla ARP del host para `.100`, `.150` y `.11` | `52:54:00:10:00:01` (las tres iguales) | `52:54:00:20:00:01` (las tres iguales) |
| `curl http://192.168.100.150/` | `200` en 0,0009 s | `200` |
| `curl http://192.168.100.150/healthz` | `ok`, `200` | `ok`, `200` |
| API por la VIP `.100` (`/healthz` sin credenciales) | `401` en el puerto 6443 | `401` en el puerto 16443 |

Con `svc_enable: "true"` los nodos siguieron `Ready` y `192.168.100.11` conservó su MAC: no se reprodujo el incidente descrito en el comentario anterior de la plantilla (kube-vip tomando la IP de un nodo). En MicroK8s, con kube-vip `v0.8.9`, los pods registraron 2 y 1 reinicios durante el arranque (nodos 1 y 3); con `v1.2.4` solo el del nodo 1 registró 2.

### 2.5 k6: prueba de humo y afinidad de CPU

Parámetros: `TASA=20 RAMPA_S=5 ESTABLE_S=20 DESCENSO_S=5 PRE_VUS=5 MAX_VUS=20`, `REPETICION=0`, escenario `media`, por `k6/correr.sh`.

| Dato | K3s | MicroK8s |
|---|---|---|
| Solicitudes | 499 | 499 |
| `checks` (`status 200`) | 499 de 499 | 499 de 499 |
| `http_req_duration` promedio / p(95) / máximo | 837 µs / 1,1 ms / 2,8 ms | 723 µs / 876 µs / 4,56 ms |
| Archivos generados | `k3s_media_r00.json.gz`, `k3s_media_r00.resumen.json` | `microk8s_media_r00.json.gz`, `microk8s_media_r00.resumen.json` |

- El JSON de K3s tiene 7062 líneas (`zcat | wc -l`) y pesa 71 238 B comprimido.
- Escenario `idle` (1 VU, 1+6+1 s, sin solicitudes HTTP): 8 iteraciones en cada clúster, sin tráfico.
- Durante la corrida de `idle` leí `/proc/<pid>/status` de k6: `Cpus_allowed_list: 0-1`; `taskset -pc` confirma `0,1`.
- `lscpu -e` muestra que las CPU 0 y 1 son los dos hilos del núcleo 0; `vm_cpusets` fija las VMs a las CPU 2 a 7 (núcleos 1 a 3).

### 2.6 Prometheus y kube-state-metrics

En ambos clústeres, `up{job="kube_state_metrics"}` vale 1 y llegan con la etiqueta `distribution` correcta:
`kube_pod_info{pod=~"nginx-referencia.*"}` (nodo `k3s-node2` / `microk8s-node2`), `kube_deployment_status_replicas_available{deployment="nginx-referencia"} = 1`, `kube_service_info{service="nginx-referencia"}` (solo la consulté en K3s), y los límites y la clase QoS de 2.3.

`kube_node_status_condition{status="true"} == 1`: K3s devuelve 6 series (`Ready` y `EtcdIsVoter` en los 3 nodos); MicroK8s devuelve 3 (`Ready` en los 3 nodos).

### 2.7 kube-vip v1.2.4, `svc_election` y verificaciones con carga

**Actualización (ambos clústeres, 18 de octubre, `svc_election: "false"`).** Los 3 pods de kube-vip corren `v1.2.4`, los nodos siguen `Ready` con su IP, la API responde por la `.100` (`401` sin credenciales), y `/` y `/healthz` responden `200` por la `.150`. La configuración por variables de entorno y el RBAC anteriores siguieron valiendo en la serie 1.x. En los logs de MicroK8s aparece el aviso `WARN Node name is missing from the config, fall back to hostname`; en K3s no repetí la búsqueda con ese patrón.

**Quién sostiene cada VIP (`svc_election: "false"`).**

| Clúster | `plndr-cp-lock` | `plndr-svcs-lock` | MAC de `.100` y `.150` |
|---|---|---|---|
| K3s | `k3s-node1` | `k3s-node1` | `52:54:00:10:00:01` ambas |
| MicroK8s | `microk8s-node3` | `microk8s-node3` | `52:54:00:20:00:03` ambas |

El líder no es siempre el mismo: en MicroK8s fue el nodo 1 en la corrida con `v0.8.9` (2.4) y el nodo 3 en la corrida con `v1.2.4`, y en K3s fue el nodo 1 en ambas. No lo controlé.

**`svc_election: "true"`.** Se crea un *lease* por Service (`default/kubevip-nginx-referencia`) y `plndr-svcs-lock` queda sin titular.

| Clúster | Estado | Titular del Service (`.150`) | Titular del plano de control (`.100`) |
|---|---|---|---|
| K3s | tras aplicar | `k3s-node1` | `k3s-node1` |
| K3s | tras borrar el pod de kube-vip del nodo 1 | `k3s-node3` (MAC `…:03`) | `k3s-node1` |
| MicroK8s | tras aplicar | `microk8s-node1` (MAC `…:01`) | `microk8s-node3` |
| MicroK8s | tras borrar el pod de kube-vip del nodo 1 | `microk8s-node2` (MAC `…:02`) | `microk8s-node3` |

Durante el borrado del pod, 120 solicitudes a `http://192.168.100.150/` (una cada 0,25 s, `--max-time 0,4`) respondieron `200` en ambos clústeres, sin ninguna falla. No es la prueba de resiliencia de HU-19: es una observación puntual.

**Camino del tráfico (`svc_election: "false"`, contadores de `/proc/net/dev` antes y después de 35 000 solicitudes).**
- K3s: la `ens3` del nodo 1 recibió 28,3 MB y envió 30,7 MB; la interfaz `flannel.1` del nodo 1 envió 8,0 MB, que coinciden con lo que recibió `flannel.1` del nodo 2 (8,0 MB); el nodo 3 casi no cambió.
- MicroK8s: lo mismo con el nodo 3 como entrada y `vxlan.calico` hacia el nodo 2 (7,98 MB recibidos en el nodo 2); el nodo 1 casi no cambió.
- Cuando el titular de la `.150` no es el nodo del pod, el tráfico hace un salto por VXLAN; cuando coincide (MicroK8s con `svc_election: "true"`, titular `microk8s-node2`), ese salto no existe. Ese caso no lo medí con contadores.

**Carga moderada (no es calibración): 1000 solicitudes por segundo objetivo, 30 s estables, `PRE_VUS=50`, `MAX_VUS=200`.**

| Dato | K3s | MicroK8s |
|---|---|---|
| Solicitudes y `checks` | 34 999 de 34 999 | 35 000 de 35 000 |
| Tasa promedio de la corrida | 874,96/s | 874,95/s |
| `http_req_duration` promedio / p(95) / máximo | 305 µs / 432 µs / 5,64 ms | 309 µs / 444 µs / 5,68 ms |
| `memory.peak` / `memory.current` del contenedor | 7 380 992 B / 4 468 736 B | 7 188 480 B / 4 161 536 B |
| `nr_throttled` (`cpu.stat`) | 0 | 0 |
| Procesos `nginx: worker process` | 2 | 2 |

**Actualización (20 de octubre de 2026):** las plantillas de kube-vip ahora llevan `KUBERNETES_SERVICE_HOST=127.0.0.1` y `KUBERNETES_SERVICE_PORT` (el puerto de la API de cada distribución) para que la elección de líder dependa del apiserver del propio nodo y la VIP migre al fallar su proceso; con la configuración original la VIP no migró en K3s. Las pruebas de esta evidencia (humo de k6, `svc_election`) se hicieron con la configuración original y no se repitieron; ver `evidencia_T-19.md`.

## 3. Interpretación (no verificada)

- Que el líder cambie entre corridas de MicroK8s (nodo 1 y luego nodo 3) parece depender de qué pod de kube-vip toma el *lease* primero al arrancar; no lo investigué.
- La memoria máxima observada (7 MB a unas 875 solicitudes por segundo reales, `nr_throttled` 0) no representa el uso a la tasa de saturación; los 128 MiB siguen siendo un margen conservador. La saturación real se determina en T-20.5.
- Que el salto adicional por VXLAN cambie el consumo o la latencia no lo medí; las latencias de K3s y MicroK8s en 2.7 salen de una sola corrida cada una y no las comparo.
- Las latencias de la prueba de humo (K3s 837 µs, MicroK8s 723 µs) provienen de una corrida de 30 s a baja tasa; no son comparables entre distribuciones.

## 4. Decisiones, hallazgos y desviaciones

### 4.1 Errores encontrados y corregidos durante la ejecución

1. **Orden de los *plays***: puse `nginx_referencia` en el *play* del nodo 1, que corre antes de que `node2` se una. Con `nodeSelector` al nodo 2, el pod quedó `Pending` y la espera del *rollout* agotó sus 3 intentos. Moví el rol a un tercer *play* (`hosts: <distribución>-node1`) que corre después de unir los nodos, en ambos playbooks.

### 4.2 Decisiones tomadas

- **Mecanismo de la IP `.150`**: anotación `kube-vip.io/loadbalancerIPs` en el Service, sin `kube-vip-cloud-provider`. Según la documentación de kube-vip, funciona desde la 0.5.12 y el observador solo anuncia un Service cuando esa anotación (o `spec.loadBalancerIP`) está poblada. Ventajas: un componente menos y el mismo mecanismo en K3s y MicroK8s. Desventaja: la IP queda en el manifiesto y no en un pool central.
- **`svc_enable: "true"` y `svc_election: "false"`**: se activó solo `svc_enable`; `svc_election` queda como estaba.
- **kube-vip actualizado a v1.2.4** (antes v0.8.9): decidí la 1.2.4 y no la 1.3.0 porque esta se publicó hace 2 días y declara un cambio incompatible. Lo hice antes de la calibración (T-20.5) para no cambiar el componente de HA después de medir.
- **`svc_election` queda en `"false"`, decisión definitiva**: con `"false"` un solo líder sostiene la `.100` y la `.150`, lo que deja inequívoco el nodo al que apunta el protocolo de fallo controlado; con `"true"` cada Service tiene su propio titular, que cambia al reiniciar un pod (2.7). Con esto no verifico el efecto del salto por VXLAN ni por qué el líder difiere entre distribuciones. El valor es la variable `kube_vip_svc_election` de los `group_vars`.
- **Fuente única con variables**: `k8s/nginx-deployment.yaml.j2` y `k8s/nginx-service.yaml.j2` se renderizan con Ansible (`template`) en ambas distribuciones. La plantilla es única; solo difiere `app_node` (`k3s-node2` / `microk8s-node2`, el nombre de host de cada inventario).
- **Límite de CPU como variable**: `nginx_cpu_limit: "500m"` (provisional hasta T-20.5). La solicitud de CPU es igual al límite, igual que la memoria (128 MiB), por lo que la clase QoS es `Guaranteed`.
- **Endpoints**: `/` (HTML mínimo) y `/healthz` (respuesta fija `ok`), por `ConfigMap` idéntico en ambas distribuciones. Sin endpoint de costo computacional.
- **`access_log off` en NGINX** para que el registro no añada escritura de logs a la medición.
- **`allocateLoadBalancerNodePorts: false`** en el Service: kube-vip no usa NodePorts.
- **`readinessProbe` en `/healthz`**, sin `livenessProbe`, para que un reinicio automático no altere una medición.
- **Sin almacenamiento externo al host**: el respaldo de snapshots y resultados de k6 es el repositorio (`data/` versionado); no habrá copia fuera del equipo.
- **k6 anclado a las CPU 0 y 1** con `taskset` (núcleo 0, reservado fuera del mapeo de las VMs).
- **Parámetros de k6 por variables de entorno**: `TASA` es obligatoria y no tiene valor por defecto; `RAMPA_S`, `ESTABLE_S` y `DESCENSO_S` valen 30, 180 y 30 por defecto (las fases del diseño); `PRE_VUS=50` y `MAX_VUS=200` son valores por defecto provisionales que no calibré; `DISTRIBUCION`, `ESCENARIO` y `REPETICION` los toma `correr.sh`.
- **Nombres de resultados**: `data/humo/<distribución>_<escenario>_r<NN>.json.gz` y `.resumen.json`; `r00` marca las pruebas de humo. El JSON se escribe comprimido porque `data/` se versiona. El escritor de metadatos con el mismo esquema (`data/<tipo>/<sesión>/metadatos/<distribución>_<escenario>_r<NN>.json`) queda para T-32.1.

### 4.3 Desviaciones respecto del prompt y del diseño

- El prompt nombra el nodo como «nodo-2»; en el inventario se llama `k3s-node2` / `microk8s-node2`.
- `idle.js` no es solo «sin tráfico»: usa 1 VU que duerme durante la suma de las tres fases, para que la línea de tiempo coincida con la de los otros escenarios.
- No hubo cambios al diseño cerrado de la Etapa 2.

## 5. Limitaciones

- Una sola corrida de humo por clúster; sin repeticiones ni carga cercana a la saturación.
- El uso de memoria de NGINX se midió una vez por clúster, a unas 875 solicitudes por segundo.
- Probé `svc_election: "true"` solo con el borrado de un pod de kube-vip y una vez por clúster; no probé la caída del proceso de la distribución ni de un nodo completo (HU-19).
- El titular de la `.100` y de la `.150` no está controlado: difiere entre corridas (en MicroK8s: nodo 1 y luego nodo 3), y con él cambia si el tráfico hace un salto por VXLAN.
- Amenaza a la validez: el camino de red de la `.150` depende de qué nodo toma el *lease* de kube-vip al arrancar, que no está controlado; si ese nodo no es el del pod, hay un salto adicional por VXLAN. No medí su efecto; los metadatos de T-32.1 registrarán el dato.
- Los servicios del host (Prometheus, Scaphandre, Node Exporter) no están anclados a CPU: comparten el núcleo 0 con k6 y también pueden ejecutarse en otros núcleos. Los hilos del emulador de QEMU tampoco están anclados (`vcpupin` fija solo los vCPU). Por lo tanto el aislamiento de k6 no es completo.
- Un cambio en el `ConfigMap` no reinicia el pod (los archivos se montan con `subPath`); hay que ejecutar `rollout restart`.
- Las tareas no idempotentes de `k3s_server` y `microk8s_server` siguen fuera de alcance.
- Versiones de NGINX y k6 consultadas el 18 de octubre; el digest de NGINX se verificó al desplegar, pero no comparé la suma de verificación del tarball de k6 con una segunda fuente además del archivo `checksums.txt` del release.

## 6. Pendiente

1. Calibración de tasas (media y alta) y del límite de CPU en T-20.5.
2. Resiliencia (HU-19). `chrony` (HU-34), el orquestador y el escritor de metadatos (T-32.1) quedaron hechos después; ver `evidencia_T-34.md`. El escritor de T-32.1 debe incluir `nodo_vip_plano_control`, `nodo_vip_servicio` y `nodo_pod` (esquema en `data/README.md`).
3. Ingresar las horas reales de T-18.1 a T-18.5 en la hoja (no se estiman).
4. Hacer commit con esta evidencia (sección 7).

## 7. Archivos asociados a esta evidencia

| Archivo | Contenido |
|---|---|
| `k8s/nginx-deployment.yaml.j2`, `k8s/nginx-service.yaml.j2` | `ConfigMap` + `Deployment` y Service LoadBalancer |
| `k3sHA/ansible/roles/nginx_referencia/`, `microk8sHA/ansible/roles/nginx_referencia/` | Despliegue en cada distribución |
| `k3sHA/ansible/group_vars/all.yml`, `microk8sHA/ansible/group_vars/all.yml` | `nginx_image`, `nginx_cpu_limit`, `nginx_cpu_request`, `nginx_memory`, `app_node`, `lb_ip`, `kube_vip_version`, `kube_vip_svc_election` |
| `k3sHA/ansible/playbook.yml`, `microk8sHA/ansible/playbook.yml` | *Play* 3 con `nginx_referencia` |
| `k3sHA/ansible/roles/kube_vip/templates/kube-vip.yaml.j2`, `microk8sHA/ansible/roles/kube_vip/templates/kube-vip.yaml.j2` | `svc_enable: "true"` |
| `ansible/roles/k6/`, `ansible/group_vars/all.yml`, `ansible/playbook.yml` | Instalación de k6 en el host |
| `k6/common.js`, `k6/idle.js`, `k6/media.js`, `k6/alta.js`, `k6/correr.sh` | Escenarios y lanzador |
| `data/README.md`, `data/humo/` | Esquema de nombres y resultados de las pruebas de humo |
| `.gitignore` de `data/` | Ya no ignora el contenido |
| este documento | Resumen de hechos, interpretaciones, decisiones y pendientes |

## 8. Criterio de aceptación

- T-18.1 «NGINX de referencia»: cumplido en K3s y MicroK8s (imagen con tag y digest, 1 réplica, límites explícitos, QoS `Guaranteed`, mismo manifiesto).
- T-18.2 «Acceso y endpoints»: cumplido; `/` y `/healthz` responden `200` desde el host por `192.168.100.150:80` en ambos clústeres.
- T-18.3 «Scripts de k6»: cumplido para los tres escenarios; probados `media` e `idle` en ambos clústeres; `alta.js` comparte código con `media.js` y no se ejecutó por separado.
- T-18.4 «Organización de resultados»: cumplido con el esquema de nombres de la sección 4.2; el escritor de metadatos (T-32.1) quedó hecho después en `k6/orquestador.py` (`evidencia_T-34.md`).
- T-18.5 «Service LoadBalancer con kube-vip»: cumplido en `192.168.100.150`, con la VIP `.100` respondiendo (`401` sin credenciales) en ambos clústeres.

Commits previstos: (1) cierres de HU-17, (2) T-18.1, T-18.2 y T-18.5, (3) T-18.3 y T-18.4, (4) documentación y README.
