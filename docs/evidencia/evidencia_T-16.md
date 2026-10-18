# Evidencia de HU-16 (T-16.1 a T-16.4): medición energética con RAPL/powercap y Scaphandre

Fechas: 2026-10-12 (noche) y 2026-10-13 (tarde-noche). Todas las salidas provienen de mi terminal en el host (ThinkPad), operando por SSH desde otro equipo a partir del 13 de octubre. Hasta ahora solo se han ejecutado comandos de verificación y ventanas de prueba de 60 s; no hay mediciones experimentales ni ejecuciones de clústeres.

Convención: la sección 2 contiene hechos medidos u observados; la 3, interpretaciones no verificadas; la 4, decisiones y criterios; la 5, limitaciones; la 6, lo pendiente; la 7, los archivos asociados a esta evidencia.

## 1. Condiciones del equipo (REX-07)

| Parámetro | Valor |
|---|---|
| Equipo | Lenovo ThinkPad T14 Gen 2A |
| CPU | AMD Ryzen 7 PRO 5850U with Radeon Graphics |
| Sistema operativo | Ubuntu 24.04.5 LTS |
| Kernel | 7.0.0-34-generic |
| Driver de frecuencia | amd-pstate-epp |
| Gobernador | powersave |
| Perfil de energía | balanced |
| Boost de CPU | activado (1) |
| Alimentación | con corriente (online = 1), batería en estado Full |
| Sesión durante las mediciones | gráfica abierta (Google Chrome y terminal alacritty) en las lecturas del 12 de octubre; el 13 de octubre se operó por SSH; **la sesión gráfica estaba abierta** |
| Acceso remoto | `openssh-server` 1:9.6p1-3ubuntu13.19, habilitado y activo el 13 de octubre; escucha en 0.0.0.0:22 y [::]:22; autenticación por llave ed25519 funcionando; la autenticación por contraseña **sigue habilitada** (decisión mía) |
| Firewall | `ufw` inactivo; se agregó la regla para 192.168.1.0/24 hacia el puerto 22, pero sin efecto mientras `ufw` siga inactivo |
| Red del host | 192.168.1.23 (LAN); las demás direcciones corresponden a puentes de libvirt, Docker e Incus |

Las pruebas definitivas se harán sin sesión gráfica (SSH).

## 2. Hechos medidos u observados

### 2.1 T-16.2: RAPL/powercap

- `/sys/class/powercap/` expone `intel-rapl`, `intel-rapl:0` y `intel-rapl:0:0`.
- `intel-rapl:0` se llama `package-0`; `intel-rapl:0:0` se llama `core`. `intel-rapl` es el contenedor y no tiene nombre.
- Ambos `energy_uj` tienen permisos `-r-------- root root`: solo se leen con root.
- `max_energy_range_uj` vale 65 532 610 987 µJ en ambas zonas.
- No se ejecutó `modprobe`; las zonas ya estaban presentes.

Lecturas de potencia del 12 de octubre (ventanas de 10 s, tiempo real transcurrido, con corrección de desbordamiento):

| Lectura | package-0 (W) | core (W) |
|---|---|---|
| Reposo (serie 1, lectura 1) | 3,77 | 0,03 |
| Reposo (serie 1, lectura 2) | 3,44 | 0,03 |
| Carga, 4 hilos al máximo | 17,46 | 0,04 |
| Reposo tras la carga | 1,99 | 0,02 |

Seis lecturas adicionales en reposo (misma sesión gráfica):

| Lectura | package-0 (W) | core (W) |
|---|---|---|
| 1 | 2,87 | 0,03 |
| 2 | 3,49 | 0,05 |
| 3 | 3,12 | 0,03 |
| 4 | 5,09 | 0,09 |
| 5 | 3,94 | 0,04 |
| 6 | 3,46 | 0,06 |

Descriptivos de package-0 en estas seis lecturas (cálculo propio): mediana 3,48 W; rango intercuartílico 0,62 W (cuartiles inclusivos); media 3,66 W; desviación estándar 0,79 W; mínimo 2,87 W; máximo 5,09 W; coeficiente de variación 21,5 %.

### 2.2 T-16.1: Scaphandre

- Binario: `/usr/local/bin/scaphandre`, 11 931 032 bytes, SHA-256 `980b8124c75fa4b1411a4a172842d1c6a71593ab872c490d163d6decdba738a7`. Es idéntico al compilado en `~/scaphandre/target/release/scaphandre` (18:18 del 3 de septiembre).
- Origen: clon de https://github.com/hubblo-org/scaphandre.git compilado con Rust (confirmado por el reflog del clon; no lo recordaba).
- Clon en el tag `v1.0.3`, commit `b64443c447e24f25947111ec8611449f213eb0a5` (clon 18:16:27, checkout 18:16:37, zona -0400).
- `scaphandre --version` imprime 1.0.2 porque el `Cargo.toml` de ese commit dice `version = "1.0.2"`. La versión real es el tag/commit indicado.
- `git -C ~/scaphandre status --short` no imprimió nada (13 de octubre): sin cambios locales ni archivos sin seguir.
- Exportador `stdout`: potencia del host entre 2,32 y 5,63 W en las ventanas observadas; la primera ventana marca 0 W.
- Exportador `prometheus` (puerto 8080):
  - Energía: `scaph_host_energy_microjoules` (counter) y `scaph_socket_energy_microjoules{socket_id="0"}` (counter). No aparece una métrica de potencia instantánea del host.
  - Otras del host: memoria, swap, load average, `scaph_host_cpu_frequency` y disco (solo `/boot/efi`, no sirve para almacenamiento).
  - `scaph_self_*`: memoria residente de 21,4 MB y 0,10 % de CPU en una única muestra autorreportada; `scaph_self_topo_procs_nb` = 393.
  - `scaph_process_*`: 2753 líneas en una consulta, unas 120 veces más que las 23 líneas de host, zócalo y `self`. Es lo primero que devuelve `/metrics`.
- Unidad systemd `/etc/systemd/system/scaphandre.service` creada y habilitada; el 13 de octubre `systemctl is-active scaphandre` respondió `active` y `curl -s 127.0.0.1:8080/metrics` devolvió métricas.

```ini
[Unit]
Description=Scaphandre Prometheus exporter (energia del host)
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/scaphandre prometheus -a 127.0.0.1 -p 8080
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

### 2.3 Comparación de contadores, primera prueba (30 s, 12 de octubre)

| Dato | Valor |
|---|---|
| Crudo, lectura 1 | 11 422 350 214 µJ |
| Scaphandre, lectura 1 | 11 422 745 152 µJ |
| Delta crudo | 64 634 017 µJ |
| Delta Scaphandre | 64 767 144 µJ |
| Diferencia | +133 127 µJ (+0,21 %) |

### 2.4 T-16.3 / T-16.4: seis ventanas de 60 s (13 de octubre)

Script `ventana_energia.py`: lee el contador crudo de `package-0` y las métricas de Scaphandre en `t_inicio` y `t_fin`, y aplica la corrección de desbordamiento. La ventana A se imprimió en pantalla y no se guardó en archivo; las ventanas 1 a 5 están en `ventana_1.json` a `ventana_5.json`. Con sesión gráfica abierta.

| Ventana | Δt (s) | Crudo pkg-0 (µJ) | Scaph. host (µJ) | Scaph. socket (µJ) | Crudo (W) | host − crudo | socket − crudo |
|---|---|---|---|---|---|---|---|
| A | 60,050 | 142 981 436 | 142 798 127 | 142 843 077 | 2,381 | −0,128 % | −0,097 % |
| 1 | 60,048 | 137 686 254 | 137 481 584 | 137 578 945 | 2,293 | −0,149 % | −0,078 % |
| 2 | 60,024 | 170 824 356 | 172 087 368 | 171 998 414 | 2,846 | +0,739 % | +0,687 % |
| 3 | 60,026 | 169 867 879 | 171 408 860 | 171 393 908 | 2,830 | +0,907 % | +0,898 % |
| 4 | 60,026 | 211 609 723 | 213 131 877 | 213 165 596 | 3,525 | +0,719 % | +0,735 % |
| 5 | 60,024 | 264 953 415 | 266 325 979 | 266 364 399 | 4,414 | +0,518 % | +0,533 % |

Cálculos propios: la diferencia absoluta máxima es 0,907 % (host) y 0,898 % (socket). En potencia, las diferencias van de −0,003 a +0,026 W. En las ventanas 2 a 5 el exceso de Scaphandre sobre el crudo es de unos 1,17 a 1,56 J, aunque la potencia varió de 2,8 a 4,4 W. En las ventanas A y 1 la diferencia es negativa (−0,11 a −0,20 J). La potencia del crudo subió ventana a ventana (2,293; 2,846; 2,830; 3,525; 4,414 W).

### 2.5 T-16.4: prueba de intercalado (`bracket.py`, 20 muestras, 13 de octubre)

En cada muestra se lee el crudo (`a`), el contador de zócalo de Scaphandre (`s`) y el crudo de nuevo (`b`), con 3 s de pausa. Resultado: `s` quedó entre `a` y `b` en las **20 de 20** muestras.

| Medida (µJ, cálculo propio) | Mínimo | Mediana | Máximo |
|---|---|---|---|
| s − a | 0 | 29 791 | 338 606 |
| b − s | 260 226 | 403 437 | 586 837 |
| b − a (duración de la consulta en energía) | 274 049 | 447 373 | 925 443 |

Salida original (`i, a, s, b`):

```
0 5060780092 5061118698 5061705535
1 5068883448 5068938941 5069333467
2 5075879729 5075932781 5076337347
3 5082913469 5082918107 5083334452
4 5089994783 5089999345 5090401653
5 5096996313 5097053561 5097487346
6 5107894019 5108014908 5108427561
7 5114985358 5114989386 5115434279
8 5121864061 5121976329 5122383352
9 5129070338 5129074686 5129531648
10 5136531012 5136535497 5136975172
11 5143730102 5143730102 5144118418
12 5150636834 5150642114 5150910883
13 5161399888 5161403291 5161688433
14 5168084952 5168146762 5168406988
15 5174920994 5175075924 5175366818
16 5181937401 5181941993 5182227013
17 5188785298 5188873581 5189257762
18 5195867314 5195873844 5196266433
19 5202680758 5202745101 5203161614
```

### 2.6a T-16.3: comparación con Prometheus (ventana 6, 18 de octubre)

Prometheus 3.15.0 del host (T-17.2) scrapea Scaphandre cada 10 s. Se midió una ventana de 60 s con `ventana_energia.py` (`ventana_6.json`; no se registró si la sesión gráfica estaba abierta ni la carga del equipo durante la ventana) y se comparó con lo almacenado en Prometheus para el mismo intervalo con `consulta_prometheus.py`.

| Dato | Valor |
|---|---|
| Δt (s) | 60,057 |
| Crudo pkg-0 | 226 829 044 µJ (3,777 W) |
| Scaphandre host (lectura directa) | 226 315 384 µJ (3,768 W); −0,226 % respecto del crudo |
| Muestras de Prometheus dentro de la ventana | 6 (scrape de 10 s) |
| Prometheus, interpolación lineal entre las muestras que rodean `t_inicio` y `t_fin` | 225 881 081 µJ (3,761 W); −0,418 % respecto del crudo, −0,192 % respecto de Scaphandre directo |
| Prometheus, `increase(...[60s])` evaluado en `t_fin` | 230 622 961 µJ (3,840 W); +1,673 % respecto del crudo, +1,903 % respecto de Scaphandre directo |

La interpolación se recalculó a mano con las muestras reales y dio el mismo valor (225 881 081 µJ). Los incrementos entre muestras consecutivas equivalen a 2,98–4,97 W, es decir, la potencia varió dentro de la ventana.

El primer intento del script devolvió +1,7 % y 61 muestras porque `query_range` repite el último valor en cada paso; se corrigió leyendo las muestras crudas con su `timestamp` real. Ese resultado no se usa.

Interpretación (no verificada): la diferencia de `increase()` coincide con la extrapolación que hace esa función hacia los bordes de la ventana; no se comprobó con otras ventanas. La interpolación supone potencia lineal entre muestras y no se cuantificó su error. Una sola ventana.

### 2.6 Servicios activos en el host (listas de systemctl, 12 de octubre)

- Contenedores y virtualización: `docker` (con socket), `containerd`, `incus` (servicio, sockets y lxcfs), servicios `vbox*` habilitados.
- Libvirt: `virtlockd`, `virtlogd`, `systemd-machined`; `libvirtd` habilitado pero no aparece corriendo.
- Datos, MAAS y DHCP: `postgresql@16-main`, `snap.maas.pebble`; `isc-dhcp-server` e `isc-dhcp-server6` habilitados (no figuran corriendo); `openvpn` y `ufw` habilitados.
- Escritorio y periféricos: `lightdm`, `cups`, `cups-browsed`, `avahi`, `ModemManager`, `colord`, `udisks2`, `fwupd`, `snapd`.
- Actualizaciones y tareas periódicas: `unattended-upgrades` y varios timers (`apt-daily*`, `fstrim`, `man-db`, `motd-news`, `update-notifier-*`).
- `ssh` estaba deshabilitado y detenido el 13 de octubre antes de habilitarlo (ver sección 1).

## 3. Interpretación (no verificada)

- `package-0` responde a la carga (de unos 2 a 5 W en reposo a 17,46 W), por lo que el contador es sensible a la actividad del equipo.
- `core` se mantiene entre 0,02 y 0,09 W aunque el paquete llegue a 17 W. No se conoce la causa; se trata como observación y no se usa como medida de carga.
- El reposo varía entre lecturas (1,99 a 5,09 W) y subió ventana a ventana el 13 de octubre (2,29 a 4,41 W). No se determinó la causa; con sesión gráfica y servicios en segundo plano no se puede separar la variación del equipo de la de las aplicaciones.
- La prueba de intercalado indica que Scaphandre entrega el contador del instante de la consulta (siempre entre las dos lecturas del crudo), cerca del inicio de la consulta (mediana 0,03 J después de la lectura previa).
- Ese desfase solo explica diferencias de unos ±0,3 J por ventana. No explica el exceso de +1,2 a +1,6 J de las ventanas 2 a 5; la causa de ese exceso **sigue abierta**.
- Desbordamiento del contador (aritmética propia desde `max_energy_range_uj`): vuelta cada unos 62,6 min a 17,46 W, 5,2 h a 3,5 W, 7,6 h a 2,38 W y 8,5 h a 2,15 W. Probabilidad de que una ventana de 180 s contenga una vuelta: 4,8 %, 1 % y 0,6 % en los tres primeros casos de potencia (17,46, 3,5 y 2,15 W).
- Con `increase()` de Prometheus una caída se trata como reinicio y, en el peor caso, se perdería hasta un 5,6 % de la ventana (scrape de 10 s).

## 4. Decisiones y criterios vigentes

- `core` no se usa como medida.
- **Medida principal de energía:** lectura directa del contador crudo de `package-0` en `t_inicio` y `t_fin`, con corrección de la vuelta (suma de `max_energy_range_uj` si el delta es negativo). Scaphandre y Prometheus se usan como contraste. No se usa `increase()` para la energía de los experimentos. Fórmulas de REX-05: E_exp = E_final − E_inicial; EE = E_exp / N_válidas; P_media = E_exp / Δt.
- **Criterio de consistencia de T-16.4 (aceptado el 13 de octubre):** la diferencia de energía entre Scaphandre y el contador crudo debe ser menor al 2 % del crudo por ventana. Las seis ventanas lo cumplen (máximo 0,907 %). La pregunta de la sección 3 sobre el exceso de las ventanas 2 a 5 queda registrada como abierta.
- Prometheus descartará la alta cardinalidad con `metric_relabel_configs` (configuración propuesta, aún no aplicada):

```yaml
scrape_configs:
  - job_name: scaphandre
    scrape_interval: 10s
    static_configs:
      - targets: ['127.0.0.1:8080']
    metric_relabel_configs:
      - source_labels: [__name__]
        regex: 'scaph_(host|socket|self)_.*'
        action: keep
```

- Servicios: prefiero dejarlos activos por realismo (un host con Kubernetes suele tener otros servicios). Propuesta pendiente de mi decisión:
  - Controlar siempre actualizaciones, timers, `snap refresh --hold` y la sesión gráfica.
  - Decidir sobre Docker, Incus, PostgreSQL, MAAS y VirtualBox con una medición A/B de reposo (seis ventanas de 60 s o más por condición, criterio fijado antes de medir).
  - Revisar `docker ps` e `incus list` para descartar cargas reales.
  - Guardar la lista de servicios activos en los metadatos de cada ejecución.
  - Declarar en OE4 la limitación de host dedicado frente a host compartido.
- Acceso: SSH por llave desde otro equipo de la red local, con contraseña aún habilitada y `ufw` inactivo. Se evita activar `ufw` por posible interferencia con las reglas de libvirt, Docker e Incus (precaución, no verificada).

## 5. Limitaciones

- Lecturas con sesión gráfica abierta; el reposo de este documento no es el reposo experimental.
- Solo se leyeron dos zonas. No se verificó en fuentes qué energía cubre `package-0` en un AMD Zen 3; se describe como la zona observada y no se afirma qué incluye (RE-03).
- Ventanas de 10 s y 60 s, y pocas lecturas: sirven para comprobar acceso, respuesta y consistencia, no para caracterizar la variabilidad.
- La corrección del desbordamiento no se observó en una medición real; solo se estimó el periodo de vuelta por aritmética.
- La CPU y la memoria de Scaphandre provienen de una sola muestra autorreportada. El costo del propio muestreo (cada consulta tarda cientos de milisegundos y el exportador procesa más de dos mil líneas de procesos) no se midió.
- No se midió contra un instrumento externo.
- La ventana A no se guardó en archivo; sus valores se transcribieron de la pantalla.

## 6. Pendiente

### 6.1 Cierre de T-16.1 a T-16.4

1. ~~Pasar la compilación del tag fijado (`v1.0.3`, commit `b64443c`) y la unidad systemd a un rol de Ansible.~~ **Hecho (13 de octubre):** `ansible/roles/scaphandre/`, playbook `ansible/playbook.yml` (host físico, `connection: local`). Ejecutado con `ansible-playbook playbook.yml --ask-become-pass`: `ok=15 changed=4 failed=0`. El rol verifica al final que `/metrics` expone `scaph_host_energy_microjoules` (falla la corrida si no). Hallazgo durante la implementación: `rustc`/`cargo` del repositorio de Ubuntu 24.04 (1.75.0) no compilan Scaphandre v1.0.3 (`feature edition2024 is required`); el build manual original usaba `rustup` con toolchain 1.98.1 (`cargo --version` / `rustc --version` verificados), no el paquete de apt. El rol instala `rustup` con ese toolchain fijado (`scaphandre_rust_version: "1.98.1"`) en vez de los paquetes de apt.
2. ~~T-16.3: falta la consulta a Prometheus para la misma ventana (depende de T-17.2).~~ **Hecho (18 de octubre, una ventana):** sección 2.6a. Queda repetir con más ventanas si se quiere caracterizar la diferencia.
3. T-16.4: queda abierta la causa del exceso de +1,2 a +1,6 J en las ventanas 2 a 5. Repetir ventanas con el sistema en estado más controlado (sin sesión gráfica) para ver si se reproduce.
4. Ingresar las horas reales de T-16.4 en la hoja (no se estiman).
5. Hacer commit con esta evidencia (sección 7).

### 6.2 Host y servicios

1. Confirmar el método de acceso en los experimentos: TTY o SSH. Si es SSH, documentar la interfaz de red usada (Wi-Fi o cable).
2. Listar timers: `systemctl list-timers --no-pager`.
3. Decidir la política de servicios (sección 4) y ejecutar la medición A/B de reposo, con el criterio fijado antes de medir.
4. Caracterizar el reposo experimental sin sesión gráfica (seis ventanas o más).
5. Revisar `docker ps` e `incus list`.
6. Decidir si se desactiva la autenticación por contraseña de SSH y si se activa `ufw`.

### 6.3 Cadena técnica posterior

1. ~~T-17.1 a T-17.5~~ (Node Exporter, Prometheus, etiquetas, continuidad y kube-state-metrics): **hecho (18 de octubre)**; ver `evidencia_T-17.md`.
2. ~~T-18.1 a T-18.5~~ (aplicación de referencia, scripts de k6 y LoadBalancer de kube-vip en 192.168.100.150): **hecho (18 de octubre)**; ver `evidencia_T-18.md`.
3. `chrony`: host como fuente NTP y VMs como clientes solo de 192.168.100.1; no está implementado (HU-34).
4. T-19.x: pruebas de resiliencia.
5. T-32.1: orquestador de ejecuciones y escritor de metadatos.
6. T-20.x a T-22.x: pilotos, calibración de tasas y de CPU (T-20.5), mejoras y validación integral.

### 6.4 Encuesta y documentación (EP-06)

1. Fijar la regla de cierre de la encuesta (propuesta: hacia el 16 de octubre).
2. Al cierre, contar el grupo principal (responden «No» en perfil 3 y 4 y aprueban la comprobación).
3. Marcar T-33.1 como «Realizado» con horas reales; decidir sobre T-33.3.
4. T-33.2: tabular y analizar.
5. Informe de la Etapa 3: corregir la referencia «T-06.2» de la Tabla 4 para que apunte a T-20.5, actualizar el `.xlsx` del Project respecto de la hoja y registrar el hallazgo de que la documentación de HA de MicroK8s tiene casi dos años.

## 7. Archivos asociados a esta evidencia

Todos están en el directorio personal del host (`/home/coto/`), salvo la unidad systemd.

| Archivo | Contenido |
|---|---|
| `ventana_energia.py` | Mide una ventana de energía (crudo y Scaphandre) y emite JSON. Uso: `sudo python3 ventana_energia.py 60`. |
| `bracket.py` | Prueba de intercalado crudo – Scaphandre – crudo, 20 muestras. Uso: `sudo python3 bracket.py`. |
| `ventana_1.json` a `ventana_5.json` | Salidas de las ventanas 1 a 5 (sección 2.4). |
| `ventana_6.json` | Salida de la ventana 6, comparada con Prometheus (sección 2.6a). |
| `consulta_prometheus.py` | Compara una ventana JSON con las muestras de Prometheus. Uso: `python3 analysis/verificacion/consulta_prometheus.py docs/evidencia/ventana_6.json`. |
| `/etc/systemd/system/scaphandre.service` | Unidad del exportador (sección 2.2). |
| este documento | Resumen de hechos, interpretaciones, decisiones y pendientes. |

## 8. Criterio de aceptación

- T-16.2 «Contadores accesibles y dominio energético documentado»: cumplido con las reservas de la sección 5.
- T-16.1 «Scaphandre ejecuta y expone métricas energéticas»: **cumplido**, incluido el rol de Ansible (6.1).
- T-16.4 «Consistencia comprobada durante una ventana común»: cumplido con el criterio de menos del 2 % (sección 4); queda abierta la causa del exceso de las ventanas 2 a 5.
- T-16.3: cumplido con una ventana (sección 2.6a): la energía de la misma ventana se obtiene de Prometheus; con interpolación entre muestras la diferencia fue −0,418 % respecto del crudo, y con `increase()` +1,673 %. Reserva: una sola ventana.

Commit sugerido: `T-16.1 a T-16.4: verifica RAPL/powercap y Scaphandre v1.0.3; scripts de ventana y prueba de intercalado; evidencia en Ryzen 7 PRO 5850U`
