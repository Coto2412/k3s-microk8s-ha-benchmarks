# Pre-registro de la campaña definitiva (`plan-campana-v1`)

**Estado: BORRADOR.** Se revisa antes de crear la etiqueta `plan-campana-v1`. Después de la etiqueta, este documento no se modifica: cualquier cambio posterior se registra como desviación en `docs/preregistro/desviaciones.md`.

- **Plan de ejecución:** `data/campana/plan_campana_v1.json`, generado por `k6/medicion/plan_campana.py`.
- **Ejecutor:** `k6/medicion/campana.py`.
- **Pipeline de análisis:** `python3 -m analysis.campana.todo --datos data/campana --salida analysis/salidas/<fecha>_campana`.

## 1. Pregunta y variable principal

¿Difiere la potencia de K3s y de MicroK8s en un clúster HA de 3 nodos con la misma carga?

- **Variable principal:** potencia media del paquete según RAPL (`package-0`) en la fase estable de 180 s, por escenario.
- **Cómo se nombra:** siempre «potencia media del paquete según RAPL», nunca «consumo del equipo». RAPL no mide la placa, la memoria (o no completa), el disco ni la pantalla.

## 2. Diseño

| Elemento | Valor |
|---|---|
| Bloques | 8. Cada bloque tiene 2 tramos, uno por distribución, en el orden sorteado con la semilla **20261028**. K3s va primero en los bloques 1, 2, 5 y 6; MicroK8s, en los bloques 3, 4, 7 y 8. **No se vuelve a sortear.** |
| Corridas por tramo | idle, media, alta, idle, media y alta (2 repeticiones por celda) y, al final, una corrida con fallo. 96 corridas normales y 16 con fallo. |
| Unidad de análisis | promedio de la celda (bloque × distribución × escenario) |
| Escenarios | idle, sin tráfico; media, 450 rps; alta, 900 rps. Carga abierta de k6 (`ramping-arrival-rate`) desde el host, con k6 fijado en los CPU 0 y 1. |
| Fases | estabilización 120 s, rampa 30 s, fase estable 180 s (la única ventana de medición), descenso 30 s |
| Construcción | el clúster se construye desde cero en cada tramo (16 construcciones) y se destruye al final. El registro de despliegue usa ciclo = 100 + bloque. |
| Ventana de referencia | al inicio de cada tramo, antes de construir, sin VMs ni k6: 120 s de espera y 180 s de medición |
| Corrida con fallo | al final de cada tramo, antes de destruir: media a 450 rps, fallo a los 30 s de la fase estable y 120 s de retención, con el protocolo vigente (`k6/lib/fallo.py`) |
| Energía del despliegue | RAPL al inicio y al término de cada construcción, en J, con corrección del desbordamiento |
| Jornadas | jornada 1: bloques 1 a 3; jornada 2: bloques 4 a 6; jornada 3: bloques 7 y 8; un día de reserva. Una sola activación del modo medición por jornada, sin reiniciar el equipo ni cambiar la red dentro de una jornada. Un bloque nunca se divide entre jornadas. |
| Red | solo la red virtual (NAT de libvirt). El RTT se mide una vez por tramo, fuera de las ventanas. |
| Medidor externo | no hay. RAPL es la única fuente de energía; Scaphandre sirve de contraste. |

## 3. Familia principal

Potencia en idle, media y alta: 3 pruebas.

- **Prueba:** Wilcoxon de rangos con signo, exacto y bilateral, sobre las 8 diferencias por bloque (MicroK8s − K3s, promedio de celda), con α = 0,05 y corrección de Holm entre los tres escenarios.
- **Complementos:** t pareada, y Hodges–Lehmann con intervalo exacto. Se declara el nivel de confianza alcanzado, que con n = 8 es discreto: 94,53 % es el más cercano al 95 %.
- **Potencia del diseño:** con 8 bloques, el p exacto mínimo es 2/256 = 0,0078, por debajo del primer umbral de Holm (0,0167). Una diferencia del mismo signo en los 8 bloques es detectable.

## 4. Equivalencia

- **Prueba:** TOST pareado sobre ln(P_MicroK8s / P_K3s) por bloque, con margen de ±ln(1,05), es decir ±5 %, e intervalo al 90 %.
- **Margen:** propio. Está muy por encima de la repetibilidad dentro de una sesión (cerca de 0,5 %) y por debajo de los desfases entre sesiones (cerca de 20 %).
- **Robustez:** intervalo de Hodges–Lehmann sobre el mismo logaritmo, al nivel exacto más cercano al 90 % (89,06 % con n = 8).
- **Resultado por escenario:**
  - «diferencia detectada»: Wilcoxon significativo después de Holm. Si además el TOST concluye equivalencia, se informa como «diferencia detectada, dentro del margen de equivalencia».
  - «equivalencia demostrada»: sin diferencia y con el intervalo al 90 % dentro de ±5 %.
  - «inconcluso»: ninguno de los dos.

## 5. Familias secundarias

Cada familia aplica las mismas pruebas pareadas (Wilcoxon exacto, t pareada, Hodges–Lehmann), con su propio Holm entre sus pruebas.

| # | Familia | Pruebas |
|---|---|---|
| 1 | Energía por solicitud | J por solicitud completada en la fase estable, en media y alta (2) |
| 2 | CPU | CPU media de las VMs y CPU del host (Node Exporter), en los 3 escenarios (6) |
| 3 | Memoria | MemAvailable mínimo del host en la fase estable, RSS total de QEMU y páginas de swap movidas, en los 3 escenarios (9) |
| 4 | Latencia | p50, p95 y p99 de la fase estable, en media y alta (6). Siempre se reportan con las iteraciones descartadas por k6. |
| 5 | Despliegue | tiempo y energía de construcción, por tramo (2) |
| 6 | Recuperación | migración de la VIP del plano de control, migración de la VIP del servicio, restablecimiento de la API y Ready tras la restauración, en la corrida con fallo de cada tramo (4, n = 8 pares). NotReady es solo descriptivo, por estrato de liderazgo del `kube-controller-manager`. |
| 7 | Almacenamiento | directorios de la distribución y de containerd por nodo, `df` usado, qcow2 total, contenido de las imágenes y bytes escritos a disco en las idle (6) |

## 6. Sensibilidad

- **Modelo mixto:** potencia ~ distribución × escenario, con efecto aleatorio de bloque, sobre las corridas incluidas. La jornada entra como efecto fijo; si el modelo no converge, como componente de varianza aleatorio. El pipeline declara cuál de los dos se usó.
- **Sobrecosto en reposo:** idle del tramo menos su ventana de referencia, en lugar de idle, con las mismas pruebas pareadas.

## 7. Exclusión y repetición

- **Falla del procedimiento.** Una corrida es no válida solo por esto: precondición no cumplida, lectura de RAPL fallida, aborto por reloj, fase estable incompleta o `valida_para_campana: false`. Se repite **una vez** al final de su tramo, antes de la corrida con fallo (repetición 10 + la original). Si sigue no válida, la celda queda con una sola corrida.
- **Resultados que no excluyen ni se repiten:** la latencia, las solicitudes fallidas, las iteraciones descartadas y MemAvailable bajo 1024 MB.
- **Construcción fallida:** se reintenta una vez (destruir y construir). Si vuelve a fallar, el tramo se aborta y **el bloque completo** pasa al día de reserva, con el mismo orden y el sufijo `r` (`b03r_k3s`). La sesión de reserva reemplaza al bloque completo en el análisis.
- **MemAvailable bajo 512 MB:** el orquestador aborta la corrida (código 86), se termina el tramo, se destruye el clúster y se registra como resultado de la distribución. No se repite.
- **Swap:** es una covariable, no un criterio de exclusión.
- **Anomalías:** todas quedan en `anomalias.csv` con la regla que las detectó. Ninguna excluye por sí misma, salvo las de procedimiento anteriores.

## 8. Memoria

- Cada nodo tiene 4096 MB y 2 vCPU, sin cambios durante la campaña.
- Antes de cada tramo, en ambas distribuciones, se libera el swap y se vacía la caché de páginas (`tesis-preparar-memoria`).

## 9. Estado del host

Es el del Cuadro 17 del informe 3, verificado por el orquestador en cada corrida (`estado_host`, política en `/etc/tesis/medicion.json`):
- consola de texto, sin sesión gráfica;
- `tesis-modo-medicion` activo: solo las unidades permitidas y **sin contenedores de incus** (`entrar` los detiene);
- perfil `balanced` y CPU boost apagado;
- corriente alterna conectada;
- relojes sincronizados (host < 100 ms, VMs < 5 ms).

Además, el factor fijado por el diagnóstico del 19-nov, si lo hay: **[pendiente de la decisión del viernes 20]**.

Versiones fijas:

| Componente | Versión |
|---|---|
| K3s | `v1.36.3+k3s1` |
| MicroK8s | canal `1.36/stable` |
| Aplicación | NGINX con SHA-256 ×300 por solicitud (njs), límite de CPU `2000m`, solicitud `500m`, 1 réplica |

## 10. Exploratorio declarado

Todo lo que sigue va rotulado como exploratorio: desfase con las covariables de la instrumentación y de la ventana de referencia, agrupamiento de los niveles idle de los 16 tramos (por construcción), NotReady por estrato, y cualquier comparación no listada en las secciones 3 a 6.

## 11. Fijación

- **Commit del código de medición y del pipeline:** **[se completa al fijar]**
- **Fecha:** **[se completa al fijar]**
- **Comando de fijación:** `python3 -m k6.medicion.plan_campana --fijar --commit <sha>`. Verifica que la semilla y el orden sean los del borrador y escribe `estado: fijado` en el plan.
- **Etiqueta:** `plan-campana-v1`, sobre el commit que contiene este documento y el plan fijado. La crea el usuario.
- **Pruebas del pipeline antes de fijar:** `python3 -m analysis.campana.todo --autotest`, que usa datos sintéticos con efecto conocido. Además, una prueba de punta a punta con las jornadas 3 y 4 como dos bloques ficticios, cuyas salidas no se interpretan (`docs/evidencia/evidencia_E7-E8.md`).
