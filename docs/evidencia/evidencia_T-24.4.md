# Evidencia T-24.4: pendientes técnicos previos a la campaña

Estado al 27-oct-2026. Aquí dejo preparados el diagnóstico del desfase de ≈ 1 W, la instrumentación y el borrador del plan de la campaña. **No ejecuté el diagnóstico ni medí nada para la campaña**: lo que hay son herramientas probadas en modo simulacro y planes por confirmar. El diseño de sesiones y el análisis propuesto están en `evidencia_T-21.md`, sección 4.5.

## 1. Estado de cada parte del criterio

| Parte | Estado |
|---|---|
| Pilotos de energía con la aplicación definitiva (SHA-256, `2000m`, `media` 450 y `alta` 900 rps) en ambas distribuciones | Pendiente |
| K3s construido por el flujo completo de Ansible con la aplicación definitiva, sin ajustes manuales | Pendiente |
| Contadores por repetición (C-states, KSM, temperatura, hilos de QEMU) | Instrumentación escrita y probada (sección 2); **no está integrada en `k6/medicion/orquestador.py`**: hoy solo la usa el diagnóstico |
| Experimento diagnóstico del desfase de ≈ 1 W | Script escrito y probado en simulacro; no ejecutado (sección 3) |
| Desbordamiento del contador RAPL en el análisis de Scaphandre | Pendiente (análisis de la Etapa 4) |
| Plan de la campaña | Generador y borrador; sin fijar ni etiquetar (sección 4) |
| Pre-registro fijado antes del primer bloque: etiqueta `plan-campana-v1`, número de bloques y repeticiones, secuencia con semilla, reglas de exclusión y plan de análisis (Wilcoxon exacto por bloque, t pareada complementaria, Hodges-Lehmann, Holm por familias, modelo mixto como sensibilidad) | Pendiente; la propuesta está en `evidencia_T-21.md`, sección 4.5 |

## 2. Instrumentación (`k6/lib/instrumentacion.py`)

Toma una foto de contadores acumulados antes y después de una ventana y calcula diferencias y tasas, en vez de fotos de `top`. Un error de lectura queda en el JSON y no detiene la corrida.

| Origen | Qué registra |
|---|---|
| Host | residencia y entradas de cpuidle por CPU y por estado; interrupciones por CPU y las 10 IRQ con más actividad; CPU acumulada por hilo de cada QEMU, clasificada en vCPU, emulador/E/S, `vhost` y otros; CPU de `ksmd` y contadores de KSM; parámetros de halt polling de KVM; temperatura; frecuencia |
| Cada VM (por SSH) | driver y gobernador de cpuidle, residencia, interrupciones por segundo y por IRQ, cambios de contexto, CPU por modo |

**Qué verifiqué** (con las 3 VMs de K3s levantadas por Terraform, sin clúster, y destruidas después):
- Autotest sintético, y lectura real del host y de las 3 VMs.
- En la prueba encontré dos errores míos y los corregí: la CPU de QEMU por clase daba valores negativos cuando terminaba un hilo (ahora cuento solo los hilos presentes en las dos fotos), y el nombre de las IRQ de las VMs salía como la última palabra de la descripción.
- Observado en el host (valores de una prueba de 10 s, no son resultados): estados de cpuidle `POLL`, `C1`, `C2` y `C3`; `halt_poll_ns` de KVM en 200000 con crecimiento 2 y reducción 2; KSM con `run` en 1 y sin páginas compartidas.
- Observado en las VMs: no hay driver de cpuidle (`driver_cpuidle` vacío), así que no se registra residencia de estados dentro del invitado. No verifiqué cómo se queda ocioso el invitado.

**Límites.** Los hilos de QEMU que nacen o terminan dentro de la ventana no se cuentan. La foto añade ≈ 0,3 s a la ventana por el SSH a las VMs (ventanas de 10 s medidas de 10,29 s), y la potencia usa solo las lecturas de RAPL, sin ese retraso. La instrumentación no mide nada sobre `vhost` bajo carga, porque las pruebas fueron en reposo.

## 3. Diagnóstico del desfase de ≈ 1 W (`k6/diagnostico/diagnostico_desfase.py`)

### 3.1 Qué intenta distinguir

El nivel de potencia absoluta cambia ≈ 1 W entre series con la misma carga (`evidencia_T-20.md`, 7.4 punto 6). Candidatos: residencia de C-states, KSM, halt polling del host o del invitado, ubicación de los hilos de QEMU, estado del host tras `salir`/`entrar`, factores térmicos. Para el diseño de la campaña necesito además saber si el nivel es compartido dentro de un bloque (`evidencia_T-21.md`, 4.5).

### 3.2 Secuencia

Todas las ventanas son de reposo (clúster arriba, sin k6), de 180 s, con 120 s de calentamiento tras cada cambio de condición. Empezar por K3s, que es la distribución que cambió de nivel.

| Fase | Qué hace | Duración calculada con los parámetros por defecto |
|---|---|---|
| 1. `serie` | 20 ventanas seguidas sin intervenir | ≈ 62 min |
| 2. `ciclos` | 3 ventanas de base y luego 3 ciclos de `salir`, espera de 30 s, `entrar` y 3 ventanas | ≈ 46 min |
| 3. `abab` con un factor | A, B, A, B con 3 ventanas por condición | ≈ 44 min por factor |
| 4. Repetir 1 y 2 en MicroK8s | Comprobar si MicroK8s puede bajar al nivel bajo; exige reconstruir el clúster | ≈ 1,8 h más la construcción |

Las duraciones son un cálculo con los parámetros, no una medición. Las fases 1 a 3 con dos factores suman ≈ 3,3 h; el límite de cada invocación es de 4 h (`--limite-h`). Solo se hace la fase 3 con los 1 o 2 factores cuya covariable se movió con el nivel en las fases 1 y 2; no se prueban todos a la vez. Un tercer paso a mano no automatizado: para distinguir un cambio por arranque de las VMs, apagarlas y encenderlas (`virsh shutdown`/`virsh start`) y correr `serie --ventanas 3`.

### 3.3 Factores del ABAB

| Factor | B (el cambio) | Requiere |
|---|---|---|
| `ksm` | pausa KSM (`/sys/kernel/mm/ksm/run` en 0) | root |
| `haltpoll` | `halt_poll_ns` de KVM en 0 | root |
| `cstates` | deshabilita los estados de cpuidle 2 en adelante en todas las CPU (`C2` y `C3`) | root |
| `emulatorpin` | fija el hilo del emulador de cada VM en las CPU 8 a 15 (`virsh emulatorpin --live`) | grupo `libvirt` |

El estado A es el original, que el script lee y guarda en el JSON (`factor_original`), y lo restaura al terminar. `emulatorpin` no cubre los hilos `vhost`: no verifiqué si heredan la afinidad. Se aplica en vivo, no por Terraform, porque es un experimento y no un cambio de la infraestructura; no persiste al recrear las VMs.

### 3.4 Reglas de aborto y de parada (umbrales míos)

- **Aborto** tras cada ventana: más de 4 h, temperatura del CPU > 85 °C, memoria disponible < 1024 MB (el umbral del orquestador), reloj sin converger, o modo medición inactivo. Antes de empezar exige modo medición activo, sin sesión gráfica, sin k6 y SSH a las 3 VMs.
- **Un factor mueve el nivel** si |B − A| ≥ 0,3 W en los dos pares y A1 ≈ A2 y B1 ≈ B2 (dentro de 0,05 W). **Se descarta** si |B − A| < 0,1 W en los dos pares. Entre 0,1 y 0,3 W es no concluyente. La dispersión dentro de una serie fue de 0,018 W (`evidencia_T-21.md`, 4.2), pero estos umbrales no están derivados de una prueba.
- **Parada:** se detiene cuando un factor reproduce el cambio de nivel en ABAB o cuando se agota el límite de tiempo. En el segundo caso la causa se declara no resuelta y no se ajusta más.
- El script no escribe el veredicto: queda `pendiente de análisis` en el JSON.

### 3.5 Cómo se ejecuta y qué devolver

Lo lanzo yo desde la consola de texto, con la herramienta de asistencia de línea de comandos cerrada, el clúster arriba y el modo medición activo (`sudo /usr/local/sbin/tesis-modo-medicion entrar`).

```bash
python3 -m k6.diagnostico.diagnostico_desfase --distribucion k3s --fase serie
python3 -m k6.diagnostico.diagnostico_desfase --distribucion k3s --fase ciclos --ciclos 3
sudo python3 -m k6.diagnostico.diagnostico_desfase --distribucion k3s --fase abab --factor ksm
```

Cada corrida escribe en `data/diagnostico/<fecha>/`. Hay que devolver todos los JSON de esa carpeta. `--simulacro` acorta las ventanas y no exige las precondiciones.

**Qué probé:** `serie` y `abab` con `emulatorpin`, en simulacro, con las VMs de K3s levantadas por Terraform: el flujo corre, escribe el JSON, aplica el cambio (B) y restaura el original (`0-15` en las 3 VMs, verificado con `virsh`). Con la sesión gráfica abierta y el boost activo, esas potencias no significan nada. **Qué no probé:** `ciclos` (hace `salir` y `entrar` y cerraría una sesión gráfica abierta), los tres factores que piden root, ni nada con carga. Si se interrumpe una corrida de un factor sin dejarla terminar, el factor puede quedar aplicado; el JSON conserva `factor_original` para restaurarlo a mano.

## 4. Plan de la campaña (borrador)

`k6/medicion/plan_campana.py` genera `data/campana/plan_campana_v1.json`: 8 bloques, con las dos distribuciones en orden sorteado con una semilla (4 empiezan por K3s y 4 por MicroK8s), y en cada tramo `idle`, `media` y `alta` por repetición, con las tasas 450 y 900 rps y las fases de la Etapa 2 (30 s, 180 s, 30 s y 120 s de estabilización). Es determinista con la semilla; lo verifiqué generándolo dos veces. Con 2 repeticiones por celda son 96 corridas.

- **Semilla:** 20261028, la fecha de generación, no un valor elegido con criterio. El sorteo dio K3s, K3s, MicroK8s, MicroK8s, K3s, K3s, MicroK8s, MicroK8s en el primer lugar de cada bloque. No lo repetí con otra semilla para no elegirla después de ver el resultado.
- **Validez:** una corrida entra al análisis solo si el orquestador la marca `valida_para_campana` (modo medición, sin sesión gráfica, servicios permitidos, perfil, boost, memoria, corriente alterna). Las demás reglas de exclusión las fijo antes del primer bloque; no están decididas.
- **Repeticiones por celda:** 2 (1 si el tiempo aprieta), propuestas junto con los 8 bloques (T-21.4) y pendientes de fijar en el pre-registro (`evidencia_T-21.md`, 4.5).

**Sin hacer:** la etiqueta git `plan-campana-v1` (no la creo hasta fijar el plan) y un ejecutor de la secuencia de la campaña: `k6/medicion/secuencia_piloto.sh` corre pilotos (`--tipo piloto`) y no lee este plan.
