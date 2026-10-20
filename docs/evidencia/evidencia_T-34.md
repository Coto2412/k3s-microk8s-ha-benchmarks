# Evidencia de HU-34 (T-34.1 a T-34.3) y T-32.1: sincronización de relojes con chrony y orquestador de repeticiones

Fecha: 18 de octubre de 2026. Las salidas provienen de mi terminal en el host (ThinkPad). Probé un clúster a la vez: primero K3s y, tras destruirlo, MicroK8s; ambos quedaron destruidos al terminar (`virsh list --all` muestra solo `minione`). El playbook del host lo ejecuté yo con `--ask-become-pass`; los de las VMs, por SSH con la llave del proyecto. Las ejecuciones del orquestador son de verificación de 20 s en la fase estable: no son repeticiones válidas ni un piloto. Todo se hizo con la sesión gráfica abierta; no son condiciones de ejecución definitiva.

Convención: la sección 2 contiene hechos medidos u observados; la 3, interpretaciones no verificadas; la 4, decisiones, hallazgos y desviaciones; la 5, limitaciones; la 6, lo pendiente; la 7, los archivos asociados; la 8, el criterio de aceptación.

## 1. Alcance y condiciones

| Parámetro | Valor |
|---|---|
| Tareas cubiertas | T-34.1 (host como fuente NTP), T-34.2 (VMs como clientes solo de `192.168.100.1`), T-34.3 (verificación con `chronyc` y desfase medido entre nodos) y T-32.1 (orquestador de una repetición y escritor de metadatos) |
| Correcciones de documentación incluidas | titular de la VIP entre corridas de MicroK8s (`README.md` sección 13, `data/README.md`, `evidencia_T-18.md`) y estado real de chrony y del orquestador en los README |
| Fuera de alcance | calibración de tasas (T-20.5), caracterización del reposo del host (T-20.7), aislamiento de CPU (T-21.5), tratamiento del titular de la VIP (T-19.5), repeticiones válidas de la campaña |
| Host | Lenovo ThinkPad T14 Gen 2A, Ubuntu 24.04 (ver `evidencia_T-16.md`, sección 1) |
| Clústeres probados | K3s `v1.36.3+k3s1` y MicroK8s `v1.36.2`, uno a la vez |
| Red | VMs `192.168.100.11` a `.13`, VIP del plano de control `.100`, VIP del Service `.150`, host `.1` |
| Versión de chrony | `4.5-1ubuntu4.2` (paquete `chrony` de apt en el host y en las VMs) |

## 2. Hechos medidos u observados

### 2.1 Instalación e idempotencia

- Host: `apt` instaló `chrony 4.5-1ubuntu4.2` y retiró `systemd-timesyncd` (estado `rc`: paquete quitado, configuración residual); `chrony` queda `active` y `systemd-timesyncd` `inactive`.
- Playbook del host en siete ejecuciones: `ok=47 changed=9`, `ok=46 changed=3` (al cambiar la etiqueta `distribution` a MicroK8s), `ok=45 changed=1` (repetición), una cuarta sin tareas modificadas en el filtro pero sin `PLAY RECAP` capturado, y tres más con la distribución `k3s` (la primera sin `PLAY RECAP` capturado, la segunda con `ok=45 changed=1` y la tercera, tras corregir el rol `operador_host`, con `ok=45 changed=0 skipped=5`). La `changed=1` constante era la tarea de ACL recursiva de `operador_host`, que reporta cambio en cada pasada; la sustituí por una comprobación previa con `getfacl` y la ACL solo se aplica si falta (167 de 167 archivos ya con el permiso). `changed=0` está medido solo en esa última ejecución.
- VMs de K3s, primera ejecución: `ok=59 changed=32` (nodo 1), `ok=50 changed=27` (nodo 2) y `ok=48 changed=27` (nodo 3); es el despliegue completo desde cero.
- VMs de MicroK8s, segunda pasada del playbook completo: nodo 1 `changed=4`, nodos 2 y 3 `changed=1`. Las tareas que cambiaron fueron `microk8s_server : Apuntar kubeconfig al VIP`, `Configurar snap_refresh_timer en el snap microk8s` (2), `Guardar kubeconfig en el usuario` y `Habilitar dns y storage en microk8s`; **ninguna es del rol `chrony`**. Son las tareas no idempotentes de `microk8s_server` ya documentadas como fuera de alcance.
- VMs de K3s, ciclo repetido el 19 de octubre (`terraform init` y `apply`, playbook y segunda pasada): primera pasada `ok=59 changed=32` (nodo 1), `ok=50 changed=27` y `ok=48 changed=27`; segunda pasada nodo 1 `ok=53 changed=2`, nodos 2 y 3 `changed=0`. Las dos tareas modificadas fueron `k3s_server : Copiar kubeconfig de k3s al usuario` y su *handler* `Actualizar servidor en kubeconfig`; ninguna es del rol `chrony`, cuyas tareas salieron `ok` en los tres nodos. La idempotencia del rol `chrony` en VMs queda verificada en K3s y MicroK8s; el clúster K3s se destruyó al terminar.
- `ufw` del host: `sudo ufw status verbose` indica `Estado: inactivo`. El rol agrega `allow udp from 192.168.100.0/24 to 192.168.100.1 port 123` solo si `ufw` está activo, así que **la regla no existe hoy y las VMs sincronizan sin ella** porque no hay firewall activo. La condición buscaba el texto `Status: active`, pero el sistema está en `es_CL.UTF-8` y `ufw` responde `Estado: activo`; con `ufw` activo la regla se habría omitido sin aviso. Corregí la tarea con `LC_ALL=C`. **La regla de UDP 123 nunca se ha aplicado ni probado.**

### 2.2 Configuración resultante

Host (`/etc/chrony/chrony.conf` de Ubuntu más `conf.d/tesis.conf`):

```
allow 192.168.100.0/24
local stratum 10
```

El host mantiene las fuentes de Ubuntu (`pool ntp.ubuntu.com` y `*.ubuntu.pool.ntp.org`), `makestep 1 3`, `rtcsync` y `maxupdateskew 100.0`.

VMs de ambas distribuciones (`/etc/chrony/chrony.conf`, idéntico en K3s y MicroK8s):

```
server 192.168.100.1 iburst
driftfile /var/lib/chrony/chrony.drift
makestep 1 3
rtcsync
keyfile /etc/chrony/chrony.keys
logdir /var/log/chrony
```

Las VMs no tienen `pool` ni `sourcedir`; la única fuente es `192.168.100.1`.

### 2.3 `chronyc` en las VMs (T-34.3)

K3s, 22:03 UTC (el host ya en estrato 3):

| VM | Fuente | Estrato de la VM | `System time` | `Last offset` | `RMS offset` |
|---|---|---|---|---|---|
| `.11` | `^* 192.168.100.1` | 4 | 0,98 ms adelantado | +1,23 ms | 5,62 ms |
| `.12` | `^* 192.168.100.1` | 4 | 0,088 ms adelantado | +0,069 ms | 14,19 ms |
| `.13` | `^* 192.168.100.1` | 4 | 1,08 ms atrasado | −0,90 ms | 12,65 ms |

MicroK8s, 22:27 UTC:

| VM | Fuente | Estrato de la VM | `System time` | `Last offset` | `RMS offset` |
|---|---|---|---|---|---|
| `.11` | `^* 192.168.100.1` | 4 | 0,020 ms atrasado | −0,122 ms | 1,35 ms |
| `.12` | `^* 192.168.100.1` | 4 | 0,004 ms atrasado | −0,155 ms | 0,39 ms |
| `.13` | `^* 192.168.100.1` | 4 | 0,100 ms adelantado | +0,143 ms | 0,40 ms |

En las seis VMs `chronyc sources` lista únicamente `192.168.100.1`, `timedatectl` indica `NTPSynchronized=yes` y `systemd-timesyncd` aparece `inactive` y desinstalado (estado `rc`).

### 2.4 Desfase medido entre nodos y host

Método: `analysis/verificacion/desfase_relojes.py` mantiene una sesión SSH persistente por VM, lee `date +%s.%N` en la VM y toma el desfase como la hora de la VM menos el punto medio de las lecturas del host antes y después de la consulta; la cota es RTT/2. Son 30 sondas por VM. Los números de `chronyc` se reportan aparte: los dos métodos miden cosas distintas (el de `chronyc` es la estimación del propio chrony de la VM).

| Instante (UTC) | Estado del host | Desfase mediano VM `.11` / `.12` / `.13` (ms) | Cota mediana (ms) |
|---|---|---|---|
| K3s, 21:54 | recién arrancado, `Stratum 10` (referencia local) | −12,2 / −40,7 / −30,0 | 1,2 |
| K3s, 21:59 | `Stratum 3` | +1,0 / −1,9 / +7,4 | 1,5 a 2,0 |
| K3s, 22:03 | `Stratum 3` | +4,6 / +4,6 / +1,1 | 1,5 a 1,8 |
| MicroK8s, 22:18 | convergido | +0,68 / +0,59 / +0,71 | 1,7 a 1,8 |
| MicroK8s, 22:27 | convergido | +0,60 / +0,61 / +0,43 | 1,8 a 1,9 |

En las dos mediciones de MicroK8s el desfase máximo observado entre sondas fue de 2,6 ms (VM `.12`, 22:27), con una cota de RTT/2 de hasta 3,8 ms en la peor sonda. Con la cota de 1,7 a 1,9 ms, **la medición es consistente con un desfase de la VM respecto del host menor a unos 2 ms en MicroK8s, pero no resuelve diferencias por debajo de esa cota**. En K3s medí desfases de hasta 41 ms mientras el host aún no había convergido (primera fila); y de hasta 7,4 ms con el host en estrato 3.

Entre mediciones tomadas durante la convergencia del host (21:56, tres rondas de una sola lectura cada una) los desfases fueron de −5 a −39 ms; las dejo como observación, no como medición validada.

### 2.5 Estado del host durante la convergencia

- Justo tras arrancar chrony en el host (21:47 y 21:53 UTC): `Reference ID 7F7F0101`, `Stratum 10` (referencia local, ningún upstream seleccionado), con ocho fuentes Ubuntu/pool visibles y alcanzabilidad creciente (`Reach` 17 y luego 377).
- `chronyc sourcestats` del host a las 21:53: `Freq Skew` entre 125 y 566 ppm en las fuentes upstream, y offsets individuales de hasta ±76 ms.
- A las 21:59 el host aparece con `Stratum 3`, es decir, ya sincronizado con un upstream.
- Las VMs, que apuntan a `192.168.100.1`, mostraron en ese lapso `Stratum 11` y luego `4`.

### 2.6 Orquestador (T-32.1)

`k6/orquestador.py` ejecutó cuatro verificaciones cortas (rampa 5 s, estable 20 s, descenso 5 s), con 50 solicitudes por segundo en `media`, `--estabilizacion 10` y `--verificacion`, que prefija el nombre con `verif_`:

| Corrida | Potencia media RAPL en la ventana (W) | Titular `.100` / `.150` al inicio y al fin | Nodo del pod | Primer punto del JSON de k6 tras el lanzamiento (s) |
|---|---|---|---|---|
| `verif_k3s_media_r00` | 6,708 | `k3s-node1` / `k3s-node1`, sin cambio | `k3s-node2` | 0,482 |
| `verif_k3s_idle_r00` | 4,870 | `k3s-node1` / `k3s-node1`, sin cambio | `k3s-node2` | 1,014 |
| `verif_microk8s_media_r00` | 5,219 | `microk8s-node3` / `microk8s-node3`, sin cambio | `microk8s-node2` | 0,630 |
| `verif_microk8s_idle_r00` | 5,016 | `microk8s-node3` / `microk8s-node3`, sin cambio | `microk8s-node2` | 1,029 |

- Las ventanas duraron 20,0 s (`t_fin − t_inicio`). Dos lecturas RAPL de cada corrida tardaron entre 11 y 20 ms. Estos valores de potencia vienen de 20 s con la sesión gráfica abierta: **no los comparo entre distribuciones ni los uso como resultado**.
- Los titulares del orquestador coincidieron con los *leases* `plndr-cp-lock` y `plndr-svcs-lock` y con la anotación `kube-vip.io/vipHost` del Service en ambos clústeres (verificación manual).
- La lectura RAPL usa `max_energy_range_uj = 65532610987`; la fórmula de desbordamiento (`b − a` si `b ≥ a`, si no `b − a + máximo`) pasa un autotest (`k6/orquestador.py --autotest`). **Ninguna corrida tuvo desbordamiento real**; la rama no se ejercitó con hardware.
- Tamaños medidos: `.json.gz` de `media` (50 solicitudes por segundo, 30 s) de 173 066 B en K3s y 179 506 B en MicroK8s; de `idle`, unos 1,8 kB. Eso da 138,6 B por solicitud en K3s y 143,7 B en MicroK8s (1249 solicitudes cada una); junto con las dos pruebas de humo de T-18 (133 a 139 B) el rango medido es de 133 a 144 B, y uso 144 B (el máximo) para estimar.
- Snapshots de Prometheus: son copias completas de la TSDB y crecieron entre corridas (2,1 MB, 2,7 MB y 5,2 MB observados; `du` redondea a 3 o 6 MB en el repositorio). `data/` pesaba 36 MB al terminar.
- El aviso de tamaño del orquestador se probó con `--tasa 5000`: imprimió `AVISO: el JSON de k6 estimaría 151 MB` y se detuvo después, porque la distribución pedida (`k3s`) no coincidía con la etiqueta de Prometheus (`microk8s`); no creó archivos.

- Después de cambiar el orquestador (aviso de tamaño y comprobación de `up`), lo probé otra vez en K3s con una verificación corta (`--sin-snapshot`): el campo `k6.tamano_json_bytes` quedó en 173 408 B y los titulares no cambiaron. Descarté esos archivos de prueba y no los versioné.
- Hallazgo: al cambiar la etiqueta `distribution` con el playbook del host, Prometheus sigue devolviendo en `up` las series de la etiqueta anterior mientras dure su ventana de 5 min, y el orquestador abortaba con «Prometheus etiqueta ['k3s', 'microk8s']». Cambié la consulta a `last_over_time(up[30s])`, que solo ve series con muestras de los últimos 30 s; con eso la verificación pasó sin esperar.

### 2.7 Corrección de `continuidad.py`

`analysis/verificacion/continuidad.py` calculaba el rango de `up` como `up[{int(dt)}s]`. Para una ventana de 19,998 s consultaba `up[19s]` y obtenía 1 de 2 muestras en el job del host (cobertura 0,500). Cambié a `math.ceil(dt)` y filtré las muestras al intervalo `[t0, t1]`. Re-verifiqué las ventanas de las cuatro corridas `verif_*` (2/2 en todos los targets) y el piloto de T-17.4 en K3s (120/120). No cambia los resultados de HU-17.

## 3. Interpretación (no verificada)

- Que el host tarde unos 10 a 15 minutos en pasar de estrato 10 a 3 parece venir del ruido de las fuentes upstream (`Freq Skew` alto), pero no verifiqué que `maxupdateskew 100.0` sea la causa.
- Que el desfase de unos 5 a 40 ms de K3s coincida con ese lapso de convergencia del host es una correlación temporal; no la probé de forma independiente.
- Que los 0,4 a 0,7 ms de MicroK8s sean desfase real y no sesgo del método (asimetría del camino SSH) no lo puedo separar: la cota de RTT/2 es de 1,7 a 1,9 ms.
- Que las 20 s de las corridas de verificación basten para el orquestador no implica que basten para la campaña (ver 5).

## 4. Decisiones, hallazgos y desviaciones

### 4.1 Errores encontrados y corregidos durante la ejecución

1. **Truncamiento en `continuidad.py`**: descrito en 2.7.
2. **Desfase aparente mal atribuido**: la primera medición en K3s (−12, −41 y −30 ms) no calzaba con lo que reportaba `chronyc` en las VMs; coincidía con el host recién arrancado en referencia local. Lo registro tal cual y no lo reporto como desfase del diseño.
3. **ACL recursiva no idempotente** en `operador_host`: reportaba `changed` en cada pasada. La apliqué solo si una comprobación con `getfacl` encuentra archivos sin el permiso.
4. **Condición de `ufw` dependiente del idioma**: buscaba `Status: active` y el sistema responde en español. Corregido con `LC_ALL=C`; no se pudo probar con `ufw` activo.
5. **Consulta de `up` del orquestador** veía series de la etiqueta anterior tras cambiar de distribución: acotada a los últimos 30 s (2.6).

### 4.2 Decisiones tomadas

- **Host como servidor y como cliente**: conserva sus fuentes de Ubuntu. El diseño dice que el host es «fuente de referencia»; sin salida a Internet no tendría hora fiable. Si más adelante decido medir con el host sin fuentes externas, hay que desactivarlas; no lo decidí todavía (T-20.7).
- **`local stratum 10`** en el host para servir hora aunque se pierda el upstream.
- **VMs sin `pool` ni `sourcedir`**: el archivo de configuración se escribe completo, no se agrega a lo existente. Por eso `chronyc sources` muestra una sola fuente.
- **`systemd-timesyncd`**: lo retira `apt` al instalar `chrony`; no lo desactivo aparte.
- **Regla de `ufw` condicionada** a que el firewall esté activo (con `LC_ALL=C`), limitada a UDP 123 desde `192.168.100.0/24` hacia `192.168.100.1`; sin probar porque `ufw` está inactivo en el host.
- **Acceso del orquestador sin ejecutarlo como root** (rol `operador_host`): ACL de lectura sobre el directorio de datos de Prometheus (para copiar el snapshot) y una regla de `sudoers` que permite solo `/usr/bin/cat /sys/class/powercap/intel-rapl\:0/energy_uj` sin contraseña. Es la única ampliación de permisos del host.
- **Método de titular verificable**: el host hace `ping` a la VIP y a cada nodo, lee la MAC desde `ip neigh` y la asocia a la única IP de nodo con esa MAC; el nombre del nodo sale de `kube_node_info`. Si la MAC no calza con exactamente una IP, el campo dice `no determinado`. El nodo del pod sale de `kube_pod_info`.
- **Metadatos**: `data/metadatos/<base>.json` con `t_inicio` y `t_fin` de la fase estable (puntos medios de las lecturas RAPL), los de la ejecución completa, los dos valores crudos de `energy_uj`, `max_energy_range_uj`, el desborde, el delta y los titulares al inicio y fin (esquema completo en `data/README.md`).
- **Estabilización**: el orquestador espera `--estabilizacion` segundos (60 por defecto, **provisional**) y aborta si Prometheus no tiene exactamente los 7 targets en `up`, si la etiqueta `distribution` no es la pedida o si la VIP `.150` no responde 200.
- **No sobrescribe** archivos existentes de la misma repetición.

### 4.3 Desviaciones respecto del prompt y del diseño

- `chrony` no está fijado por versión: apt de Ubuntu 24.04 solo ofrece `4.5-1ubuntu4.2`, igual que en el resto del proyecto para paquetes de apt. La versión instalada queda documentada aquí.
- El diseño pide NTP «solo hacia `.1`» en las VMs; se cumple. No hay diferencia entre K3s y MicroK8s en el rol `chrony`: los dos roles son idénticos archivo por archivo.
- La estabilización por defecto de 60 s no garantiza reloj convergido tras reconstruir las VMs (ver 5).
- No hubo cambios al diseño cerrado de la Etapa 2.

## 5. Limitaciones

- Una sola medición de desfase por instante y por distribución, con 30 sondas; cota de 1,7 a 1,9 ms. No medí la deriva a lo largo de una ventana de 3 minutos ni de una repetición completa.
- La convergencia del reloj tras reconstruir las VMs no está cubierta por la estabilización del orquestador. `node_exporter` está configurado sin el colector `timex`, por lo que no se puede comprobar el desfase desde Prometheus. Queda abierto para T-20.7.
- Las ventanas de 20 s son demasiado cortas para el criterio de continuidad de la campaña (≥ 99 % de las muestras sin huecos mayores a 30 s); `continuidad.py` solo las valida aquí.
- El orquestador se probó una vez por distribución y escenario, sin repeticiones, sin fase de fallo y sin rama de desbordamiento ejercitada.
- El titular de la VIP no está controlado: en MicroK8s fue el nodo 1 (kube-vip `v0.8.9`) y luego el nodo 3 (`v1.2.4`) en los dos ciclos de T-18, y de nuevo el nodo 3 en este; en K3s fue el nodo 1 en los tres ciclos. Con tres ciclos por distribución no hay base para afirmar que sea determinista. El orquestador lo registra, no lo corrige.
- El método de ARP depende de la caché del vecino del host; el `ping` previo la refresca, pero no probé qué pasa si hay un cambio de titular justo entre el `ping` y la lectura.
- El desbordamiento de RAPL se maneja para un solo desbordamiento por ventana.
- Los snapshots son copias completas: tomar uno por repetición duplica el historial y el repositorio crece con cada una. Con 10 repeticiones esperadas no medí el tamaño final.
- Tamaño de `data/` por repetición, estimado con 144 B por solicitud: JSON de k6 de unos 61 MB a 2000 solicitudes por segundo en la fase estable, unos 91 MB a 3000 y unos 151 MB a 5000 (ventana de 210 s equivalentes: 15 s de rampa, 180 s estables y 15 s de descenso). **Por encima de unos 3300 solicitudes por segundo el archivo supera los 100 MB de GitHub.** La tasa de saturación aún no se calibró (T-20.5). El orquestador avisa por stderr cuando la estimación previa o el tamaño real pasa del 80 % del límite, y guarda el tamaño real en los metadatos (`k6.tamano_json_bytes`). Esa estimación es una extrapolación de cuatro mediciones a 50 solicitudes por segundo o menos; no la verifiqué a esas tasas.
- Los servicios del host no están anclados a CPU (aislamiento incompleto de k6, ya documentado en `evidencia_T-18.md`).

## 6. Pendiente

1. T-19.5: decidir cómo tratar el titular de la VIP (se registra pero no se controla) y revalidar su migración con kube-vip `v1.2.4`.
2. T-20.7: caracterizar el reposo del host y definir si el chrony del host debe tener fuentes externas durante mediciones; agregar un criterio de reloj convergido antes de lanzar k6 (por ejemplo `chronyc tracking` en las VMs y el host, o el colector `timex`).
3. T-20.5: calibrar la tasa de saturación, que fija el tamaño real del JSON de k6.
4. Decidir qué hacer con los snapshots de Prometheus (uno por repetición o uno por bloque) antes de la campaña.
5. Ingresar las horas reales de T-34 y T-32.1 en la hoja (no se estiman).
6. Hacer commit con esta evidencia (sección 7).

## 7. Archivos asociados a esta evidencia

| Archivo | Contenido |
|---|---|
| `ansible/roles/chrony/` | Servidor NTP del host, regla de `ufw` y arranque |
| `k3sHA/ansible/roles/chrony/`, `microk8sHA/ansible/roles/chrony/` | Cliente NTP de las VMs (idénticos) |
| `ansible/roles/operador_host/` | ACL de lectura sobre los datos de Prometheus y `sudoers` para `energy_uj` |
| `ansible/group_vars/all.yml`, `ansible/playbook.yml` | `chrony_red_vms`, `chrony_ip_host`, `operador_host` y los roles nuevos |
| `k3sHA/ansible/group_vars/all.yml`, `microk8sHA/ansible/group_vars/all.yml`, ambos `playbook.yml` | `chrony_servidor` y el rol `chrony` |
| `k6/orquestador.py` | Orquestador de una repetición y escritor de metadatos |
| `analysis/verificacion/desfase_relojes.py` | Medición del desfase de las VMs respecto del host |
| `analysis/verificacion/continuidad.py` | Corrección del rango de la consulta |
| `data/metadatos/verif_*.json`, `data/k6-resultados/verif_*`, `data/prometheus-snapshots/` | Salidas de las cuatro verificaciones y sus snapshots |
| `data/README.md`, `README.md`, `k3sHA/README.md`, `microk8sHA/README.md` | Estado real documentado |
| este documento | Resumen de hechos, interpretaciones, decisiones y pendientes |

## 8. Criterio de aceptación

- T-34.1 «Servidor NTP en el host»: cumplido; `chrony` activo y `allow 192.168.100.0/24`. La regla de `ufw` para UDP 123 está escrita pero no aplicada: `ufw` está inactivo.
- T-34.2 «VMs como clientes de `.1`»: cumplido en K3s y MicroK8s; fuente única `192.168.100.1`, `systemd-timesyncd` retirado, rol `chrony` sin tareas modificadas en la segunda pasada de ambas distribuciones.
- T-34.3 «Verificación»: cumplido con `chronyc tracking` y `chronyc sources` en el host y en las VMs de ambas distribuciones, y desfase medido con cota de 1,7 a 1,9 ms. Reporto solo lo medido; el desfase tras la convergencia del host fue menor a unos 2 ms en MicroK8s y de hasta 7,4 ms en K3s con el host recién sincronizado.
- T-32.1 «Orquestador»: funciones verificadas en ambas distribuciones con repeticiones de 20 s en la fase estable. **No se ha ejecutado una repetición con las fases del diseño (30 s, 180 s, 30 s)**, que el criterio llama «repetición completa»; queda pendiente, y el criterio de estabilización sigue provisional.

Commit: uno con los tres bloques (chrony, orquestador y correcciones de documentación). La repetición de duración completa de T-32.1 y T-19 van en un commit posterior.
