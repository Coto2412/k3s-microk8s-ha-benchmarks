# Evidencia T-20: reposo del host, política de servicios, reloj, datos y calibración

Estado al 27-oct-2026. Este documento se completa a medida que ejecuto las mediciones; lo que aún no medí está marcado como pendiente y no lo uso como resultado.

## 1. Alcance y estado

| Tarea | Estado | Qué hay |
|---|---|---|
| T-20.7 política de servicios | Aplicada y usada en todas las corridas de esta evidencia | Rol `ansible/roles/host_mediciones/` (lista blanca); `entrar`/`salir` ejecutados por mí en consola de texto |
| T-20.7 criterio de reloj | Implementado y usado en cada corrida del orquestador y de `calibrar.py` | `k6/estado_host.py`; corregí la comparación por IP (sección 3.4) |
| T-20.7 ufw | Decidido (sección 4) | Sin cambios de código |
| T-20.7 política de datos | Implementada y ejercitada en los pilotos (sección 5) | `k6/agregado.py`, `data/.gitignore` |
| T-20.7 reposo del host (sin sesión gráfica) | Medido (sección 2.3) | 3 sesiones × 3 ventanas con boost de CPU activo y 3 × 3 con boost apagado |
| T-20.5 calibración | Ejecutada con la política definitiva (6.2); con el techo en el contenedor y luego en el generador apliqué la contingencia SHA-256 de la Etapa 2 y recalibré ambas distribuciones (6.5 y 6.6). Tasas fijadas: `media` 450 y `alta` 900 rps | `k6/calibrar.py`; hay además corridas exploratorias, rotuladas como tales |
| T-20.1 a T-20.4 (pilotos) | K3s 9 de 9 y MicroK8s 9 de 9, ambos el 27-oct en la misma sesión; T-20.3 y T-20.4 documentados (sección 7) | Hallazgo abierto: dos niveles de potencia con la misma carga (≈ 1 W), sin causa conocida y no atribuibles a la sesión (7.4, punto 6) |
| T-20.6 despliegue | K3s 6 ciclos y MicroK8s 5, mediciones puntuales (sección 8) | `data/despliegue/despliegue_*.jsonl` |

## 2. Estado del host para medir y reposo

### 2.1 Hechos del host (leídos el 25-oct-2026)

- `graphical.target` es el objetivo por defecto y `lightdm` está activo; `ufw` tiene `ENABLED=no`.
- Perfil de energía `balanced` (`powerprofilesctl get`), gobernador de CPU `powersave`, corriente alterna, red por Wi-Fi (`rtw89_pci`).
- Con `systemctl list-units` vi en ejecución, entre otros y fuera del experimento: `docker`, `containerd`, `incus`, `postgresql@16-main`, `snap.maas.pebble`, `cups`, `avahi-daemon`, `ModemManager`, `preload`, `unattended-upgrades`, `snapd`, `cron`, `udisks2`, `upower`; 14 timers (`apt-daily`, `fstrim`, `fwupd-refresh`, `man-db`, entre otros).

### 2.2 Decisión: un solo estado de medición, sin sesión gráfica

Todas las mediciones (calibración, pilotos y campaña) se hacen **sin sesión gráfica** y con **solo las unidades necesarias corriendo**. No mido nada con sesión gráfica ni comparo contra los servicios normales: es un estado fijo, no una opción por corrida. Esto coincide con la Etapa 2 («ejecuciones definitivas desde consola de texto»).

- Lista blanca, no lista negra: `ansible/group_vars/all.yml` define `medicion_unidades_permitidas` (expresiones regulares). Todo lo que corre y no está en la lista se detiene. Así un servicio que yo no vi no queda corriendo sin que nadie lo note.
- Permitido: `chrony`, `node_exporter`, `prometheus`, `scaphandre`, `ssh`, `NetworkManager`, `wpa_supplicant`, `dbus`, `polkit`, `power-profiles-daemon`, `rsyslog`, `getty`, `user@`, las unidades `systemd-*`, `libvirt`/`virt*`, y `dm-event`, `lvm2-*` y `uuidd`.
- `/usr/local/sbin/tesis-modo-medicion simular` imprime lo que detendría sin tocar nada; `entrar` lo detiene (se niega si la sesión gráfica sigue activa, para no matar la sesión del usuario) y fija el perfil `balanced`; `salir` lo restaura todo. Solo detiene servicios en estado `running` y sockets, paths y timers `active`; no toca los servicios de una sola ejecución (`exited`) porque detenerlos puede revertir su efecto (por ejemplo, perfiles de AppArmor).
- Simulación de hoy (sin `sudo`, con la sesión gráfica activa): detendría 44 unidades, entre ellas `lightdm`, `docker`, `incus`, `postgresql`, `snapd`, `cups`, `avahi`, `cron`, `udisks2`, `upower` y los timers listados. La lista efectiva la reviso con `simular` antes de la primera vez.
- El orquestador y `calibrar.py` verifican en cada corrida: sesión gráfica inactiva, modo medición activo, ninguna unidad fuera de la lista, servicios requeridos activos, perfil de energía y corriente alterna. Registran el bloque `estado_host` (incluye las 10 unidades o procesos con más CPU según `top`). Si algo falla, la corrida queda con `valida_para_campana: false` y `motivos_no_valida`. Las corridas de tipo `piloto`, `calibracion` y `verificacion` nunca son válidas para la campaña.
- El modo vive en `/run`: se pierde al reiniciar. Hay que ejecutar `entrar` en cada jornada de medición y `salir` al terminar.

Límites (condición de medición válida para toda la campaña): no cuantifico el costo de la sesión gráfica ni el ahorro de pausar servicios. La decisión se apoya en la Etapa 2 y en reducir fuentes de ruido, no en una medición propia. Los servicios que dejo (red, `ssh`, `rsyslog`, entre otros) siguen consumiendo algo que no mido por separado.

### 2.3 Caracterización del reposo

Mido la potencia del paquete (RAPL `package-0`, la misma lectura de `energy_uj` del orquestador) en ventanas consecutivas de 180 s (la duración de la fase estable), sin VMs ni k6, en el estado de medición. Son 3 sesiones de 3 ventanas, con 120 s de calentamiento cada una. Las 3 ventanas de una sesión están autocorrelacionadas: la variabilidad que cuenta es la de entre sesiones, y con 3 es una estimación gruesa.

```
sudo /usr/local/sbin/tesis-modo-medicion entrar
python3 k6/reposo_host.py --sesion 1
python3 k6/reposo_host.py --sesion 2
python3 k6/reposo_host.py --sesion 3
sudo /usr/local/sbin/tesis-modo-medicion salir
```

El script se niega a medir si hay VMs encendidas, un `k6` en ejecución, la sesión gráfica activa o el modo medición inactivo. Escribe `data/reposo/reposo_host_s<NN>.json` con la potencia de cada ventana, el estado del host, `chronyc tracking` y, por ventana, la carga, la CPU ocupada según Node Exporter y la temperatura.

Resultados (W, potencia media del paquete por ventana de 180 s):

| Condición | Sesión 1 | Sesión 2 | Sesión 3 | Media de sesiones | sd entre sesiones | sd entre las 9 ventanas |
|---|---|---|---|---|---|---|
| Boost de CPU activo (`reposo_host_boost-activo_s0*.json`) | 2,470 / 2,552 / 2,603 | 2,526 / 2,571 / 2,511 | 2,444 / 2,486 / 2,460 | 2,514 | 0,044 | 0,054 |
| Boost apagado, política definitiva (`reposo_host_s0*.json`) | 2,614 / 2,661 / 2,584 | 2,550 / 2,682 / 2,561 | 2,543 / 2,521 / 2,730 | 2,605 | 0,013 | 0,072 |

Observaciones y límites:

- Las dos condiciones difieren en 0,09 W (3,6 %), del orden de la dispersión entre ventanas. No concluyo que el boost cambie el reposo; solo registro que en reposo no se nota con n = 3 sesiones.
- La dispersión entre sesiones cambia de una condición a otra (0,044 frente a 0,013) y con 3 sesiones no es una estimación fiable de la variabilidad real.
- La condición con boost activo se midió antes de fijar la política de boost apagado (sección 6.3); la dejo como referencia y no se usa en la campaña.
- No separo cuánto del reposo es del paquete sin VMs frente al consumo de los servicios que dejé corriendo.

## 3. Reloj (chrony)

### 3.1 Hechos

- El host sincroniza hoy con fuentes externas: `pool ntp.ubuntu.com` y `pool {0,1,2}.ubuntu.pool.ntp.org` (configuración por defecto de Ubuntu), más `local stratum 10` y `allow 192.168.100.0/24` que agrega `ansible/roles/chrony/templates/tesis.conf.j2`. Las VMs apuntan solo a `.1`.
- `chronyc sources` del 25-oct: ocho fuentes; la seleccionada tenía ± 28 ms de distancia a la raíz y las demás diferían entre sí hasta ≈ 60 ms. `chronyc tracking`: `System time` 1,9 ms, `RMS offset` 7 ms, intervalo de actualización 259 s.
- En las corridas anteriores (`reloj_antes` en los metadatos de `verif_k3s_media-fallo_r03`) el host tenía `System time` de 0,2 ms y las tres VMs entre 1 µs y 15 µs respecto del host.

### 3.2 Decisión sobre las fuentes externas del host

Mantengo las fuentes externas por defecto del host. Alternativas que descarté:

| Alternativa | Ventaja | Desventaja | Por qué no |
|---|---|---|---|
| **Mantener fuentes externas (elegida)** | El tiempo queda anclado a UTC y los metadatos son trazables | chrony puede corregir el reloj del host durante una ventana | Una corrección está acotada por el umbral del criterio (20 ms): sobre 180 s afectaría la duración de la ventana, como máximo, 0,011 % (cálculo mío, suponiendo que toda la corrección cae dentro de la ventana) |
| Host aislado (solo `local stratum 10`) | Sin correcciones durante la campaña | Se pierde la referencia absoluta; la deriva de varios días no queda acotada | La trazabilidad vale más que evitar una corrección de milisegundos |
| Congelar fuentes durante la corrida (`chronyc offline`/`online`) | Reloj sin correcciones en la ventana | Agrega un paso privilegiado y un estado que puede quedar mal restaurado si el orquestador cae | Complejidad sin ganancia medible frente al umbral anterior |
| Una sola fuente fija | Más reproducible | Depende de un servidor concreto y de que siga existiendo | Frágil en una campaña de semanas |

Esto no cambia el diseño de la Etapa 2 (host = referencia de las VMs, VMs solo contra `.1`).

### 3.3 Criterio de reloj convergido

Antes de lanzar k6 el orquestador (y `calibrar.py`) ejecuta `chronyc tracking` en el host y en cada VM y exige: `Leap status: Normal` en todos; `|System time|` ≤ 20 ms en el host y ≤ 5 ms en cada VM; y que cada VM tenga como referencia a `192.168.100.1`. Si no se cumple, reintenta cada 10 s hasta 180 s; si sigue sin cumplirse, **aborta sin lanzar k6**. Los umbrales están en `ansible/group_vars/all.yml` (`medicion_reloj_*`).

- **Supuesto, no derivado de una prueba estadística:** los umbrales son decisiones mías. El de 20 ms del host es ≈ 3 veces el `RMS offset` que vi (7 ms); el de 5 ms de las VMs es ≈ 300 veces el mayor desfase que medí (15 µs). La resolución más fina de las muestras (1 s) es 50 veces mayor que el umbral del host.
- Si el host está sin fuentes externas, `local stratum 10` lo mantiene como referencia y el criterio puede cumplirse con `Leap status: Normal` pero sin anclaje absoluto; no lo detecta el criterio.
- Registro `reloj_antes` y `reloj_espera_s` en los metadatos de cada corrida.

### 3.4 Corrección durante las pruebas

La primera comparación del orquestador buscaba la IP del host en `Reference ID` y falló (`no sigue al host (C0A86401 (coto-thinkpad…))`) porque chrony muestra el nombre del host y no la IP. Ahora comparo por el hexadecimal de la IP (`C0A86401`). No cambia el criterio, corrige la lectura.

### 3.5 Cambio posterior a ver datos: umbral del host de 20 a 100 ms

El 26-oct-2026 dos corridas (la calibración de K3s y `media` r2 del piloto) abortaron por el criterio de reloj: el host marcaba 22,7 ms y 51–55 ms de atraso contra el NTP. A las 22:52 estaba en 13,6 ms y a las 23:00 en 55 ms, tras una muestra nueva de dos fuentes (−52 y −64 ms). Las fuentes externas son ruidosas (`chronyc sourcestats`: desviación de 11 a 28 ms por fuente; retardo de raíz de 70 ms por Wi-Fi), así que un umbral de 20 ms es menor que la incertidumbre de la referencia y cumplirlo depende de la muestra.

Decisión (mía, después de ver los fallos): subo el umbral del host a **100 ms** como control de cordura y dejo el de las VMs en 5 ms. Razones: k6, RAPL y Prometheus usan el reloj del host, así que el desfase absoluto contra el NTP no altera su alineación; chrony corrige a ≈ 7 µs por segundo, unos 1,3 ms en 180 s (0,0007 % de la ventana). El desfase del host y de las VMs se sigue guardando en `reloj_antes` de cada corrida, sin usarlo como filtro, para comprobar en el análisis que no correlaciona con la potencia.

Límites: el valor de 100 ms sigue siendo una decisión mía y solo detecta fallos groseros. Debe quedar fijo antes de empezar la campaña. La referencia sería más estable con Ethernet o una fuente local; no lo probé. Las corridas anteriores a este cambio (por ejemplo `piloto_k3s_alta_r0*` y la secuencia de MicroK8s) cumplieron el umbral de 20 ms.

## 4. ufw

Hecho: `ufw` está inactivo (`ENABLED=no` en `/etc/ufw/ufw.conf`), por lo que la regla de `UDP 123` del rol `chrony` nunca se aplicó y las VMs sincronizan igual porque no hay filtrado.

Decisión: **lo dejo inactivo** y lo registro en cada corrida (`estado_host.ufw_habilitado`).

| Alternativa | Ventaja | Desventaja |
|---|---|---|
| **Dejar inactivo (elegida)** | No agrega variables al entorno medido; no arriesga la red NAT de libvirt, el SSH ni los scrapes de Prometheus | El host queda sin filtrado; es un equipo de laboratorio en una red doméstica o universitaria |
| Activar con reglas mínimas (SSH, UDP 123 desde `192.168.100.0/24`) | Reduce la exposición | `ufw` con política de entrada denegada y reenvío por defecto puede interferir con libvirt NAT (DHCP y DNS de `dnsmasq`, reenvío de las VMs; lo sé por conocimiento general, no lo reproduje aquí); agrega seguimiento de conexiones por paquete que afectaría la medición de energía y obligaría a repetir las pruebas de conectividad; **no lo pude probar** porque cambiar el cortafuegos requiere `sudo` interactivo y un riesgo que no quiero asumir a cinco días de la entrega |

La tarea `Permitir NTP (123/udp)...` del rol `chrony` queda condicionada a que `ufw` esté activo, por lo que si alguien lo activa después se aplica sola. No la probé activa.

## 5. Política de datos de `data/`

### 5.1 Hechos medidos

- `data/` pesa ≈ 114 MB en el último commit (≈ 91 MB en 14 snapshots de Prometheus, de 2,1 MB a 9,1 MB; ≈ 24 MB de resultados de k6).
- Un snapshot contiene toda la TSDB hasta ese momento, así que **cada uno incluye a los anteriores**. Su tamaño crece ≈ 0,3 a 0,5 MB por snapshot en las verificaciones que hice (observación, no modelo).
- El JSON de k6 pesa ≈ 144 B comprimidos por solicitud (máximo de cuatro corridas); `verif_k3s_media-fallo_r03` (20.999 solicitudes) pesa 2,86 MB y su agregado por segundo, 3,6 KB. Sobre ≈ 3.300 solicitudes por segundo en la fase estable el crudo pasaría de 100 MB.
- Una ventana de 5 min exportada de Prometheus (643 series del host y los exportadores) ocupa 40 KB comprimidos.

### 5.2 Decisión

| Dato | Qué hago | Dónde |
|---|---|---|
| JSON crudo de k6 | **No se versiona.** Queda en `data/k6-crudo/<tipo>/<sesión>/` (ignorado por git); su `sha256` y tamaño van en los metadatos de la repetición | local, con respaldo manual fuera del repositorio |
| Agregado de k6 | Se versiona el agregado por segundo (solicitudes, fallidas, descartadas, p50, p95, p99 y máximo) y el resumen de k6 | `data/<tipo>/<sesión>/k6-resultados/<base>.por_segundo.json.gz` y `.resumen.json` |
| Ventana de Prometheus | Se versionan las muestras crudas de la ventana de cada repetición (host, VMs, Scaphandre y las series de nodos y pods de kube-state-metrics) | `data/<tipo>/<sesión>/prometheus-ventanas/<base>.json.gz` |
| Snapshot de Prometheus | El orquestador lo toma siempre, pero **solo lo copia a `data/` con `--copiar-snapshot`**: copio el último de cada bloque (cada uno contiene a los anteriores) | `data/prometheus-snapshots/` |

Alternativas descartadas:

- *Un snapshot por repetición versionado:* con ≈ 60 repeticiones y snapshots de 10 a 30 MB serían ≈ 1 GB en el historial de git, y cada uno repite lo que ya contiene el siguiente (el 30 MB es una extrapolación mía, no una medición).
- *Un snapshot por escenario:* mejor que lo anterior, pero sigue duplicando datos; un snapshot al final de cada bloque cubre todo lo anterior.
- *JSON crudo completo de k6 versionado:* inviable sobre el límite de 100 MB por archivo de GitHub y sin ganancia: el agregado por segundo conserva lo que uso (tasa efectiva, fallos, latencia por segundo). Lo que pierdo es la latencia por solicitud; queda en el crudo local.
- *Muestreo de solicitudes:* introduce un sesgo de muestreo que habría que justificar; el agregado por segundo no lo tiene.

Límite: el crudo local se pierde si falla el disco del equipo; el respaldo fuera del repositorio es manual (no lo automatizo). Los archivos anteriores a esta política (`data/humo/` y `data/verificacion/*/k6-resultados/*.json.gz`) quedan como están, ya versionados.

Código: `k6/orquestador.py` (`exportar_ventana`, `sha256`, `--copiar-snapshot`, bloque `ventana_prometheus` y `k6.por_segundo` en los metadatos, esquema `2`), `k6/agregado.py`, `data/.gitignore`.

## 6. Calibración de tasas (T-20.5)

### 6.1 Método

- Herramienta: `k6/calibrar.py --distribucion <k3s|microk8s>`. Sube una escalera de tasas (por defecto 100, 200, 400, 800, 1200, 1600, 2400, 3200, 4800 y 6400 solicitudes por segundo; en las corridas definitivas usé además 1800 y 2000) en modelo abierto (`k6/calibracion.js`, mismo `discardResponseBodies` que los escenarios), un escalón de 60 s (5 s de rampa y 10 s descartados), con 20 s de pausa.
- Un escalón es **sostenido** si en su tramo estable: se aplicó ≥ 99 % de la tasa pedida; fallaron ≤ 0,1 % de las solicitudes; el pod estuvo estrangulado por CFS en ≤ 1 % de los períodos (`cpu.stat` del cgroup del pod); la CPU de los núcleos de k6 está < 85 % y los VUs en uso < 80 % de `maxVUs`. Los umbrales son decisiones mías, no derivados.
- **Cambio posterior a ver datos:** la primera versión exigía además que la mediana del p95 por segundo no superara 3 veces la del primer escalón. La quité después de ver que marcaba como fallidos escalones sin pérdida ni descarte, y la regla era arbitraria. La latencia queda solo como dato reportado. Es un ajuste post hoc y lo declaro así. `--reanalizar` re-aplica el criterio vigente a una corrida guardada.
- Salida: `data/calibracion/<fecha>_<distribución>/calib_<distribución>_<fecha>.json` (prefijo `calib_` para que nadie lo use como resultado de la campaña).
- Los JSON crudos de k6 de calibración los borré para liberar disco (≈ 770 MB las del 25 y 26-oct y ≈ 367 MB las del 27-oct); los `sha256` que quedan escritos en esos metadatos apuntan a archivos que ya no existen. Los resultados por escalón sí están en los JSON de calibración.

### 6.2 Resultados con la política definitiva (boost apagado, perfil `balanced`, límite del pod `500m`)

Una pasada por distribución. Archivos: `calib_k3s_20261025T201949.json` y `calib_microk8s_20261025T213415.json`.

| Pedida (rps) | K3s aplicada | K3s pod estrangulado | MicroK8s aplicada | MicroK8s pod estrangulado |
|---|---|---|---|---|
| 100 | 100,0 | 0/657 | 99,6 | 0/658 |
| 400 | 397,5 | 0/663 | 397,6 | 0/660 |
| 800 | 800,0 | 0/663 | 798,2 | 0/662 |
| 1200 | 1192,8 | 0/662 | 1200,0 | 0/662 |
| 1600 | 1597,4 | 0/662 | 1597,5 | 0/663 |
| 1800 | 1788,2 | 4/662 | 1798,6 | 4/663 |
| 2000 | 1991,9 | 38/663 (5,7 %) | 1982,0 | 116/663 (17,5 %) |
| 2400 | 1926,2 (23.507 descartadas) | 611/665 | 1959,5 (21.721 descartadas) | 610/663 |

- Última tasa sostenida: **1800 rps en ambas distribuciones**. En 2000 rps falla por estrangulamiento del pod. En 2400 rps el techo aplicado es ≈ 1926 rps (K3s) y ≈ 1960 rps (MicroK8s). Cero solicitudes fallidas en todos los escalones.
- El generador no limita en esta política: CPU de los núcleos de k6 ≤ 0,55 núcleos hasta 2000 rps.
- Repetí la calibración sobre clústeres recién construidos: K3s tres veces más (26-oct 19:01 y 22:35, 27-oct 08:59: `calib_k3s_20261026T190107`, `…T223532`, `calib_k3s_20261027T085927`) y MicroK8s dos veces más (26-oct 20:39: `calib_microk8s_20261026T203902`; 27-oct 11:19: `calib_microk8s_20261027T111916`). En las seis pasadas la última tasa sostenida fue **1800 rps** y el escalón de 2000 rps falló por estrangulamiento del pod (3,5 % a 17,5 % de los períodos); el techo en 2400 rps quedó entre ≈ 1910 y ≈ 1996 rps. Cero solicitudes fallidas. La diferencia entre distribuciones en 2000 rps no la interpreto como diferencia de distribución.
- Tasas que usé en los pilotos, iguales en ambas distribuciones: `media` = 900 rps (50 % de 1800) y `alta` = 1600 rps (89 % de la última tasa sostenida; mi interpretación de «justo bajo la saturación»). Quedan reemplazadas por las de 6.6, que se calibraron con la aplicación definitiva.

### 6.3 Hallazgos que cambiaron la política de medición

1. **Tope de potencia del paquete con boost activo.** Con el boost de CPU activo la potencia del paquete se queda en un tope (≈ 15 W en `balanced`, ≈ 24 W en `performance`) desde ≈ 800 rps. En los pilotos de K3s con boost activo, `media` (1600 rps) y `alta` (2900 rps) dieron exactamente 14,961 W: la energía deja de distinguir las cargas. El perfil `performance` no lo resuelve. Con el boost apagado (`/sys/devices/system/cpu/cpufreq/boost` = 0, frecuencia máxima 1,901 GHz) la potencia crece con la carga. Adopté boost apagado como parte del estado fijo de medición (`medicion_boost_cpu: 0`); `tesis-modo-medicion` lo aplica y lo restaura. Esto es una decisión de mi diseño experimental que no estaba en la Etapa 2.
2. **El techo es el contenedor, no el nodo.** En el escalón en que falla, el pod de NGINX está estrangulado por CFS (límite `500m`) mientras la CPU de las VMs queda en ≈ 35 % como máximo. Esto contradice la premisa de la Etapa 2 de que `500m` es «deliberadamente holgado» para que el techo sea el nodo. Una prueba exploratoria con límite `2000m` (K3s, boost activo) movió el techo al generador (núcleos 0 y 1 saturados a ≈ 6200–8400 rps, nodo ≤ 0,81 de sus 2 vCPU). En ese momento mantuve `500m` por ser la decisión cerrada del diseño. Lo revisé el 27-oct con la política definitiva: ver 6.5 y 6.6.
3. **Presión de memoria del host.** Con 3 VMs de 4 GB, cada proceso `qemu` llega a ≈ 4,1 GB de RSS (≈ 1 GB usado por el invitado y ≈ 2,8 GB de caché de páginas del invitado). La memoria disponible del host baja a ≈ 1,3–1,7 GB con MicroK8s y se mantiene en ≈ 5,6–6,2 GB con K3s. El kernel no registró OOM (`journalctl -k` desde las 15:00 del 25-oct sin `out of memory`) y el orquestador aborta bajo 1024 MB. Mantengo 4 GB por nodo, el valor de la Etapa 2; el margen con MicroK8s es estrecho (ver 7.2).
4. **Variabilidad sin explicar entre corridas del mismo estado.** La corrida exploratoria de K3s con boost apagado dio ≈ 6,0 W a 100 rps y la definitiva ≈ 4,34 W con la misma configuración nominal. Por eso la diferencia de ≈ 1,8–2,0 W entre MicroK8s y K3s en las calibraciones definitivas (K3s 4,34 → 6,20 W de 100 a 2000 rps; MicroK8s 6,14 → 8,15 W; valores que leí de Prometheus durante las corridas y no están en los JSON de calibración) **no es atribuible a la distribución**: n = 1 por distribución y variabilidad de corrida a corrida sin explicar. Ahora se registran el EPP y el perfil de plataforma en `estado_host`.

### 6.4 Corridas exploratorias (no son resultados)

| Archivo | Condición | Uso |
|---|---|---|
| `calib_k3s_20261025T170953`, `…172640` | boost activo, `500m` | primera calibración de K3s; mostró el tope de potencia |
| `calib_microk8s_20261025T182247` | boost activo, `500m` | ambas distribuciones sostuvieron 3200 rps; techo ≈ 3400–3500 rps con el contenedor estrangulado en 92–94 % de los períodos a 4800 y 6400 rps |
| `calib_k3s_20261025T174625` | límite `2000m`, boost activo | exploratoria: techo en el generador |
| `calib_k3s_20261025T194723` | perfil `performance` | exploratoria: no resuelve el tope |
| `calib_k3s_20261025T200335` | boost apagado | exploratoria: precursora de la definitiva |

### 6.5 Límite del pod en `2000m` con NGINX estático (K3s, 27-oct)

Con la política definitiva repetí la prueba del límite: pod con límite `2000m` y request `500m` (en `500m` el techo era el estrangulamiento del pod, con el nodo en ≈ 17 %). Una pasada, clúster recién construido (ciclo 6). Archivo: `calib_k3s_20261027T131757.json`.

| Pedida (rps) | Aplicada | Descartadas | p95 (ms) | Pod (núcleos) | VM del pod (núcleos) | k6 (fracción de sus 2 núcleos) |
|---|---|---|---|---|---|---|
| 1800 | 1797 | 0 | 6,7 | 0,37 | 0,34 | 0,42 |
| 2400 | 2400 | 0 | 12,2 | 0,52 | 0,38 | 0,62 |
| 3200 | 3196 | 123 | 16,4 | 0,75 | 0,44 | 0,75 |
| 4000 | 3912 | 3290 | 61,5 | 0,95 | 0,55 | 0,92 |
| 5000 | 4660 | 16.943 | 107,4 | 1,00 | 0,70 | 0,97 |
| 6000 | 5322 | 33.868 | 117,0 | 1,01 | 0,74 | 0,96 |
| 8000 | 5402 | 129.016 | 146,1 | 1,00 | 0,76 | 0,96 |

- Última tasa sostenida: **3200 rps**, con `limite_por_generador: true`: desde 4000 rps falla por tasa aplicada < 99 %, CPU de los núcleos de k6 ≥ 85 % y VUs ≥ 80 % de `maxVUs`. Cero solicitudes fallidas y cero períodos estrangulados en todos los escalones.
- A 8000 rps pedidos la VM del pod usa 0,76 de sus 2 vCPU (≈ 38 %). NGINX estático no exige al nodo: antes lo frena el generador. Esa es la condición que la Etapa 2 deja para activar la contingencia («NGINX estático no exige al nodo ni a tasas altas»).
- A 5000–8000 rps el pod se queda en ≈ 1,0 núcleo, igual que el generador. No distingo cuál de los dos limita ahí; no medí la distribución entre los procesos de NGINX.
- Una extrapolación lineal previa (estimación mía, no medida) preveía el techo del generador en ≈ 7700 rps; el real quedó en ≈ 3200–4000 rps.

### 6.6 Contingencia SHA-256 y tasas definitivas (T-20.5)

**Decisión (mía, tomada con los datos de 6.5).** Apliqué la contingencia de la Etapa 2: cada solicitud a `/` calcula un SHA-256 repetido N veces con un valor fijo. Lo implementé con el módulo njs que ya trae la imagen fijada por digest (`ngx_http_js_module`), sin cambiar de imagen: el `ConfigMap` `nginx-referencia` lleva el `nginx.conf` (con `load_module`), el `default.conf` y el script `sha.js`; `/healthz` queda igual. N es la variable `nginx_sha_iteraciones` (valor `300`, inicial: no probé otros valores) y el límite del pod queda en `2000m` con request `500m` en ambas distribuciones. Verifiqué que la respuesta coincide con el hash calculado fuera del clúster con 300 iteraciones. Esto cambia la aplicación de referencia respecto de la Etapa 1–2 y lo declaro como desviación.

**Resultados.** Una pasada por escalón. K3s: `calib_k3s_20261027T143148.json` (200–3000 rps) y `calib_k3s_20261027T144649.json` (900, 1000, 1100). MicroK8s: `calib_microk8s_20261027T152020.json`. K3s con el NGINX renderizado desde la plantilla y aplicado con `kubectl` sobre el clúster del ciclo 6; MicroK8s construido por el flujo completo con límite `500m` (omisión mía en su `group_vars`) y corregido a `2000m` con `kubectl` antes de calibrar.

| Pedida (rps) | K3s aplicada / descartadas / p95 ms / pod núcleos | MicroK8s aplicada / descartadas / p95 ms / pod núcleos |
|---|---|---|
| 400 | 397,7 / 0 / 2,3 / 0,42 | 397,2 / 0 / 2,3 / 0,42 |
| 800 | 795,9 / 0 / 5,1 / 0,98 | 797,9 / 0 / 7,6 / 1,01 |
| 900 | 893,8 / 0 / 4,8 / 1,03 | 895,4 / 0 / 15,3 / 1,31 |
| 1000 | 999,4 / 0 / 6,3 / 1,27 | 998,1 / 96 / 62,9 / 1,59 |
| 1100 | 1093,0 / 14 / 12,1 / 1,61 | 1064,3 / 1488 / 346 / 1,71 |
| 1200 | 1097,5 / 5051 / 378 / 1,76 | 1077,0 / 6021 / 389 / 1,70 |
| 1400 | no medido | 1073,9 / 16.217 / 397 / 1,73 |

- Última tasa sostenida: **1100 rps en K3s** (99,4 % aplicada, justo) y **1000 rps en MicroK8s** (99,8 %, con 96 descartadas y p95 de 63 ms). Sobre el techo la tasa aplicada se aplana en ≈ 1100 rps (K3s) y ≈ 1075 rps (MicroK8s).
- El techo ahora lo pone el nodo: la VM del pod llega a 0,85–0,97 de ocupación, el generador queda en 0,34 de sus núcleos como máximo en K3s y 0,31 en MicroK8s (`limite_por_generador: false`), cero solicitudes fallidas y ≤ 1 período estrangulado de ≈ 664.
- A igual tasa el pod de MicroK8s gasta más CPU que el de K3s (a 1000 rps, 1,59 contra 1,27 núcleos, ≈ 25 % más; cálculo mío) y tiene más latencia. No medí la causa.
- Cada escalón se midió una vez por distribución, así que no conozco la variación entre pasadas.

**Tasas fijadas, iguales en ambas distribuciones.** La Etapa 2 justifica el modelo abierto porque «ambas distribuciones reciban exactamente la misma tasa» (RNF-03), así que descarté usar una tasa por distribución. Tomo como saturación común la de la distribución que satura antes (MicroK8s, ≈ 1000 rps):
- `alta` = **900 rps**: la tasa limpia inmediatamente inferior en ambas (MicroK8s: 99,4 % aplicada, 0 descartadas, p95 15 ms). 1000 rps no sirve porque en MicroK8s ya hay descartadas.
- `media` = **450 rps**, la mitad de `alta`, como dice el texto de la Etapa 2 («la mitad de la tasa así determinada para carga alta»). El Cuadro 4 de la misma entrega dice «50 % de la tasa de saturación», que daría 500 rps; las dos redacciones no coinciden y elegí la del texto.

Los pilotos de la sección 7 se hicieron antes de este cambio (NGINX estático, `500m`, 900 y 1600 rps): valen como pilotos del procedimiento de medición, no como mediciones de la aplicación definitiva.

## 7. Pilotos (T-20.1 a T-20.4)

### 7.1 Qué corrí

Política definitiva con la aplicación de entonces (modo medición, boost apagado, perfil `balanced`, 4 GB por VM, NGINX estático, límite del pod `500m`; la aplicación definitiva es la de 6.6). Cada distribución en un clúster recién construido, calibrado (sección 6) y con la misma secuencia: `idle`, `media` y `alta` × 3 repeticiones (`k6/secuencia_piloto.sh`), 120 s de estabilización, rampa de 30 s, fase estable de 180 s y descenso de 30 s. Tasas: `media` 900 rps y `alta` 1600 rps (sección 6.2).

| Distribución | idle | media | alta | Observación |
|---|---|---|---|---|
| K3s | 3 de 3 | 3 de 3 | 3 de 3 | Secuencia completa de 9 corridas el 27-oct-2026 (equipo reiniciado, red de la oficina), en un único clúster recién construido y calibrado (ciclo 5). Las corridas del 26-oct (ciclos 3 y 4) están en `data/exploratorio/2026-10-26_k3s/` |
| MicroK8s | 3 de 3 | 3 de 3 | 3 de 3 | Secuencia completa de 9 corridas el 27-oct-2026, después de la de K3s, en la misma sesión del equipo y en un clúster recién construido y calibrado (ciclo 4). La secuencia del 26-oct (ciclo 3) está en `data/exploratorio/2026-10-26_microk8s/` |

Las corridas de K3s con boost activo y las del 26-oct (K3s y MicroK8s) están en `data/exploratorio/` (sin los JSON crudos de k6, que descarté; los metadatos conservan la ruta del crudo, que ya no existe). No las trato como resultados definitivos, pero son evidencia del tope de potencia (6.3) y de los niveles de potencia (7.4, punto 6).

### 7.2 Resultados del piloto (potencia media del paquete en la fase estable, RAPL `package-0`)

| Escenario | K3s (W) | MicroK8s (W) |
|---|---|---|
| idle | **4,894** (4,859 / 4,920 / 4,902; sd 0,031). 26-oct: 5,781 | **5,867** (5,864 / 5,875 / 5,863; sd 0,007). 26-oct: 5,877 |
| media (900 rps) | **6,212** (6,208 / 6,204 / 6,223; sd 0,010). 26-oct: 7,137 / 5,264 / 5,217 | **7,206** (7,199 / 7,208 / 7,210; sd 0,006). 26-oct: 7,197 |
| alta (1600 rps) | **6,792** (6,784 / 6,801 / 6,790; sd 0,009). 26-oct: 7,764 | **7,775** (7,775 / 7,758 / 7,791; sd 0,017). 26-oct: 7,734 |

- Con boost apagado la potencia crece con la carga: no aparece el tope que había con boost activo.
- Tasa efectiva en la fase estable: `media` 900,0 rps (sd por segundo ≤ 0,9) y `alta` 1599,9–1600,0 rps. Cero solicitudes fallidas en las 12 corridas con carga. Descartadas por k6 en `alta`: K3s 7, 7 y 30; MicroK8s 5, 6 y 36 (de ≈ 288.000 solicitudes por corrida).
- Diferencias entre distribuciones, ambas medidas el mismo día en la misma sesión del equipo: MicroK8s − K3s = +0,973 W en `idle` (+19,9 %), +0,994 W en `media` (+16,0 %) y +0,983 W en `alta` (+14,5 %). Es una diferencia casi constante, la misma curva paralela de 7.4 (punto 6). **No la interpreto como efecto de la distribución:** el 26-oct K3s midió 5,781 / 7,137 / 7,764 W, a ≈ 0,1 W de los niveles de MicroK8s, y MicroK8s repitió sus niveles del 26-oct con ±0,04 W. Con n = 3 por celda no concluyo diferencias entre distribuciones; son pilotos.
- La potencia en `idle` del piloto de K3s del 26-oct (5,78 W) es mayor que la medida a 100 rps en su calibración (4,34 W). No lo explico; es la misma variabilidad entre corridas.
- Todas las corridas salen con `valida_para_campana: false` solo por el motivo `tipo piloto`. Ninguna tuvo motivos de estado del host, de reloj ni de memoria.
- Reloj antes de lanzar k6: espera entre 4,7 s y 7,1 s en las 18 corridas del 27-oct; no hubo abortos.
- Memoria disponible del host durante las corridas: K3s 5632–6139 MB; MicroK8s **1519–1776 MB** (el 26-oct: 1279–1671 MB). Con MicroK8s el margen sobre el umbral de aborto del orquestador (1024 MB) fue de 495 MB como mínimo el 27-oct y de 255 MB el 26-oct. Sin presión según PSI en K3s; no registré PSI máximo en MicroK8s.

### 7.3 T-20.3: sincronía de Scaphandre, Prometheus y k6

- **Scaphandre contra RAPL.** Con la energía acumulada de Scaphandre (`scaph_socket_energy_microjoules`, interpolada linealmente a los extremos de la ventana) calculé la potencia de cada corrida y la comparé con la lectura RAPL del orquestador. En las 18 corridas del 27-oct (K3s y MicroK8s), 17 están entre −0,06 % y +0,01 %. La restante (`piloto_microk8s_idle_r01`) tiene el desbordamiento explicado en 7.4; corregido, su diferencia es −0,005 %. Los scrapes distan 10,0 s como máximo, que es el intervalo configurado.
- **Ventana contra k6.** Revisé las tasas por segundo de k6 alrededor de la ventana (`t_inicio`–`t_fin`): los 2–3 s anteriores muestran la rampa (por ejemplo, 1507 y 1547 rps antes de llegar a 1600) y el primer segundo de la ventana ya está en el plateau; tras la ventana empieza el descenso. La ventana coincide con la fase estable con resolución de 1 s. Dentro de la ventana, los segundos fuera de ±1 % aparecen en pares consecutivos (por ejemplo 1580 y 1619), lo que es coherente con desfase de un segundo en el recuento de k6 (no lo verifiqué contra el código de k6) y no con pérdida de solicitudes.
- Límite: la comparación de energía usa dos fuentes (RAPL y Scaphandre) que leen el mismo contador del paquete, por lo que su concordancia confirma el tratamiento temporal, no la exactitud absoluta de RAPL.

### 7.4 T-20.4: anomalías

1. **Desbordamiento del contador RAPL dentro de una ventana** (ocurrió dos veces: `piloto_microk8s_alta_r02` del 26-oct y `piloto_microk8s_idle_r01` del 27-oct; el detalle siguiente es de la primera). El contador de energía tiene rango máximo 65.532.610.987 µJ y se desborda cada ≈ 8500 s a 7,7 W (≈ 2,4 h; cálculo mío). El orquestador lo detectó (`desbordamiento: true`) y corrigió el delta: 7,712 W, consistente con las vecinas (7,755 y 7,735) y con la energía de Scaphandre corregida por el desbordamiento (≈ 7,713 W). Scaphandre, en cambio, publica el contador crudo: calculada sin corregir, su diferencia de energía da −356 W y la serie `scaph_socket_power_microwatts` tiene una muestra de 0,0 W en ese punto (media de la ventana 7,274 W, −5,7 %). Scaphandre no se reinició (`NRestarts=0`). **Consecuencia para el análisis:** cualquier cálculo de potencia con series de Scaphandre debe corregir el desbordamiento y descartar la muestra en cero; con ventanas de 180 s, ≈ 2 % de las ventanas de la campaña lo tendrán (cálculo mío: 180 s / 8500 s). En la de `idle_r01` del 27-oct Scaphandre dio −358 W sin corregir y 5,864 W corregido, contra 5,864 W de RAPL.
2. **Corridas descartadas por tasa distinta de la prevista.** Tres `media` de K3s se lanzaron a 800 rps en lugar de 900; se descartaron y no se conservan. `k6/secuencia_piloto.sh` ahora imprime las tasas que recibe antes de empezar.
3. **Reinicios de `kube-vip` durante la unión de nodos** en la construcción del ciclo 4 de MicroK8s (1 y 2 reinicios en dos pods); quedaron `Running` y no vi efecto en las corridas.
4. **Holgura de memoria con MicroK8s y 4 GB:** ver 7.2.
5. **Sin explicar:** la variabilidad entre corridas de la sección 6.3 (punto 4); ver el punto 6.
6. **Dos niveles de potencia con la misma carga (≈ 1 W de diferencia).** `media` de K3s a 900 rps midió 7,137 W (r1, 22:54–22:57) y 5,264 y 5,217 W (r2 y r3, 23:12–23:21), en el mismo clúster. Descarté, con los datos de las ventanas: la carga (tasa efectiva 900,0 rps en las tres; CPU del host 15,3 / 14,4 / 14,9 % y de las VMs idénticos; mismos modos de CPU y mismo tráfico de red), la frecuencia (1856 MHz en las tres, según Scaphandre), el boost, el gobernador, el EPP y el perfil (idénticos en `estado_host`), Scaphandre (sin reinicio desde las 18:41, 0,05 % de CPU) y el tráfico Wi-Fi (< 0,5 KB/s). Las cifras de Scaphandre y RAPL coinciden (−0,04 % a −0,01 %), así que no es un error de lectura. Lo mismo se ve en reposo: con las VMs encendidas y sin carga medí 4,188 W a las 23:3x (60 s, con una sesión de terminal activa), frente a 5,78 W de `idle` en la secuencia del ciclo 3. Entre r1 y r2 hubo un `ansible-playbook` del host, `salir`, `entrar` y el cambio del archivo de política; la temperatura de CPU registrada fue 50,5 °C en r1 y 47,2 °C en r2. Además, `ksmd` aparece entre los procesos con más CPU en r1 y no en r2. **No sé la causa.** No descarto la residencia en estados de bajo consumo (C-states), KSM, el estado del equipo tras `salir`/`entrar` ni factores térmicos. Es la amenaza principal para comparar energía entre distribuciones: el salto es ≈ 20 veces mayor que las diferencias entre distribuciones que vimos (≈ 0,1 W). **Sesión del 27-oct (K3s, tras reiniciar el equipo, red de la oficina, clúster nuevo):** idle 4,894 W, media 6,212 W, alta 6,792 W, con dispersión entre repeticiones de 0,01 a 0,03 W y sin ningún aborto. Respecto de la sesión de la tarde del 26-oct (5,781 / 7,137 / 7,764 W) la diferencia es de −0,89, −0,93 y −0,97 W: **la curva es paralela, un desplazamiento aditivo casi independiente de la carga**. Con los dos valores bajos de la noche del 26-oct (5,264 y 5,217 W a 900 rps) se observan tres niveles para la misma carga (7,137; 6,212; ≈ 5,24 W), separados por ≈ 0,9–1,0 W. Es una observación con tres niveles, no un modelo. El reposo del host sin VMs no sigue ese patrón: 2,605 W (26-oct) y 2,887 W (27-oct, una ventana), así que el desplazamiento aparece solo con las VMs encendidas. Las vCPU de las VMs están fijadas a núcleos (`vcpupin` en el XML de libvirt), por lo que la colocación de hilos no explica el salto; el estado del host registrado (gobernador, EPP, perfil, frecuencia máxima, boost, pantalla) es idéntico en todos los niveles. **Prueba de la misma sesión (27-oct, MicroK8s después de K3s, mismo arranque del equipo y misma red):** idle 5,867 W, media 7,206 W, alta 7,775 W. Respecto de K3s del mismo día la diferencia es +0,973 / +0,994 / +0,983 W: otra vez un desplazamiento aditivo casi constante, pero ahora entre distribuciones dentro de una sesión. Eso **no** coincide con la hipótesis de un efecto de sesión: MicroK8s repitió sus niveles del 26-oct (5,877 / 7,197 / 7,734 W, ±0,04 W) en una sesión distinta, y K3s estuvo en el nivel alto el 26-oct (5,781 / 7,137 / 7,764 W) y en el bajo el 27-oct, y dentro del 26-oct pasó de alto a bajo entre r1 y r2 de `media` en el mismo clúster. Resumen de lo observado: MicroK8s, dos sesiones, nivel alto en ambas; K3s, nivel alto en el ciclo 3 y en `media` r1 del ciclo 4 (26-oct), nivel bajo en `media` r2 y r3 del ciclo 4 y en todo el ciclo 5 (27-oct). No depende del arranque del equipo, de la sesión ni del ciclo de construcción. **Un indicio, no una causa:** en `idle`, node_exporter muestra menos CPU ocupada en las VMs cuando el nivel es bajo (K3s del 27-oct: 4,2–7,5 % por VM) que cuando es alto (K3s del 26-oct: 5,9–8,4 %; MicroK8s: 6,0–9,9 % el 26-oct y 5,8–9,0 % el 27-oct); en el host, 4,3–4,7 % contra 4,5–5,2 %. Son cuatro series de tres ventanas y no cuantifiqué si esa diferencia de CPU puede explicar ≈ 1 W, así que lo dejo como correlación. La temperatura del CPU fue parecida (≈ 51–52 °C en MicroK8s el 27-oct). **Consecuencia práctica:** dentro de una serie las mediciones son precisas (sd ≤ 0,03 W), pero el nivel absoluto puede cambiar ≈ 1 W entre series de la misma distribución, ≈ 10 veces la diferencia esperada entre distribuciones. Mientras no se conozca la causa no puedo atribuir a K3s ni a MicroK8s la diferencia de ≈ 1 W de este piloto, y comparar niveles absolutos entre distribuciones no es válido.

### 7.5 Estado y pendientes

- Hecho: pilotos de K3s (9 de 9) y de MicroK8s (9 de 9), ambos el 27-oct en la misma sesión, T-20.3 y T-20.4 documentados con estos datos.
- Pendiente: identificar la causa de los dos niveles de potencia (7.4, punto 6) antes de la campaña; candidatos sin descartar: estados de bajo consumo (C-states), KSM y la actividad de las VMs en reposo. El orquestador no registra hoy residencia de C-states ni contadores de KSM por repetición.
- Datos: de los snapshots de Prometheus del 26 y 27-oct dejé solo el último (`20261027T153553Z-7cd2151d00457ec0`, 26 MB), que contiene a los anteriores (misma TSDB desde el 13-oct; verifiqué los rangos de tiempo de sus bloques). Borré los crudos de k6 de las calibraciones y del piloto de MicroK8s del 26-oct; quedan los de los 18 pilotos del 27-oct en `data/k6-crudo/pilotos/` (≈ 408 MB, sin versionar).
- Hecho: calibración con la aplicación definitiva (SHA-256, `2000m`) en ambas distribuciones y tasas fijadas (6.6). Pendiente: repetir los pilotos con esa aplicación y con `media` 450 y `alta` 900 rps antes de la campaña; los de la sección 7 usaron NGINX estático, `500m` y 900/1600 rps. Falta además construir K3s por el flujo completo con la aplicación definitiva (hoy la calibré con el NGINX aplicado con `kubectl`).
- Etiqueta git de los datos del piloto antes de las mejoras de HU-21 (T-20.4): no la creé; la creo junto con el commit.

## 8. Despliegue (T-20.6) y escenarios sin ejercitar

Medido con `k6/despliegue.sh` (fases `tf_construir`, `huellas`, `ansible` y `tf_destruir`), sin carga, en modo medición. Son mediciones puntuales (K3s 6 ciclos, MicroK8s 5; los ciclos 5 y 6 de K3s y el 4 y el 5 de MicroK8s se hicieron desde la red de la oficina, más lenta, y casi duplican o superan el tiempo de los ciclos anteriores): sin dispersión estimable ni intención de comparar distribuciones, y no las presento como serie. Los ciclos son las reconstrucciones de la secuencia de pilotos y de las calibraciones, no ciclos dedicados.

| Distribución | Ciclo | Construir (s) | Terraform (s) | Huellas (s) | Ansible (s) | Destruir (s) |
|---|---|---|---|---|---|---|
| K3s | 1 | 285,8 | 28,7 | 7,4 | 249,7 | 6,2 |
| K3s | 2 | 392,4 | 29,6 | 7,3 | 355,4 | 6,8 |
| K3s | 3 | 385,6 | 40,7 | 12,3 | 332,6 | 6,8 |
| K3s | 4 | 430,0 | 49,1 | 11,8 | 369,1 | 6,7 |
| K3s | 5 | 813,8 | 69,6 | 12,0 | 732,2 | 6,8 |
| K3s | 6 (exploratorio, límite `2000m`) | 608,9 | 43,3 | 11,8 | 553,8 | 6,8 |
| MicroK8s | 1 | 785,7 | 35,3 | 7,4 | 743,0 | 6,3 |
| MicroK8s | 2 | 954,8 | 40,5 | 12,5 | 901,7 | 7,0 |
| MicroK8s | 3 | 886,0 | 62,7 | 12,0 | 811,3 | 7,2 |
| MicroK8s | 4 | 1467,6 | 129,8 | 11,2 | 1326,5 | 7,1 |
| MicroK8s | 5 (con SHA-256) | 1188,1 | 44,1 | 11,5 | 1132,4 | 6,8 |

- Fuente: `data/despliegue/despliegue_k3s.jsonl` y `despliegue_microk8s.jsonl`. La función de cronometraje de `k6/despliegue.sh` no propagaba el código de salida de las fases; la corregí.
- El supuesto de planificación de 20–25 min por construcción era incorrecto para K3s (≈ 5–7 min) y razonable para MicroK8s solo en el extremo bajo (13–16 min medidos). Solo valen los tiempos medidos.
- **Desviación del diseño:** la Etapa 2 pide ciclos dedicados de destroy/apply; estos ciclos son las reconstrucciones de la secuencia de pilotos. No son ciclos aislados y lo declaro.
- Si un escenario del diseño no se ejercita en el piloto, lo declaro como no ejercitado y no lo marco como validado (hoy los tres escenarios se ejercitaron en ambas distribuciones, pero el piloto de energía no es confiable por la anomalía de 7.4, punto 6).
