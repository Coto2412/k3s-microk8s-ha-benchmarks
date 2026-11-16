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
