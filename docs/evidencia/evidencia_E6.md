# Evidencia E6 (Etapa 4): desfase de ≈ 1 W, análisis retrospectivo y diagnóstico

Estado al 16-nov-2026. La capa 1 (retrospectiva) está hecha. La capa 3 (diagnóstico dirigido) se documenta aquí cuando esté lista. Todo lo de este archivo es **exploratorio**: orienta el diagnóstico del 19-nov y no concluye la causa.

## 1. Capa 1 · Análisis retrospectivo (`analysis/desfase_retro.py`)

```bash
python3 -m analysis.desfase_retro --salida analysis/salidas/2026-11-16_desfase_retro
python3 -m analysis.desfase_retro --autotest
```

### 1.1 Datos usados

| Rótulo | Carpeta | Configuración |
|---|---|---|
| J1 (jornada 1) | `data/exploratorio/2026-10-26_<dist>` | inicial (NGINX estático, `500m`, 900/1600 rps) |
| J2 (jornada 2) | `data/pilotos/2026-10-27_<dist>` | inicial |
| VI (validación integral) | `data/verificacion/2026-10-27_<dist>_T-22` | definitiva (SHA-256, `2000m`, 450/900 rps) |
| J3 (jornada 3) | `data/pilotos/2026-10-28_<dist>` | definitiva |
| J4 (jornada 4) | `data/pilotos/2026-11-02_<dist>` | definitiva |
| J4c (control de J4) | `data/pilotos/2026-11-02_<dist>_control` | definitiva, solo `media` |
| Reposo | `data/reposo/reposo_host_s0[1-3].json` | host sin VMs, 25-oct |

Son 96 corridas (las de fallo se excluyen: su ventana incluye la inyección) y 9 ventanas de reposo. El rótulo de cada jornada sigue el informe 3, sección 5.

### 1.2 Qué contiene cada ventana (revisado antes de concluir)

`contenido_ventanas.csv` lo registra por corrida. En las 96:
- 18 muestras de Prometheus por serie en la fase estable (scrape de 10 s en 180 s).
- CPU del host por núcleo y por modo (`user`, `nice`, `system`, `iowait`, `irq`, `softirq`, `steal`, `idle`) y `node_cpu_guest_seconds_total`; CPU de las VMs por modo; memoria completa de `/proc/meminfo`; red y disco por dispositivo; frecuencia y carga según Scaphandre; kube-state-metrics.
- **No hay datos por proceso de Scaphandre** (el filtro `scaph_(host|socket|self)_.*` los descarta), ni C-states, ni KSM, ni halt polling, ni interrupciones: esas covariables solo existen en la instrumentación nueva (E3).
- Los metadatos aportan temperatura al inicio, los 10 procesos con más CPU (una foto de `top` antes de la corrida), carga, memoria disponible y reloj.
- El reposo del host solo existe del 25-oct, sin VMs: no hay referencia por sesión.

Para comparar sesiones uso solo las corridas `idle` (sin tráfico), porque no dependen de la aplicación ni de la tasa, que cambiaron entre la configuración inicial y la definitiva.

### 1.3 Niveles de potencia en idle (`sesiones.csv`)

Regla de agrupamiento (propia): ordeno el idle medio de cada sesión × distribución y abro un nivel nuevo con cada salto mayor que 0,3 W (el umbral de «mueve el nivel» del diagnóstico).

| Nivel | Idle (W) | Sesiones |
|---|---|---|
| 1 | 4,157 a 4,158 | J3 K3s, J3 MicroK8s, J4 MicroK8s |
| 2 | 4,894 a 4,965 | J2 K3s, VI K3s, VI MicroK8s |
| 3 | 5,749 a 5,877 | J1 K3s, J1 MicroK8s, J2 MicroK8s, J4 K3s |

- Son **tres niveles**, no dos, separados por ≈ 0,8 W cada uno. Dentro de un nivel, el idle varía menos de 0,13 W entre sesiones, con aplicaciones distintas.
- Reposo del host sin VMs: 2,52 a 2,73 W.
- Un salto dentro de una sesión (`saltos_en_sesion.csv`): J1 K3s `media` r1 7,137 W contra 5,264 y 5,217 W en r2 y r3 (el caso ya descrito en `evidencia_T-20.md`, 7.4 punto 6). Las `idle` de J1 K3s (19:21 a 20:00) están en el nivel 3, y las `media` r2 y r3 (23:12 a 23:21) quedan ≈ 1 W bajo la `media` de J2 K3s (nivel 2): el clúster bajó del nivel 3 al 1 dentro de la jornada, después del playbook del host y de `salir`/`entrar`.
- En J4, el mismo día, K3s quedó en el nivel 3 y MicroK8s en el 1.

### 1.4 Covariables y nivel (`covariables.csv`)

Para cada covariable: Spearman entre el idle medio y la covariable (10 sesiones con idle; p nominal, sin corrección por comparaciones múltiples) y si separa los niveles sin solaparse.

**Ninguna covariable separa los tres niveles.** No acompañan al nivel:
- CPU del host por modo, incluidos `guest`, `steal`, `irq` y `softirq`; CPU ocupada por grupo de núcleos (0–1 de k6, 2–7 de las VMs, 8–15 del resto); CPU de las VMs. Las medias por nivel difieren en menos de 1,1 puntos porcentuales, y el nivel 3 tiene la menor ocupación de los núcleos de las VMs (10,6 % frente a 11,7 y 11,5 %).
- Frecuencia según Scaphandre (1856 MHz en todos los niveles), carga, memoria disponible, `AnonHugePages`, caché, swap, escritura a disco y tráfico Wi-Fi y de la red del laboratorio.
- `ksmd` entre los 10 procesos con más CPU: aparece en sesiones de los tres niveles (J2 K3s, J2 MicroK8s, J4 MicroK8s y J4 K3s).
- Reloj: desfase del host y espera de convergencia.

El host hace el mismo trabajo medible en los tres niveles, con una potencia distinta. Eso apunta a algo que estas fuentes no registran: residencia en C-states, halt polling, KSM o ubicación de los hilos de QEMU, que son los factores del diagnóstico.

Acompañan parcialmente al nivel (rho > 0,6, sin separar los niveles):
- **Contenedores en el host (`veth_presentes`, rho = 0,64).** Ver 1.5.
- **Temperatura al inicio** (rho = 0,72; 50,8 °C en el nivel 3 frente a 46,5 y 47,0 °C). Puede ser consecuencia de la potencia y no causa; la tomo como covariable, no como candidato.
- Tráfico en los puentes de contenedores (rho = 0,75): unos bytes por segundo en 3 corridas; depende de lo anterior.

### 1.5 Hallazgo: contenedores de incus corriendo durante las mediciones

Las interfaces `veth` del host son de dos contenedores de incus (`ssh-client` y `ssh-server`, otro proyecto del equipo; verificado con `incus list` el 16-nov). El modo medición detiene `incus.service`, pero los contenedores siguen corriendo: sus procesos (`[lxc monitor]` y los del contenedor) no son servicios de systemd y la política solo compara unidades (`unidades_fuera_de_la_lista`). Por eso `estado_host` no los detectó.

| Nivel | Sesiones con contenedores (2 `veth`) |
|---|---|
| 3 | J1 MicroK8s, J2 MicroK8s, J4 K3s (no en J1 K3s `idle`) |
| 2 | VI MicroK8s (no en J2 K3s ni VI K3s) |
| 1 | ninguna |

No basta para explicar el nivel: J1 K3s `idle` estuvo en el nivel 3 sin contenedores, y J1 K3s `media` r2 y r3 bajaron de nivel con los contenedores presentes. Pero es una carga no controlada en el host, en ambas distribuciones, y no aparece en ningún registro salvo en la lista de dispositivos de Node Exporter.

**Decisión (16-nov, cambio del estado de medición):**
- `tesis-modo-medicion entrar` detiene los contenedores de incus que estén corriendo (`incus stop`, con `--force` si no terminan en 30 s) antes de detener las unidades, y los registra en `/run/tesis-medicion.estado`. `salir` los vuelve a iniciar.
- `estado_host` registra `contenedores` (interfaces `veth` y monitores `[lxc monitor]`) y, si hay alguno, lo agrega a los motivos: la corrida queda no válida para la campaña y el diagnóstico lo ve en sus precondiciones.
- No se agrega un factor `contenedores` al diagnóstico: con la decisión anterior no estarán presentes en la campaña, y los datos ya muestran que no bastan para explicar el nivel. La fase `serie` del jueves, sin contenedores, muestra si el nivel 3 aparece igual.

**Qué probé:** la detección con los contenedores corriendo (2 `veth` y 2 monitores, motivo agregado), el autotest de `estado_host`, la sintaxis de `tesis-modo-medicion` y la lista de contenedores corriendo que usa. **Qué no probé:** `entrar` y `salir` con los contenedores (exigen cerrar la sesión gráfica); se verifican al inicio del diagnóstico.

### 1.6 Límites

- Diez sesiones con idle, un solo equipo; las corridas de una sesión son consecutivas y no son réplicas independientes. Las p son nominales y no son pruebas.
- Las covariables de C-states, KSM, halt polling, interrupciones y afinidad de QEMU no existen en estos datos.
- La temperatura y los procesos son una foto antes de la corrida, no una medida de la fase estable.
- La asignación de J4c al nivel de J4 es un supuesto (mismo clúster, mismo día, una hora antes, y potencia de `media` igual: 6,827 y 6,830 W en K3s).
- No hay reposo del host por sesión: no separo cuánto del nivel es del host y cuánto de las VMs.

## 2. Capa 3 · Diagnóstico dirigido

### 2.1 Qué cambió

| Archivo | Cambio |
|---|---|
| `k6/diagnostico/diagnostico_desfase.py` | Cada ventana guarda también el resumen del muestreador local (memoria, swap, temperatura, frecuencia). La foto del host ya incluía `tesis-kvm-stats` desde E3. Modos nuevos `reconstruccion`, `reinicio` y `confirmacion` (sección 2.2). Ciclos por defecto según el modo (los del plan). |
| `k3sHA/terraform/` y `microk8sHA/terraform/` | Variable `emulatorpin`, vacía por defecto. Con un valor, la misma plantilla XSLT que inyecta `vcpupin` agrega `<emulatorpin cpuset="…"/>`. Vacía, la plantilla genera el mismo texto que antes (comparado con `terraform console`). Se activa con `TF_VAR_emulatorpin=8-15`. |
| `k6/medicion/tramo.py` | Si el diagnóstico corre con `sudo` (factores que escriben en `/sys`), `despliegue.sh` corre como el operador (`sudo -u $SUDO_USER`), así que Terraform y Ansible nunca corren como root. |
| `analysis/diagnostico.py` | Regla de decisión fijada (sección 2.3). |

### 2.2 Modos

| Modo | Qué hace | Clúster |
|---|---|---|
| `reconstruccion` | por ciclo: ventana de referencia del host (120 + 180 s, sin VMs), construcción, verificación, calentamiento de 120 s, 3 ventanas idle y destrucción | destruye el que esté arriba y lo deja destruido |
| `reinicio` | `virsh shutdown` de las 3 VMs, espera a que se apaguen, `virsh start`, espera a la verificación (hasta 600 s), calentamiento y 3 ventanas idle | necesita uno arriba |
| `confirmacion` | igual a `reconstruccion`, con el factor en su estado B durante todo el ciclo. `emulatorpin` usa la versión persistente (Terraform); `ksm`, `haltpoll` y `cstates` se aplican antes del primer ciclo y se restauran al final | igual a `reconstruccion` |

El campo `ciclo` del registro de despliegue del diagnóstico es 300 + ciclo, en `data/diagnostico/<fecha>/despliegue_k3s.jsonl`.

### 2.3 Regla de decisión (`analysis/diagnostico.py`)

En `abab`, la media de cada condición (A1, B1, A2, B2) sale de sus 3 ventanas.
- **Mueve el nivel:** |B − A| ≥ 0,3 W en ambos pares, con |A1 − A2| ≤ 0,05 W y |B1 − B2| ≤ 0,05 W.
- **Descartado:** |B − A| < 0,1 W en ambos pares.
- **No concluyente:** cualquier otro caso.

Si varios factores mueven el nivel, se elige el de mayor |B − A| medio. Si hubo confirmación, el rango de las medias por construcción con el factor debe ser menor o igual que el de `reconstruccion` sin factor. Salidas: `condiciones.csv`, `veredictos.csv` y `decision.json`. La decisión final la toma el usuario.

### 2.4 Qué probé (16-nov, `--simulacro`, ventanas de 10 s, fuera del modo medición, K3s)

| Prueba | Resultado |
|---|---|
| `reconstruccion --ciclos 1` | referencia, construcción (5 min), verificación, 3 ventanas, destrucción; sin VMs al terminar |
| Construcción con `TF_VAR_emulatorpin=8-15` | las 3 VMs con `<emulatorpin cpuset='8-15'/>` en `dumpxml` y en `virsh emulatorpin`, junto a los `vcpupin` de siempre |
| `reinicio` | shutdown, start, verificación y 3 ventanas, sin errores (corrió 3 reinicios: el valor por defecto era 3; ahora es 1) |
| `abab --factor emulatorpin` | 4 condiciones; restauró el valor original. En esta prueba A y B coincidían, porque el clúster ya se había construido con el emulador fijado |
| `confirmacion --factor emulatorpin --ciclos 1` | referencia, construcción con la variable, 3 ventanas y destrucción |
| `analysis.diagnostico` sobre esos archivos | tabla por condición y veredicto «no concluyente» para `emulatorpin` (como era de esperar) |
| Autotest de `analysis.diagnostico` | regla en sus tres casos, elección por mayor diferencia, confirmación |
| Camino con `sudo` (lo corrió el usuario, 16-nov): `sudo … --fase confirmacion --factor haltpoll --ciclos 1 --simulacro` | sin abortar; `halt_poll_ns` en 0 durante las ventanas (instrumentación) y de vuelta en 200000 al final; registro y logs del despliegue a nombre del operador; sin VMs al terminar. Un intento anterior, interrumpido con Ctrl+C a los 8 s, también restauró el factor |
| `sudo … --fase abab --factor ksm --simulacro` (usuario, 16-nov) | `ksm/run` 1 en A y 0 en B según la instrumentación de cada condición; restaurado en 1 |
| `sudo … --fase abab --factor cstates --simulacro` (usuario, 16-nov) | 32 archivos (C2 y C3 de 16 hilos); residencia de cpu0 en C3 de 0,915 en A y 0 en B (pasa a C1, 0,98); restaurados (0 archivos desactivados al final). Una ventana de 9,7 W en B2: actividad de la sesión gráfica, sin significado en simulacro |

**Corrección:** el estado B de `ksm` alternaba el valor original (0 ↔ 1). Ahora es siempre 0 (KSM en pausa), como define el plan. Fuera del modo medición, y también dentro (el modo no toca KSM), `run` vale 1.

### 2.5 Procedimiento del jueves 19 (lo ejecuta el usuario)

**Paso previo (hecho el 16-nov, sección 2.4):** prueba del camino con `sudo`.

```
cd ~/universidad/5to_año/tesis
sudo python3 -m k6.diagnostico.diagnostico_desfase --distribucion k3s --fase confirmacion --factor haltpoll --ciclos 1 --simulacro
cat /sys/module/kvm/parameters/halt_poll_ns        # debe volver al valor original
virsh -c qemu:///system list --name                # sin VMs
```
Si falla, devolver la salida completa.

**Jueves, desde la consola de texto, sin sesión gráfica, con corriente alterna.** Desde la raíz del repositorio:

```
sudo /usr/local/sbin/tesis-modo-medicion entrar
F=data/diagnostico/$(date +%F)
mkdir -p $F

# 0. Clúster K3s y etiqueta (≈ 6 min)
DESPLIEGUE_REGISTRO=$F/despliegue_k3s.jsonl DESPLIEGUE_LOG=$F k6/operacion/despliegue.sh k3s construir 300
python3 -m k6.operacion.etiqueta --distribucion k3s

# 1. Serie: 20 ventanas sin intervenir (≈ 62 min)
python3 -m k6.diagnostico.diagnostico_desfase --distribucion k3s --fase serie

# 2. ABAB de los cuatro factores (≈ 44 min cada uno); los tres primeros piden la contraseña
sudo python3 -m k6.diagnostico.diagnostico_desfase --distribucion k3s --fase abab --factor ksm
sudo python3 -m k6.diagnostico.diagnostico_desfase --distribucion k3s --fase abab --factor haltpoll
sudo python3 -m k6.diagnostico.diagnostico_desfase --distribucion k3s --fase abab --factor cstates
python3 -m k6.diagnostico.diagnostico_desfase --distribucion k3s --fase abab --factor emulatorpin

# 3. Ciclos de salir/entrar (≈ 46 min)
python3 -m k6.diagnostico.diagnostico_desfase --distribucion k3s --fase ciclos

# 4. Reconstrucción: 2 ciclos; destruye el clúster del paso 0 (≈ 45 min)
python3 -m k6.diagnostico.diagnostico_desfase --distribucion k3s --fase reconstruccion

# 5. Reinicio: necesita un clúster, se construye de nuevo (≈ 6 + 15 min)
DESPLIEGUE_REGISTRO=$F/despliegue_k3s.jsonl DESPLIEGUE_LOG=$F k6/operacion/despliegue.sh k3s construir 310
python3 -m k6.diagnostico.diagnostico_desfase --distribucion k3s --fase reinicio

# 6. ¿Hay candidato? Si la última línea nombra un factor, confirmarlo (≈ 45 min); si no, saltar al cierre
python3 -m analysis.diagnostico --datos $F --salida /tmp/diagnostico
sudo python3 -m k6.diagnostico.diagnostico_desfase --distribucion k3s --fase confirmacion --factor <factor>   # sin sudo si es emulatorpin

# Cierre
DESPLIEGUE_REGISTRO=$F/despliegue_k3s.jsonl k6/operacion/despliegue.sh k3s destruir 310   # solo si quedó arriba (sin confirmación)
sudo /usr/local/sbin/tesis-modo-medicion salir
```

- **Total:** ≈ 6 h 10 min sin confirmación y ≈ 7 h con ella.
- El límite es el término del jueves. Lo que no alcance no se hace, en este orden de descarte: confirmación, reinicio, reconstrucción.
- Si un paso termina con `ABORTADA`, anotar el motivo y seguir con el siguiente. Si quedó un factor sin restaurar (`ERROR al restaurar`), no seguir y avisar.
- Al iniciar, `entrar` debe mostrar la detención de los contenedores de incus (`ssh-client` y `ssh-server`). Al final, `salir` los vuelve a iniciar: comprobarlo con `incus list`.

**Qué devolver:** la carpeta `data/diagnostico/<fecha>/` completa (JSON por fase, registro de despliegue y `registros/`) y la salida en pantalla de los pasos que hayan fallado. El veredicto lo calculo el viernes con `analysis.diagnostico`.

### 2.6 Resultado del diagnóstico (18-nov, adelantado un día)

Corrió completo en K3s, en modo medición: serie, los cuatro ABAB, ciclos, reconstrucción (ciclos 301 y 302) y reinicio (ciclo 310). La confirmación no corrió, porque no hubo candidato. Datos en `data/diagnostico/2026-11-18/`; salida del análisis en `analysis/salidas/2026-11-18_diagnostico/`.

**Veredicto con la regla de 2.3:**

| Factor | Diferencia B − A, par 1 y par 2 | Veredicto |
|---|---|---|
| ksm | −0,003 / −0,024 W | descartado |
| haltpoll | +0,014 / −0,036 W | descartado |
| emulatorpin | −0,009 / +0,039 W | descartado |
| cstates | +0,213 / +0,239 W | no concluyente: apagar C3 sube la potencia, pero no alcanza 0,3 W |

Ningún factor cumple la regla, así que la causa queda no resuelta.

**Observación exploratoria.** El nivel de reposo tomó tres valores el mismo día, cada uno con una sd de ≈ 0,01 W dentro de su condición:

| Condición | Media |
|---|---|
| Serie, ABAB y base de los ciclos (clúster c300, construido antes de `entrar`) | 4,86 a 4,93 W |
| Después del primer `salir` y `entrar` de los ciclos (los tres ciclos) | 4,14 a 4,17 W |
| Construcciones dentro del modo medición (c301, c302) | 5,79 W |
| Tras reiniciar las VMs (c310) | 5,76 W |

Entre esos niveles no cambia ninguna covariable registrada:
- residencia en C3 de los núcleos de las vCPU (0,66 a 0,68) y del resto (0,98);
- CPU de las vCPU (0,62 a 0,64 núcleos) y del emulador;
- interrupciones del host;
- salidas de KVM;
- frecuencia media (1433 a 1461 MHz);
- temperatura;
- estado del host registrado (perfil, EPP, perfil de plataforma, boost y gobernador).

Las páginas compartidas por KSM no siguen los niveles: 2865 en la serie, ≈ 660 000 en los ciclos y 0 tras construir.

**Interpretación (mía, no demostrada).** Si el salto no se ve en los núcleos, podría estar en el SoC. En este equipo (AMD, iGPU 0x1002), el paquete de RAPL también incluye la fábrica de datos, el controlador de memoria y la iGPU. El equipo expone `pp_dpm_fclk`, con los niveles 400, 800, 1200 y 1333 MHz, y hasta ahora no se registraba.

**Cambios del 19-nov:**
- `k6/lib/recursos.py`: el muestreador de 2 s registra el nivel activo de `fclk` y de `socclk`, y la potencia PPT de amdgpu. El resumen de la fase estable da la fracción de muestras en cada nivel y la PPT media. Sirve para la campaña y para el diagnóstico. Leer esos archivos de sysfs consulta al firmware del SoC cada 2 s, un costo que no medí.
- `k6/diagnostico/diagnostico_desfase.py`: nuevo factor `fclk`, en el que B fija los relojes del SoC en su máximo (`power_dpm_force_performance_level` = `high`). Además, `--fase ciclos` acepta `--factor`, que deja B aplicado durante toda la fase.
- `analysis/diagnostico.py`: agrega la regla de la prueba de fclk, fijada antes de medir. Se describe en 2.7.

### 2.7 Prueba de fclk (jueves 19, lo ejecuta el usuario)

**Regla, fijada antes de medir** (`analysis/diagnostico.py`, `prueba_fclk`). A son los ciclos y la reconstrucción sin factor; B son los ciclos y la confirmación con `fclk`.
- Si el rango de las medias de condición en A es menor que 0,3 W, no hubo desfase que explicar y el resultado es no concluyente.
- Si en A es de al menos 0,3 W y en B es de a lo sumo 0,1 W, fclk fija el nivel. En ese caso se propone fijarlo en `tesis-modo-medicion`; la decisión final es del usuario.
- En otro caso, fclk no fija el nivel.

Además se informa, de forma descriptiva, si el nivel de fclk cambia junto con la potencia en A.

**Paso previo, fuera del modo medición** (unos 10 s). Comprueba que el firmware acepta el cambio:

```
G=/sys/class/drm/card1/device
cat $G/power_dpm_force_performance_level          # auto
sudo sh -c "echo high > $G/power_dpm_force_performance_level"
cat $G/pp_dpm_fclk                                 # el * debe quedar en 1333Mhz
sudo sh -c "echo auto > $G/power_dpm_force_performance_level"
cat $G/power_dpm_force_performance_level          # auto
```

Si el `echo high` da error o el `*` no se mueve, no corras la prueba y avísame.

**Prueba, desde la consola de texto:**

```
cd ~/universidad/5to_año/tesis
tmux new -s fclk
sudo /usr/local/sbin/tesis-modo-medicion entrar
F=data/diagnostico/2026-11-19
mkdir -p $F

# 0. Clúster K3s y etiqueta (≈ 6 min)
DESPLIEGUE_REGISTRO=$F/despliegue_k3s.jsonl DESPLIEGUE_LOG=$F k6/operacion/despliegue.sh k3s construir 300
python3 -m k6.operacion.etiqueta --distribucion k3s

# 1. Ciclos sin factor, A (≈ 46 min)
python3 -m k6.diagnostico.diagnostico_desfase --distribucion k3s --fase ciclos

# 2. Ciclos con fclk, B (≈ 46 min)
sudo python3 -m k6.diagnostico.diagnostico_desfase --distribucion k3s --fase ciclos --factor fclk

# 3. Reconstrucción sin factor, A (≈ 45 min; destruye el clúster del paso 0 y lo deja destruido)
python3 -m k6.diagnostico.diagnostico_desfase --distribucion k3s --fase reconstruccion

# 4. Confirmación con fclk, B (≈ 45 min)
sudo python3 -m k6.diagnostico.diagnostico_desfase --distribucion k3s --fase confirmacion --factor fclk

# Análisis y cierre
python3 -m analysis.diagnostico --datos $F --salida /tmp/diagnostico | tail -2
cat /sys/class/drm/card1/device/power_dpm_force_performance_level   # auto
sudo /usr/local/sbin/tesis-modo-medicion salir
```

- **Total:** ≈ 3 h 10 min.
- Si un paso termina con `ERROR al restaurar`, no sigas y avísame: `power_dpm_force_performance_level` quedaría en `high`.
- La confirmación construye con el ciclo 300 + n. Los pasos 3 y 4 repiten ciclos de registro dentro de la misma carpeta, pero la fase y la hora quedan en cada fila.

**Qué devolver:** las dos últimas líneas del análisis. La carpeta la leo directamente.
