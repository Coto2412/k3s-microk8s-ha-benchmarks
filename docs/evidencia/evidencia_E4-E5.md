# Evidencia E4 y E5 (Etapa 4): mediciones por tramo y ejecutor de campaña

Estado al 16-nov-2026. Preparan T-24.1 y T-24.2 (campaña desatendida) y aportan a T-24.3 las mediciones de cada tramo.

## 1. E4 · Mediciones por tramo (`k6/medicion/tramo.py`)

Funciones que llama el ejecutor. Cada una devuelve un diccionario, y el ejecutor lo guarda en `data/campana/bNN_<dist>/tramo.json` (escritura atómica). Ninguna corre dentro de una fase estable.

| Paso | Función | Qué registra |
|---|---|---|
| E4.1 | `preparar_memoria()` | salida de `sudo tesis-preparar-memoria` (E2) y su duración |
| E4.2 | `referencia(120, 180)` | sin VMs (`virsh list`) ni k6: 120 s de espera y 180 s de RAPL, con foto del host al inicio y al término y el muestreador local; si aparece una VM durante la ventana, `ok: false` |
| E4.3 | `construir()` | `despliegue.sh <dist> construir <ciclo>` con RAPL al inicio y al término (J, con corrección de un desbordamiento), bytes de `/proc/net/dev` de la Wi-Fi y de los puentes `virbr*`, y la duración de cada fase tomada del registro de `despliegue.sh` |
| E4.4 | `verificar()` | las comprobaciones de la validación integral (`validacion.comprobar_ha`): nodos Ready, VIP del plano de control, VIP del servicio con el SHA-256 esperado, titulares de las VIP y límites de la aplicación; con reintentos cada 5 s hasta 60 s |
| E4.5 | `rtt()` | `recursos.medir_rtt`, la misma función de `--rtt` (20 muestras) |
| E4.6 | `plano_control()` | por nodo y por unidad (`k3s.service`; `snap.microk8s.daemon-kubelite`, `-k8s-dqlite` y `-containerd`): PID y nombre de cada proceso de `cgroup.procs`, subcgroups incluidos |
| E4.7 | `almacenamiento()` | `du -sB1` de los directorios de la distribución y de containerd por nodo (si no existe, se registra «no existe»), `df` de `/`, número de imágenes (`ctr -n k8s.io images ls`) y bytes del almacén de contenido de containerd, tamaño de cada qcow2 y bytes escritos a disco por nodo en cada idle válida (`node_disk_written_bytes_total`) |
| E4.8 | `destruir()` | `despliegue.sh <dist> destruir <ciclo>` |

**Registro de despliegue de la campaña.** `despliegue.sh` escribe en `data/campana/despliegue_<dist>.jsonl` (`DESPLIEGUE_REGISTRO`), no en el registro versionado de la Etapa 3. El campo `ciclo` sigue siendo numérico: **100 + bloque** (el bloque 0 es el 100) y **200 + bloque** en el día de reserva. El diagnóstico usa 300 + ciclo.

**Tamaño de los qcow2.** El plan pide `qemu-img info`, campo `actual-size`. Se registra además `Allocation` de `virsh vol-info`, que no necesita leer la imagen. Los dos coincidieron en las 3 VMs (por ejemplo 2 824 691 712 bytes en `k3s-node2`).

**Plano de control** (bloque 1 del simulacro, nodo 1). K3s: `k3s.service` contiene `k3s-server`, `containerd` y 5 `containerd-shim`. MicroK8s: `kubelite` en su unidad, `k8s-dqlite` en la suya y `containerd` con 6 `containerd-shim` en `snap.microk8s.daemon-containerd`. Es decir, el cgroup de K3s incluye el runtime de contenedores y los shims, y el de `kubelite` no. Esto cierra la reserva del informe 3 sobre la comparabilidad de `--cgroup-cp`: comparar `k3s.service` con la suma de las tres unidades de MicroK8s, no con `kubelite` solo.

## 2. E5 · Ejecutor de campaña (`k6/medicion/campana.py`)

```
python3 -m k6.medicion.campana --plan data/campana/plan_campana_v1.json --jornada <n> --bloques <i>-<j> [--reanudar] [--simulacro]
python3 -m k6.medicion.campana --plan ... --jornada 0 --bloques 0 --tipo piloto     # bloque 0: orden del bloque 1, sesiones b00_<dist> en data/pilotos/
python3 -m k6.medicion.campana --plan ... --jornada 4 --bloques 3 --reserva         # día de reserva: sesiones b03r_<dist>
```

**Precondiciones de la jornada.** Modo medición activo, sin sesión gráfica, sin contenedores de incus, corriente alterna, plan con `estado: fijado` (solo en `--tipo definitiva`), `git status` limpio en `k6/`, `ansible/`, `k3sHA/` y `microk8sHA/`, al menos 20 GB libres y ninguna VM encendida. Si alguna falla, no arranca y lo anota en el diario con el commit vigente. En `--simulacro` solo informan, salvo las VMs encendidas.

**Tramo**, en el orden del plan: etiqueta (E1), memoria, referencia, construcción (con un reintento: destruir y construir de nuevo), verificación, RTT y plano de control, 6 corridas, repetición de las no válidas, almacenamiento, corrida con fallo (`--fallo --escenario media --tasa 450 --fallo-en 30 --fallo-retener 120`), destrucción y respaldo del JSON crudo de k6 con su SHA-256. Al final de cada bloque, instantánea de Prometheus empaquetada en `tar` con su SHA-256. Los respaldos van a `~/tesis_respaldo/`, fuera del repositorio. Las corridas usan `--tipo definitiva`, `--estabilizacion 120`, rampa 30 s, fase estable 180 s, descenso 30 s y `--sin-snapshot` (la instantánea es una por bloque, no una por corrida).

**Reglas de exclusión y repetición.**

| Situación | Qué hace |
|---|---|
| Falla del procedimiento: sin metadatos (precondición o reloj), lectura de RAPL fallida, fase estable incompleta o `valida_para_campana: false` | se repite una vez al final del tramo, antes de la corrida con fallo, con repetición 10 + la original (`r01` → `r11`); si vuelve a fallar, la celda queda con una corrida |
| Latencia, fallidas, descartadas, memoria bajo 1024 MB, código de salida de k6 | resultados; no se excluye ni se repite |
| Construcción fallida dos veces | se destruye, el tramo se aborta y el bloque completo queda para la reserva (`--reserva`, sesiones `bNNr_<dist>`); el resto de los tramos del bloque se omite |
| Código 86 del orquestador (memoria bajo 512 MB) | se termina el tramo (sin almacenamiento ni corrida con fallo), se destruye y se registra `abortado_memoria`; no se repite |

**Diario.** `data/campana/diario/jornada_<n>.jsonl` (una línea por paso, con hora, bloque, distribución, sesión, paso, resultado, duración y detalle), `jornada_<n>.log` legible y `estado_actual.json` (último paso, corrida en curso, término estimado y tramos de la jornada).

**Reanudación.** `--reanudar` lee todos los diarios. Un tramo está hecho si tiene `tramo_fin`. Retoma desde el inicio del tramo interrumpido: la carpeta de la sesión y la de k6 crudo se renombran a `<sesión>_interrumpido_<hora>` (no se borran). Si un bloque tiene un tramo terminado en otra jornada, se rehace completo. Un bloque enviado a la reserva no se vuelve a correr. Sin `--reanudar`, el ejecutor se niega a usar una sesión que ya existe.

**Señales.** `SIGINT` y `SIGTERM`: el ejecutor envía `SIGTERM` al orquestador, que termina k6, deja de esperar la inyección y restaura el fallo en su `finally`. Luego el ejecutor vuelve a restaurar en los 3 nodos (es idempotente) y registra `interrumpido`. No borra datos ni destruye el clúster. Una segunda señal durante la limpieza se ignora. Para `--reanudar`, el clúster que quedó arriba se destruye con:

```
DESPLIEGUE_REGISTRO=data/campana/despliegue_<dist>.jsonl k6/operacion/despliegue.sh <dist> destruir <100 + bloque>
```

**Ejecución desatendida.** `tmux` 3.4 está instalado (`/usr/bin/tmux`). Comandos en el README, sección «4. Campaña».

**Cambio en el orquestador.** Atrapa `SIGTERM` como `KeyboardInterrupt`, termina k6 y corta las esperas del hilo del fallo, de modo que la restauración del `finally` corre de inmediato. Antes, una interrupción dejaba el hilo esperando hasta `--fallo-retener` más 200 s.

## 3. Pruebas (16-nov, fuera del modo medición, `--simulacro`)

Ventanas del simulacro: rampa 15 s, fase estable 30 s, descenso 10 s, estabilización 10 s, referencia 3 + 10 s, fallo a los 5 s con 15 s de retención. Las potencias no significan nada (sesión gráfica abierta).

**Bloque 1 completo, sin intervención** (`--jornada 1 --bloques 1 --simulacro`, 15:33 a 16:19): 2 tramos completos, 12 corridas válidas, 2 corridas con fallo válidas, ningún reintento. El diario tiene 39 líneas, una por paso. Respaldo de k6 de 7 archivos por tramo; instantánea de Prometheus de 45,6 MB en 0,2 s.

| | K3s | MicroK8s |
|---|---|---|
| Etiqueta (escritura a `up` nuevo) | 17,1 s | 19,1 s |
| Memoria | 0,8 s | 0,3 s |
| Construcción | 290 s, 3 329 J; Ansible 253 s | 1 317 s, 10 033 J; Ansible 1 282 s |
| Bytes recibidos por la Wi-Fi en la construcción | 739 MB | 2 267 MB |
| Tramo completo (simulacro) | 14,3 min | 31,6 min |

**Interrupción y reanudación** (`--jornada 2 --bloques 2 --simulacro`): `SIGINT` al grupo de procesos, como Ctrl+C en `tmux`, 40 s después del almacenamiento de `b02_k3s`, con el fallo inyectado (`k3s-node1` con el drop-in y la unidad `failed`). El ejecutor terminó 10 s después. `k3s-node1` quedó `active` y sin drop-in, sin k6 en ejecución, y el diario registró `interrumpido` con la restauración de los 3 nodos. El clúster quedó arriba. Con las VMs encendidas, `--reanudar` se negó a partir y mostró el comando de destrucción. Tras destruir, `--reanudar` apartó `b02_k3s` como `b02_k3s_interrumpido_20261116T163540` y rehízo el bloque desde `b02_k3s`. Terminó sin intervención (16:35 a 17:25): los 2 tramos completos, 12 corridas válidas y 2 corridas con fallo válidas, e instantánea de Prometheus. Las mediciones de almacenamiento ya corregidas salieron completas: containerd de 822 MB en K3s y de 1 277 MB en MicroK8s, y qcow2 de 2,8 a 4,2 GB. La construcción de MicroK8s tomó 1 501 s esta vez.

**Correcciones durante la prueba.** El directorio de containerd de K3s salía «no existe» porque `/var/lib/rancher/k3s/agent` no es legible sin root (ahora `sudo ls -d`). El tamaño de los qcow2 salía vacío porque libvirt entrega el nombre del volumen, no su ruta (ahora `--pool default` y `vol-path`).

**Autotests.** `tramo` (ciclos, delta de red, escritura atómica) y `campana` (orden del plan, bloque 0 y reserva, reanudación en la misma jornada, en otra jornada y con un bloque en reserva, clasificación del código 86).

## 4. Desvío de la duración estimada

La construcción de MicroK8s tomó 1 317 y 1 501 s, frente a 758 s en la Etapa 3 (K3s: 290 a 312 s). La diferencia está en la instalación del snap (Ansible), con 2,27 GB descargados por la Wi-Fi. Si se repite en la campaña, el tramo MicroK8s pasa de 69 a ≈ 78–81 min (en el borde superior del rango del plan o algo por encima), y una jornada de 3 bloques a ≈ 7 h 10 min a 7 h 20 min. Lo verifica el bloque 0 con las fases completas.

## 5. Límites

- La prueba usó ventanas cortas; las fases completas y la memoria de MicroK8s en un tramo completo las verifica el bloque 0.
- Una interrupción durante `despliegue.sh` termina el `bash`, pero Terraform o Ansible pueden quedar a medias. Antes de `--reanudar` se destruye el clúster, y el ejecutor exige que no haya VMs.
- No probé una construcción fallida ni un aborto por memoria dentro del ejecutor; la lógica está en el autotest y el código 86 se probó en el orquestador (E3).
- `--reanudar` confía en el diario: si se borra o edita, no sabe qué tramos terminaron.
- El término estimado que imprime el ejecutor usa los tiempos típicos del plan (60 y 69 min), no los medidos.
