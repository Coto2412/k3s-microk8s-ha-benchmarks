# Evidencia E3 (Etapa 4): instrumentación integrada en el orquestador

Estado al 16-nov-2026. Cierra la parte de T-24.4 «instrumentación integrada en el orquestador» y aporta a T-24.3 los datos de instrumentación y memoria de cada corrida. Los metadatos pasan al esquema 3 (`data/README.md`).

## 1. Qué cambió

| Archivo | Cambio |
|---|---|
| `k6/lib/instrumentacion.py` | `kvm_stats()` (llama a `sudo -n tesis-kvm-stats`; si falla, «no disponible» sin detener la corrida) dentro de la foto del host. `foto_host()` y `foto_vms()` separan la foto local de la que va por SSH. `delta()` acepta fotos de solo host o solo VMs, agrega el intervalo que cubre y los deltas de KVM (`delta_kvm`, globales y por VM). |
| `k6/lib/recursos.py` | `Muestreador`: hilo que lee `/proc/meminfo`, `/proc/vmstat`, `k10temp` y `scaling_cur_freq` cada 2 s (≈ 1,5 ms por muestra, sin SSH). `resumen_muestreo()`: mínimo de MemAvailable y bandera de 1024 MB en la corrida; en la fase estable, mínimo de MemAvailable, páginas de swap movidas, temperatura media y máxima y frecuencia media. |
| `k6/lib/estado_host.py` | `estado_host(pol, memoria_invalida=False)`: el orquestador ya no invalida una corrida por la memoria al inicio; aplica la regla de la sección 3. El resto de los usos (calibración, validación, diagnóstico) no cambia. |
| `k6/medicion/orquestador.py` | Línea de tiempo de la sección 2, muestreador, regla de memoria, `--datos` (raíz de los datos; el simulacro usa `data/campana_simulacro/`, en `.gitignore`), esquema 3. |
| `data/README.md` | Campos nuevos de los metadatos. |

## 2. Línea de tiempo de una corrida

Con `t_e` = lanzamiento de k6 + rampa (inicio planificado de la fase estable) y `t_f` = `t_e` + fase estable:

| Momento | Qué | Por dónde |
|---|---|---|
| desde antes de la estabilización hasta el fin de k6 | muestreador cada 2 s | local |
| `t_e − 10 s` | foto de las VMs, en un hilo (si tarda, no retrasa RAPL) | SSH |
| `t_e − 5 s` | cgroups del plano de control (solo con `--cgroup-cp`) | SSH |
| `t_e − 1 s` | foto del host | local |
| `t_e` | lectura inicial de RAPL | local |
| `t_f` | lectura final de RAPL, inmediatamente después la foto del host y los cgroups | local; cgroups por SSH |
| `t_f + 5 s` | foto de las VMs | SSH |

**E3.4.** `--cgroup-cp` ya leía 5 s antes de la fase estable y justo después de su término (código de la Etapa 3), es decir, fuera de la ventana de RAPL. No hubo que moverlo.

Ninguna lectura por SSH cae dentro de la fase estable. Las fotos del host quedan fuera de la ventana de RAPL (1 s antes y justo después), así que su costo no entra en la energía medida; el intervalo de sus deltas es ≈ 1 s más largo que la fase estable y queda registrado (`dt_s`, `intervalo`). Si la foto inicial de las VMs terminara después de `t_e`, `foto_inicio_antes_de_fase_estable` queda en falso.

## 3. Regla de memoria (umbrales propios)

- MemAvailable < 1024 MB en algún momento de la corrida: `memoria_bajo_umbral: true`. **La corrida sigue en el análisis**; es un resultado por distribución.
- MemAvailable < 512 MB: el muestreador termina k6, la corrida queda `estado: abortada_memoria` con el motivo en `motivos_no_valida`, y el orquestador sale con el código **86** (k6 no usa ese código). Si ocurre antes de lanzar k6, sale con 86 sin escribir metadatos. El ejecutor (E5) usa ese código para abortar el tramo.
- Ambos umbrales son propios, sin derivar de una prueba. El de 1024 MB es el de la Etapa 3 (`estado_host.MEM_MIN_MB`); el de 512 MB es la mitad, como margen antes de que el sistema empiece a matar procesos.

## 4. Qué probé (16-nov, fuera del modo medición, K3s construido con `DESPLIEGUE_REGISTRO` en un directorio temporal y destruido al terminar)

Corridas de verificación con rampa 15 s, fase estable 30 s, descenso 10 s y estabilización 10 s, en `data/campana_simulacro/` (no versionado). Con la sesión gráfica abierta y el boost activo: las potencias no significan nada.

| Prueba | Resultado |
|---|---|
| `idle` con `--cgroup-cp` | `completa`; ventana de RAPL de 30,000 s (no se alarga); foto del host de 0,071 y 0,066 s, a −1,006 s y +0,006 s de la ventana; fotos de las VMs de 0,275 y 0,281 s, a −10,0 s (terminó a −9,7 s) y +5,0 s; cgroups a −5,0 s y +0,07 s; 35 muestras del muestreador (15 en la fase estable), sin errores |
| `media` a 50 rps | `completa`, k6 con código 0 |
| Aborto simulado a mitad de corrida (MemAvailable forzado a 300 MB desde los 25 s) | detectado 12,8 s después de lanzar k6; k6 terminado 0,4 s después; `estado: abortada_memoria`, `rapl` con error, `memoria_bajo_umbral: true`, código de salida 86 |
| Aborto simulado antes de lanzar k6 | mensaje y código 86, sin k6 en ejecución |
| `tesis-kvm-stats` con las VMs encendidas | 3 VMs con su nombre y contadores por VM (por ejemplo `halt_wakeup` 38 990 a 55 401 en 31 s por VM). Verifica la corrección pendiente de E2. |
| Autotests | `instrumentacion`, `recursos` (incluye el resumen del muestreo y un aborto del muestreador) y `estado_host` |

La foto de las VMs en el idle de prueba muestra 85,5 s de `idle` sobre 90 s posibles (2 vCPU × 45 s) en una VM: el intervalo de las fotos de las VMs es de 45 s, no de 30 s, porque cubre la rampa final y el descenso inicial.

## 5. Límites

- Las fotos de las VMs cubren la fase estable más ≈ 10 s antes y ≈ 5 s después: sus deltas incluyen parte de la rampa y del descenso. En `idle` no hay diferencia; en `media` y `alta`, la carga de esos segundos es menor que la de la fase estable.
- El muestreador detecta la memoria baja con hasta 2 s de retraso. Antes de lanzar k6, la detección espera a que termine la estabilización (hasta 120 s).
- No probé una corrida con la duración completa (180 s) ni con `--fallo`; la línea de tiempo es la misma y las esperas son absolutas, no acumuladas. Lo cubre el bloque 0.
- La temperatura y la frecuencia del muestreador son las del host; la frecuencia es la media de `scaling_cur_freq` de los 16 hilos, que con el gobernador `powersave` puede no reflejar la frecuencia efectiva.
