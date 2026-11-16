# Evidencia E1 y E2 (Etapa 4): etiqueta `distribution` sin playbook y ayudantes de root

Estado al 16-nov-2026. Preparan la ejecución desatendida de la campaña (T-24.1, T-24.2). Se aplican al host con un solo playbook, fuera del modo medición.

## 1. E1 · Etiqueta `distribution` con `file_sd_configs`

**Problema.** La etiqueta salía de `active_distribution` en la plantilla de Prometheus. Cambiarla exigía el playbook del host con contraseña y luego `salir`/`entrar` del modo medición, 16 veces en la campaña. En los pilotos, esas reconfiguraciones coincidieron con los cambios de nivel de potencia.

**Cambio.**

| Archivo | Qué cambió |
|---|---|
| `ansible/roles/prometheus/templates/prometheus.yml.j2` | Los cinco trabajos leen sus objetivos de `/etc/prometheus/objetivos/<trabajo>.json` (`file_sd_configs`, `refresh_interval: 30s`). Se quitó `external_labels`. Los filtros `keep` de `scaphandre` y `prometheus` no cambian. |
| `ansible/group_vars/all.yml` | `prometheus_objetivos_dir` y `prometheus_trabajos` (objetivos y etiquetas `role` de cada trabajo, antes escritos en la plantilla). `active_distribution` queda solo como valor inicial de los archivos. |
| `ansible/roles/prometheus/tasks/main.yml` | `/etc/prometheus` pasa de `0750` a `0751` (el operador atraviesa el directorio, sin listarlo ni leer `prometheus.yml`). Directorio de objetivos con dueño el operador, grupo `prometheus` y `2750` (setgid: los archivos nuevos heredan el grupo). Archivos de objetivos `0640`. |
| `k6/operacion/etiqueta.py` | Comando nuevo (sección 1.1). |
| `k6/lib/comun.py`, `k6/operacion/validacion.py` | El mensaje de la precondición de la etiqueta apunta al comando nuevo. La comprobación no cambia. |
| `README.md` | Sección «Preparar el host». |

### 1.1 `python3 -m k6.operacion.etiqueta --distribucion <dist> [--diario ruta.jsonl]`

1. Reescribe cada `*.json` del directorio con `labels.distribution = <dist>`. Escribe a `<archivo>.tmp` (fuera del patrón que lee Prometheus), `fsync` y `os.replace`, así que Prometheus nunca lee un archivo a medias.
2. Espera a que `/api/v1/targets` muestre la etiqueta nueva en los 7 objetivos activos y luego a que `up{distribution="<dist>"}` devuelva 7 series (un scrape más). El límite es de 90 s.
3. Imprime una línea JSON con `t_escritura`, `t_api`, `t_up`, duración y resultado. Con `--diario`, la agrega al archivo. Sale con 1 si se agota el límite.

Prometheus relee los archivos por inotify, sin reiniciar ni recargar. El ejecutor de la campaña (E5) llamará a `cambiar()` y anotará el resultado en su diario.

**Desviación de la Etapa 2.** El diseño fijaba `distribution` en `external_labels`. Se quita porque no se puede mantener fija con dos distribuciones por jornada. No cambia los datos: `external_labels` nunca quedó en las series locales (`evidencia_T-17.md`, 4.3), y la etiqueta de cada objetivo sigue igual que antes.

### 1.2 Qué probé

En una instancia de Prometheus 3.15.0 aparte (puerto 9091, datos en un directorio temporal), con la configuración renderizada por Ansible desde `group_vars` y las VMs apagadas:

- `promtool check config` acepta la configuración.
- Los archivos generados tienen los mismos objetivos y etiquetas `role` que la configuración anterior.
- Cambios `k3s` → `microk8s` → `k3s`: `resultado: ok` en los tres. La API mostró la etiqueta nueva entre 0,02 y 1,0 s después de escribir, y `up` entre 10 y 18 s después (espera del scrape siguiente).
- Las series con la etiqueta anterior desaparecieron de `up` en menos de 15 s (marcadores de obsolescencia). La precondición del orquestador usa `last_over_time(up[30s])` después de 120 s de estabilización, así que no las ve.

**Qué no probé todavía:** el criterio de aceptación en el host, con las VMs de K3s levantadas (sección 3). Los permisos reales del directorio en `/etc/prometheus` (en la prueba el directorio era mío).

## 2. E2 · Ayudantes de root

Scripts propiedad de root en `/usr/local/sbin/`, instalados por el rol `operador_host`. Regla en `/etc/sudoers.d/tesis-operador`, validada con `visudo`, con el patrón de `tesis-rapl`:

```
<operador> ALL=(root) NOPASSWD: /usr/local/sbin/tesis-preparar-memoria "", /usr/local/sbin/tesis-kvm-stats ""
```

El `""` hace que `sudo` acepte cada script solo sin argumentos. Los scripts además rechazan argumentos. Son Python con `-I` (sin variables de entorno ni rutas del usuario). No hay reglas sobre `sh`, `python3` ni otros intérpretes.

| Script | Qué hace |
|---|---|
| `tesis-preparar-memoria` | `swapoff -a`, `swapon -a` (siempre, aunque `swapoff` falle), `sync` y `3 > /proc/sys/vm/drop_caches`. Imprime JSON con `MemAvailable`, `MemFree`, `Cached`, `SwapTotal` y `SwapFree` antes y después, y la duración de cada paso. Sale con 1 si algún paso falla. |
| `tesis-kvm-stats` | Solo lectura de `/sys/kernel/debug/kvm`: todos los contadores escalares globales y, por VM (`<pid>-<fd>`), los contadores escalares de ese directorio. Agrega el nombre de la VM desde `-name guest=` de QEMU. Omite siempre los histogramas (`*_hist`). Si el directorio no existe o está vacío, imprime `disponible: false` con el motivo y sale con 0. |

**Qué expone el núcleo del host** (`sudo ls /sys/kernel/debug/kvm`, 16-nov, sin VMs): entre otros, `halt_attempted_poll`, `halt_successful_poll`, `halt_poll_success_ns`, `halt_poll_fail_ns`, `halt_poll_invalid`, `halt_wakeup`, `halt_wait_ns`, `halt_exits`, `exits`, `irq_exits` y los histogramas `halt_poll_success_hist`, `halt_poll_fail_hist` y `halt_wait_hist`. Con las VMs encendidas aparecen `<pid>-<fd>/` por VM con subdirectorios `vcpuN/`, que no traen contadores `halt_*`.

**Qué probé antes de aplicar:** `visudo -cf` sobre la regla. `tesis-kvm-stats` sobre un árbol falso y sin root (`disponible: false`). Rechazo de argumentos en los dos. La lectura de `/proc/meminfo`.

## 3. Aplicación en el host y aceptación (16-nov-2026)

El usuario aplicó el playbook del host fuera del modo medición. Luego construí K3s con `despliegue.sh k3s construir 900` (310 s), con `DESPLIEGUE_REGISTRO` y `DESPLIEGUE_LOG` en un directorio temporal, para no tocar el registro versionado. Lo destruí al terminar.

| Comprobación | Resultado |
|---|---|
| Directorio de objetivos | `drwxr-s--- coto prometheus`, 5 archivos `-rw-r----- coto prometheus`; `/etc/prometheus` en `751` |
| `/api/v1/status/config` | sin `external_labels` |
| Reglas de `sudo -n -l` | `tesis-preparar-memoria ""` y `tesis-kvm-stats ""`; con un argumento, `sudo` pide contraseña |
| 6 cambios de etiqueta (`k3s` ↔ `microk8s`) sin `systemctl` ni playbook | todos `ok`; API en 0,02 a 1,03 s, muestra nueva de `up` en los 7 objetivos entre 9,0 y 11,1 s |
| `up{distribution="<dist>"}` tras cada cambio | 7 series con valor 1: host, 3 VMs, Scaphandre, kube-state-metrics y Prometheus |
| `tesis-preparar-memoria` | `ok`; swap 0,027 s, caché 1,094 s; `Cached` de 4,2 a 0,7 GB, `SwapFree` igual a `SwapTotal` |
| `tesis-kvm-stats` | `disponible: true`, 60 contadores globales, 3 VMs con su nombre (`k3s-node1` a `k3s-node3`) |

**Correcciones durante la aceptación:**
- La primera versión del comando aceptaba `up{distribution="k3s"}` 1 s después de volver de `microk8s`, sin haber esperado un scrape nuevo. Ahora exige en los 7 objetivos una muestra de `up` posterior a la escritura (`timestamp(up{...}) > t_escritura`).
- Sin VMs, `halt_poll_fail_hist` se leía como un número y entraba en el JSON. Ahora los `*_hist` se omiten siempre, para que las claves no cambien entre fotos.
- Los `vcpuN/` no traen contadores `halt_*`, así que la versión por vCPU quedaba vacía. Ahora se leen los contadores escalares de `<pid>-<fd>/`. Según el código del núcleo (`virt/kvm/kvm_main.c`), ese directorio suma los contadores de las vCPU de la VM; no lo verifiqué contra la suma de los globales.

**Pendiente:** las dos últimas correcciones de `tesis-kvm-stats` están en el repositorio, pero no instaladas. Se instalan con la próxima aplicación del playbook del host, que E3 o E6 van a requerir. Hasta entonces, la salida por VM no está verificada.

## 4. Límites

- Si se corre el playbook del host de nuevo, los archivos de objetivos vuelven a `active_distribution` (por defecto `k3s`). Después hay que correr `k6.operacion.etiqueta`.
- `tesis-preparar-memoria` puede fallar en `swapoff -a` si el swap ocupado no cabe en la memoria libre; el ejecutor (E5) lo registra como falla del procedimiento.
- El plazo de 90 s del comando es un valor mío (scrape de 10 s y relectura de 30 s como respaldo de inotify).
