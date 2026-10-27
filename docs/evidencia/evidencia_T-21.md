# Evidencia T-21: mejoras del entorno experimental (HU-21)

Estado al 27-oct-2026. Separo lo medido, lo supuesto y lo que no verifiqué.

## 1. Alcance y estado

| Tarea | Estado | Qué hay |
|---|---|---|
| T-21.1 muestreo y recolección | Verificado, sin cambios (sección 2) | `analysis/muestreo_ventanas.py` |
| T-21.2 etiquetas, nombres y estructura | Reestructura hecha antes, dentro de T-20; auditoría hoy, sin cambios (sección 3) | `data/README.md` |
| T-21.3 repetir el piloto | Hecha: repetí los pilotos el 26 y el 27-oct. Resultado: precisión dentro de una sesión, no reproducible entre sesiones (hallazgo abierto de `evidencia_T-20.md`, 7.4 punto 6; lo resuelve T-24.4) | `evidencia_T-20.md` |
| T-21.4 tamaño muestral | Hecha: 8 bloques y 2 repeticiones por celda propuestos según la variabilidad observada en el piloto; potencia condicionada a σ_u (limitación declarada); la fijación definitiva se hace en el pre-registro (T-24.4) (sección 4) | `analysis/varianzas_piloto.py`, `analysis/potencia.py` |
| T-21.5 aislar CPU de QEMU y servicios | Estado verificado y alternativas documentadas; **no apliqué ningún cambio** (sección 5) | sin cambios de código |

## 2. T-21.1: frecuencia de muestreo y parámetros de recolección

**Configuración actual (leída del código):** `scrape_interval` de Prometheus 10 s (`ansible/group_vars/all.yml`); Node Exporter con 6 colectores (`cpu`, `meminfo`, `diskstats`, `filesystem`, `netdev`, `loadavg`).

**Medido** con `python3 analysis/muestreo_ventanas.py` sobre las 18 ventanas de los pilotos del 27-oct (fase estable de 180 s):

| Fuente | Muestras por serie en la ventana |
|---|---|
| Node Exporter del host (CPU 0) | 18 (mínimo 18, máximo 18) |
| Node Exporter de las VMs (3 series) | 18 en las 54 series-ventana |
| Scaphandre (`scaph_socket_power_microwatts`) | 18 en las 18 ventanas |
| kube-state-metrics (`kube_node_status_condition`) | 18 en las 18 ventanas |

Intervalo entre muestras consecutivas: mínimo 9,997 s, máximo 10,003 s, mediana 10,000 s (n = 1836); ninguno fuera de 10 ± 0,5 s.

**Decisión:** no cambio ningún parámetro. Los datos no muestran huecos ni irregularidad que lo justifiquen.

**Límites.** Con 10 s hay 18 muestras (17 intervalos) por ventana, y los extremos del scrape no coinciden con los de la ventana, así que las tasas calculadas con contadores de Prometheus cubren algo menos de 180 s; no cuantifiqué ese efecto. La potencia de la campaña no depende del scrape: el orquestador lee RAPL directamente al inicio y al fin de la fase estable. No probé intervalos distintos de 10 s, así que no afirmo que otro sea mejor o peor. Solo revisé los pilotos del 27-oct. Antes, en T-20.3, comprobé que los scrapes de Scaphandre distan 10,0 s como máximo.

## 3. T-21.2: etiquetas, nombres de archivos y estructura de datos

**Hecho antes.** Durante T-20 reorganicé `data/` por tipo y sesión (`calibracion/`, `pilotos/`, `verificacion/`, `exploratorio/`, `reposo/`, `despliegue/`, `humo/`, `prometheus-snapshots/`; el crudo de k6 fuera de git) y reescribí las rutas de 70 metadatos. Es el trabajo que describe esta tarea; el historial de git conserva las rutas anteriores y no escribí un mapa de equivalencias aparte.

**Auditoría de hoy (medida sobre los archivos versionados):**

| Grupo | Archivos | Resultado |
|---|---|---|
| `pilotos/` | 18 metadatos | esquema `2`, mismas claves en todos |
| `exploratorio/` | 27 metadatos | esquema `2`, mismas claves que `pilotos/` |
| `calibracion/` | 17 archivos | un único esquema; `nota` falta en 2 y `pod`/`limite_por_contenedor` en 1 (calibraciones más antiguas) |
| `reposo/` | 6 archivos | mismas claves en los 6 |
| `verificacion/` | 14 metadatos | formato anterior al orquestador actual (12 con esquema `1`, 2 sin esquema); 30 componentes ausentes (por segundo, resumen o ventana de Prometheus) en las sesiones del 18, 19 y 20-oct |

Identificación: todo archivo con metadatos sigue `[prefijo_]<distribución>_<escenario>_r<NN>`, salvo los 2 `piloto_T-17.4_*`, anteriores a la convención.

**Decisión:** no arreglo nada. Las inconsistencias están solo en `verificacion/`, que son las pruebas de T-17 a T-19 previas al esquema actual; no entran en el análisis de la campaña y no bloquean nada. Por eso no renombré archivos.

## 4. T-21.4: tamaño muestral con la varianza del piloto

### 4.1 Datos

`python3 analysis/varianzas_piloto.py` sobre los 36 metadatos de los pilotos con boost apagado del 26 y 27-oct: 12 celdas de día × distribución × escenario, con 3 repeticiones cada una. Son pilotos con la aplicación anterior (NGINX estático, `500m`, 900/1600 rps): sirven para estimar varianza, no son resultados.

| Celda (día, distribución, escenario) | Media (W) | sd de 3 repeticiones (W) |
|---|---|---|
| 26-oct K3s idle / media / alta | 5,781 / 5,873 / 7,764 | 0,037 / **1,095** / 0,011 |
| 26-oct MicroK8s idle / media / alta | 5,877 / 7,197 / 7,734 | 0,001 / 0,010 / 0,022 |
| 27-oct K3s idle / media / alta | 4,894 / 6,212 / 6,792 | 0,031 / 0,010 / 0,009 |
| 27-oct MicroK8s idle / media / alta | 5,867 / 7,206 / 7,775 | 0,007 / 0,006 / 0,017 |

La sd de 1,095 W es la celda de K3s `media` del 26-oct: r1 midió 7,137 W y r2 y r3 5,264 y 5,217 W, tras un `ansible-playbook` del host y un `salir`/`entrar` entre r1 y r2 (`evidencia_T-20.md`, 7.4 punto 6). Su media (5,873 W) mezcla dos niveles.

### 4.2 Varianza por nivel

**Medido**

- **Dentro de una serie (repeticiones de una celda):** sd agrupada 0,018 W sin la celda dividida (máximo 0,037 W); con ella, 0,317 W. Mediana de las 12 celdas: 0,011 W.
- **Entre días, misma distribución y escenario** (diferencia entre las medias de celda del 27 y del 26-oct): MicroK8s −0,010 / +0,008 / +0,041 W (idle, media, alta); K3s −0,887 / +0,339 / −0,972 W.
- **Entre distribuciones, misma sesión** (MicroK8s − K3s): 26-oct +0,096 / +1,325 / −0,030 W; 27-oct +0,974 / +0,994 / +0,983 W.

**Interpretación (mía, no demostrada).** La diferencia entre días de K3s (hasta ≈ 1 W) es de decenas de veces la sd dentro de una serie (0,018 W), así que las repeticiones de una misma sesión no son independientes: comparten el nivel de esa serie, y la varianza que importa para comparar distribuciones es la de entre series. La diferencia entre distribuciones cambia de signo y de tamaño según la sesión (de ≈ 0 a ≈ 1 W), de modo que con estos datos no se puede estimar un efecto de distribución.

**Supuesto, no medido:** no estimo la varianza entre series. Cada distribución tiene solo 2 días de datos (1 grado de libertad), y K3s alterna niveles dentro de un mismo clúster. Acoto su desviación entre 0,1 y 0,6 W como supuesto.

### 4.3 Función de potencia

`analysis/potencia.py` simula la comparación con este modelo (supuestos):

- `y = μ + δ·[MicroK8s] + u + e`, con `u ~ N(0, σ_u)` independiente por segmento y `e ~ N(0, σ_w)` por repetición.
- Un segmento es un bloque de repeticiones de una distribución. En el diseño de la Etapa 2, `b` bloques por distribución, cada uno con `r` repeticiones.
- `σ_w = 0,018 W` es el valor medido (4.2); `σ_u` y `δ` son supuestos.
- Dos análisis, ambos con t de Welch a α = 0,05: **ingenuo** (todas las repeticiones como independientes) y **por segmento** (la media de cada segmento).
- Verificación de la función: la p de la t de Welch usa la beta incompleta. La contrasté con `scipy.stats.ttest_ind(equal_var=False)` (scipy 1.11.4) en 501 casos, uno fijo y 500 aleatorios de 2 a 10 observaciones por grupo: la diferencia absoluta máxima de p fue 8,1·10⁻¹⁴. El propio script conserva además una comprobación con formas cerradas (df = 1 y df = 2) que no depende de scipy.

Fracción de rechazos en 2000 simulaciones por celda (extracto; la tabla completa se obtiene ejecutando el script):

| `b` × `r` | `σ_u` (W) | δ = 0 (falso positivo): ingenuo / por segmento | δ = 0,25 W: ingenuo / por segmento | δ = 0,5 W: ingenuo / por segmento |
|---|---|---|---|---|
| 2 × 5 | 0 | 0,052 / 0,021 | 1,000 / 1,000 | 1,000 / 1,000 |
| 2 × 5 | 0,3 | 0,540 / 0,025 | 0,673 / 0,037 | 0,843 / 0,089 |
| 6 × 2 | 0,1 | 0,187 / 0,046 | 0,999 / 0,969 | – |
| 6 × 2 | 0,3 | 0,207 / 0,049 | 0,533 / 0,240 | 0,910 / 0,722 |
| 6 × 2 | 0,6 | 0,189 / 0,051 | 0,277 / 0,093 | 0,532 / 0,247 |
| 10 × 1 | 0,3 | 0,056 / 0,056 | 0,413 / 0,413 | 0,935 / 0,935 |
| 10 × 1 | 0,6 | 0,046 / 0,046 | 0,136 / 0,136 | 0,416 / 0,416 |

Con δ = 0,1 W, `σ_u` = 0,1 W: por segmento, 0,039 (2 × 5), 0,336 (6 × 2) y 0,543 (10 × 1).

### 4.4 Lectura y límites

- Si el nivel de cada segmento varía (σ_u > 0), con 2 o más repeticiones por segmento el análisis ingenuo da falsos positivos de 19 % a 57 % con δ = 0, y el análisis por segmento mantiene ≈ 5 % (con 1 repetición por segmento los dos análisis coinciden). Tratar las repeticiones como independientes no es válido en ese caso.
- Lo que aporta potencia es el número de segmentos `b`, no las repeticiones `r` dentro de cada uno: con `σ_u` = 0,3 W y δ = 0,25 W la potencia por segmento sube de 0,04 (b = 2) a 0,24 (b = 6) y 0,41 (b = 10).
- Con σ_u de 0,3 W o más y diferencias de 0,25 W o menos, ni 10 segmentos por distribución alcanzan 0,8 de potencia. Con σ_u = 0 el problema desaparece, pero no sé si la causa del desfase se puede eliminar (T-24.4).
- El modelo supone un nivel independiente por segmento, porque MicroK8s repitió niveles entre sesiones y K3s alternó dentro de un clúster. No simulé un nivel compartido por bloque entre ambas distribuciones, donde una prueba pareada lo cancelaría.
- Esta simulación usa t de Welch sobre las medias de cada segmento. No simulé la potencia de la prueba de Wilcoxon de 4.5; para esa prueba solo calculé la combinatoria exacta.

### 4.5 Diseño y análisis propuestos para la campaña (a fijar en el pre-registro)

**Diseño propuesto:** 8 bloques. Cada bloque contiene las dos distribuciones en orden alternado: 4 bloques empiezan por K3s y 4 por MicroK8s, con la asignación sorteada con una semilla registrada y la restricción 4/4. Dentro de cada tramo se corre `idle`, `media` y `alta` por repetición, como en la Etapa 2. Repeticiones por celda (bloque × distribución × escenario): 2, o 1 si el tiempo aprieta. Un solo `entrar` por jornada, sin reiniciar el equipo entre bloques de la misma jornada. Con 2 repeticiones son 96 corridas; a ≈ 6 min por corrida (medido en los pilotos) son ≈ 9,6 h de medición, sin contar construcciones ni los pasos del host. El borrador del plan y la semilla están en `evidencia_T-24.4.md`.

**Por qué 8 bloques.** Con una prueba de Wilcoxon de rangos con signo exacta y bilateral sobre las diferencias por bloque, el menor p posible es 2/2ⁿ (calculado con `scipy.stats.wilcoxon(method="exact")`):

| Bloques `n` | p mínimo | p mínimo si el rango más bajo cambia de signo |
|---|---|---|
| 5 | 0,0625 | 0,125 |
| 6 | 0,03125 | 0,0625 |
| 7 | 0,0156 | 0,03125 |
| 8 | 0,0078 | 0,0156 |
| 10 | 0,00195 | 0,0039 |

Con Holm sobre los 3 escenarios, el primer umbral es 0,05/3 ≈ 0,0167. Con 6 bloques el mínimo (0,031) no puede pasarlo. Con 7 pasa solo si las 7 diferencias tienen el mismo signo, y con un signo opuesto en el rango más bajo ya no. Con 8 pasa incluso si el rango más bajo cambia de signo (0,0156). Es combinatoria y no depende de σ_u. Que 8 sea par permite además el reparto 4/4 del orden.

**Análisis propuesto** (a fijar en el pre-registro antes de la campaña y no ajustar después de ver datos):
- Unidad: el promedio de cada celda (bloque × distribución × escenario).
- Prueba principal: Wilcoxon exacto sobre las diferencias por bloque; t pareada como complemento.
- Tamaño del efecto: Hodges-Lehmann y diferencia media con IC 95 %.
- Corrección: Holm dentro de familias. Primaria: energía × 3 escenarios. Secundarias: CPU, RAM, latencia y tasa de error.
- Modelo mixto, solo como análisis de sensibilidad.
- Desviación a declarar en el informe: la Etapa 2 organizó las repeticiones en bloques contrabalanceados (principio del NIST) pero propuso pruebas de muestras independientes. Pasar a diferencias por bloque corrige esa inconsistencia, y la simulación de 4.3 la respalda: 19 % a 57 % de falsos positivos con δ = 0 si las repeticiones se tratan como independientes.

**Límites que declaro:**
- **Potencia.** Con σ_u ≥ 0,3 W y diferencias ≤ 0,25 W no se alcanza potencia 0,8 ni con 10 bloques (4.3: 0,41 con σ_u = 0,3 W y 0,14 con σ_u = 0,6 W, a δ = 0,25 W). Es una limitación declarada del diseño con este nivel de variación, no un fallo del cálculo. Por eso el número queda como propuesta con potencia condicionada a σ_u.
- **Pareo.** Emparejar por bloque solo cancela algo si el nivel de potencia es compartido dentro de un bloque. No lo simulé y los pilotos no lo demuestran: MicroK8s repitió niveles entre sesiones y K3s los alternó. El diagnóstico del desfase (T-24.4) debe probarlo explícitamente: si el nivel cambia por sesión del host, por distribución o por arranque de las VMs. Si no hay nivel compartido, el análisis por bloque sigue siendo válido pero sin esa ganancia, y no la prometo.
- **Medida de energía.** No hay medidor externo, así que no existe una referencia de potencia independiente de RAPL. Un estudio sobre servidores EPYC 7502 (Zen 2) que comparó RAPL con una medición externa de corriente alterna (arXiv:2108.00808, «Energy Efficiency Aspects of the AMD Zen 2 Architecture») reporta que el dominio de paquete informa una potencia significativamente menor y que no hay dominio de memoria; lo leí en el resumen de una búsqueda, no leí el artículo. Mi CPU es un Ryzen 7 PRO 5850U (familia 25 en `/proc/cpuinfo`, que corresponde a Zen 3 según mi conocimiento, sin verificar en documentación del fabricante) y ese estudio no midió mi equipo. Que el RAPL de AMD sea un modelo y no una medición no lo verifiqué con una fuente directa. Por eso no puedo descartar que el salto de ≈ 1 W sea un artefacto del contador y no un cambio real de consumo; no cambio nada por esto.
- **Se fija en el pre-registro (T-24.4):** 8 bloques × 2 repeticiones × 2 distribuciones × 3 escenarios = 96 corridas es una propuesta. Los bloques, las repeticiones, la secuencia con semilla, las reglas de exclusión y el plan de análisis se fijan antes del primer bloque (etiqueta `plan-campana-v1`, que aún no existe) y no se ajustan después de ver datos. La limitación de σ_u queda declarada, no resuelta.

## 5. T-21.5: aislar CPU de servicios del host y de los hilos de QEMU

### 5.1 Estado verificado

Medido el 27-oct levantando solo las 3 VMs de K3s con Terraform (sin Ansible) y destruyéndolas después.

- **Topología:** 1 socket, 8 núcleos físicos con 2 hilos. `thread_siblings_list`: CPU 0-1, 2-3, 4-5, 6-7, 8-9, 10-11, 12-13 y 14-15 son pares de hilos del mismo núcleo.
- **`vcpupin`** (`virsh vcpupin`): `k3s-node1` en 2 y 3, `k3s-node2` en 4 y 5, `k3s-node3` en 6 y 7. Cada VM ocupa los dos hilos de un mismo núcleo físico, que no comparte con otra VM. k6 usa los hilos 0 y 1.
- **Hilos de QEMU:** `emulatorpin` vacío y sin IOThreads. El hilo principal, `worker`, `IO mon_iothread` y `SPICE Worker` tienen afinidad `0-15`. El hilo `vhost-<pid>` de cada VM también tiene `0-15`. Solo los hilos de las vCPU y `kvm-nx-lpage-re` están fijados.
- **Dónde corrían** (60 muestras en 15 s, VMs sin clúster ni carga): los hilos de emulador aparecieron en 13 de las 16 CPU, incluidas las 2 a 7 de las vCPU y la 0 de k6; los de `vhost` en las 4, 6, 8, 10, 12 y 14, y las 4 y 6 pertenecen a vCPU.
- **Cuánto trabajan en reposo:** los hilos de emulador y otros consumieron 0,17 s de CPU en 15 s por VM (≈ 1 %); `vhost`, 0,00 s.

No medí: el comportamiento bajo carga de k6 y con el clúster arriba (`vhost-net` procesa la red de cada VM), ni si esta ubicación afecta la potencia o el desfase de ≈ 1 W.

### 5.2 Alternativas

| Alternativa | Ventajas | Desventajas |
|---|---|---|
| **A. No aislar** (estado actual) | Mantiene la configuración de los pilotos y de la Etapa 2; sin riesgo | Hilos de emulador y `vhost` pueden correr sobre las CPU de las vCPU y de k6 |
| **B. `emulatorpin` (y `iothreadpin`) en el XSLT de Terraform**, hacia las CPU 8 a 15 | Reproducible, un cambio en `vcpupin.xsl.tftpl` de ambas distribuciones | Exige recrear las VMs; no verifiqué que `vhost` herede la afinidad |
| **C. Aislar con cgroups o systemd** (`AllowedCPUs` para los servicios del host y para el cgroup de QEMU) | Cubre servicios del host y, posiblemente, `vhost`; sin tocar el XML de las VMs | Cambia el estado del host; no verifiqué cómo reparte los hilos `vhost`; más complejo de revertir |

### 5.3 Decisión

No apliqué nada, y no recomiendo aplicarlo antes de la campaña. Cualquier cambio altera la configuración respecto de los pilotos y de la Etapa 2 (sería una desviación) y se mezclaría con el hallazgo abierto del desfase de ≈ 1 W.

**Hipótesis, sin probar:** hilos sin fijar que se despiertan en distintos núcleos podrían reducir la residencia de estados C profundos en los núcleos ociosos. La ubicación de los hilos de QEMU entra como un factor más del diagnóstico de T-24.4 (cambiar la alternativa B y medir en un diseño ABAB), no como un cambio previo.
