# Evidencia E7 y E8 (Etapa 4): pipeline de análisis pre-registrado y pre-registro

Estado al 18-nov-2026. E7 prepara T-24.3, T-26.1 a T-26.5. E8 deja el borrador del pre-registro, que se fija el viernes 20 con la etiqueta `plan-campana-v1`.

## 1. E7 · Pipeline (`analysis/campana/`)

```
python3 -m analysis.campana.todo --datos data/campana --salida analysis/salidas/<fecha>_campana [--rotulo "…"]
python3 -m analysis.campana.todo --autotest
```

| Módulo | Qué hace |
|---|---|
| `consolidar.py` | Sesiones `bNN_<dist>`. Una `bNNr_<dist>` del día de reserva reemplaza al bloque NN completo; las `*_interrumpido_*` se ignoran. Arma una fila por corrida (reutiliza `analysis.recursos_latencia.leer_corrida`: CPU, RAM, RSS de QEMU, latencia de la fase estable desde el crudo de k6) con los campos del esquema 3 (estado, memoria del muestreador, swap, temperatura, frecuencia), la energía, los J por solicitud completada, Scaphandre con corrección del desbordamiento y los tiempos de recuperación (`fallo.tiempos`). Arma también una fila por tramo (desde `tramo.json`) y una por celda (promedio de las corridas incluidas), y las anomalías, con la regla que las detectó. |
| `pruebas.py` | Wilcoxon exacto bilateral (distribución exacta de T+ para n sin empates; con ceros o empates, aproximación normal declarada), t pareada, Hodges–Lehmann con intervalo exacto y nivel alcanzado, Holm, TOST pareado sobre ln(P_MicroK8s / P_K3s) con ±ln(1,05) e intervalo al 90 %, robustez con Hodges–Lehmann al nivel más cercano al 90 %, y veredicto por escenario. |
| `todo.py` | Punto de entrada: consolidación, familia principal, siete familias secundarias, sensibilidad (modelo mixto con `statsmodels` y sobrecosto en reposo), exploratorios rotulados (niveles idle por tramo con la regla de `desfase_retro.niveles`, Spearman con covariables, NotReady por estrato) y figuras. |
| `analysis/figuras.py` | Figura nueva `fig_bloques` (potencia de cada celda por bloque, con una línea entre las dos distribuciones del bloque). El pipeline reutiliza `fig_espectro` y `fig_recuperacion`. |

**Correspondencia con el pre-registro.** Las familias y sus métricas son las de la sección 5 de `docs/preregistro/plan-campana-v1.md`; cada una tiene su propio Holm.

**Salidas** (25 archivos):
- tablas: `corridas`, `tramos`, `celdas` y `anomalias`;
- familia principal: `principal.csv` y `principal.json` (con el TOST y el veredicto);
- familias secundarias: `secundaria_<familia>.csv`;
- sensibilidad: `sensibilidad.json`;
- exploratorios: `exploratorio_*.csv`;
- resumen: `resumen.txt`;
- figuras: `figura_potencia_bloques.pdf`, `figura_espectro_latencia.pdf` y `figura_recuperacion.pdf`;
- caché: `cache_latencia.json`. Con ella, una segunda pasada no vuelve a leer los JSON crudos de k6.

Las tablas van en CSV, listas para LaTeX. Las figuras se limitan a lo extenso: series por bloque, distribución de latencia y línea de tiempo de recuperación.

**Dependencias.** Fijadas en `analysis/requirements.txt` con las versiones instaladas: numpy 1.26.4, scipy 1.11.4, pandas 2.1.4, statsmodels 0.14.1 y matplotlib 3.6.3. La versión de matplotlib estaba mal fijada (3.11.2, que no es la instalada) desde la Etapa 3; se corrigió.

## 2. Pruebas del pipeline

**Datos sintéticos con efecto conocido** (`--autotest`):
- 8 bloques con ruido de bloque (σ = 0,5 W) y +0,20 W en MicroK8s. Hodges–Lehmann recupera 0,20 W ± 0,03 con el valor dentro de su intervalo; Wilcoxon da p = 2/256 y es significativo después de Holm; el veredicto es «diferencia detectada» en los tres escenarios.
- Con efecto nulo y una dispersión de 0,5 %, el TOST concluye equivalencia. Con +20 % no la concluye, y la razón estimada es 1,20.
- Holm ajusta el p menor por m y respeta la monotonía.
- Las sesiones de reserva reemplazan al bloque y las interrumpidas se ignoran.
- La celda promedia solo las corridas incluidas.
- Las 6 figuras del módulo se generan.

**Punta a punta con las jornadas 3 y 4 como dos bloques ficticios.** Bloque 1: `2026-10-28_<dist>`. Bloque 2: `2026-11-02_<dist>` más `_fallo`. Se usó `--incluir-no-validas`, porque son pilotos. Resultado: 46 corridas (10 con fallo), 12 celdas, 12 anomalías (fallidas o descartadas en la fase estable), las 7 familias secundarias, el modelo mixto ajustado y las 3 figuras. Tardó 4 min la primera vez (lectura de los crudos de k6) y 3 s con la caché. **Estas salidas no se interpretan.** Con 2 bloques, el nivel de Hodges–Lehmann alcanzado es 50 % y el p mínimo de Wilcoxon es 0,5.

**Con el simulacro de E5** (`data/campana_simulacro/campana`, 2 bloques y 2 jornadas; no versionado y borrado después de esta prueba): corre completo, incluidos `tramo.json` (referencia, sobrecosto en reposo, construcción, almacenamiento) y el modelo mixto con la jornada fija.

## 3. E8 · Pre-registro (borrador)

- `docs/preregistro/plan-campana-v1.md`, con los 11 puntos de la sección 6 del plan. Pendientes marcados: factor del diagnóstico, commit y fecha de fijación.
- `k6/medicion/plan_campana.py`:
  - Agrega al plan la ventana de referencia, la construcción por tramo, la corrida con fallo, las jornadas y las reglas de exclusión.
  - Marca `repeticiones_por_celda_provisional: false`.
  - Con `--fijar --commit <sha>` escribe `estado: fijado` y el bloque `fijacion` (fecha, commit, etiqueta, pre-registro).
  - Antes de escribir, comprueba que la semilla y los bloques (orden y corridas) sean idénticos a los del archivo existente. Si no, se detiene.
- `data/campana/plan_campana_v1.json`: regenerado como borrador. La semilla y el orden coinciden con el borrador anterior (`b1:k3 b2:k3 b3:mi b4:mi b5:k3 b6:k3 b7:mi b8:mi`, 96 corridas). El ejecutor solo acepta `--tipo definitiva` con `estado: fijado`.

**Fijación (viernes 20, después de revisar el pre-registro y decidir el factor):**

```
git add -A && git commit -m "…"                       # código, pipeline y pre-registro
python3 -m k6.medicion.plan_campana --fijar --commit $(git rev-parse HEAD)
# completar en el pre-registro el commit, la fecha y el factor
git add data/campana/plan_campana_v1.json docs/preregistro/plan-campana-v1.md && git commit -m "docs: pre-registro plan-campana-v1 fijado"
git tag plan-campana-v1
```

## 4. Límites

- Las pruebas pareadas exigen bloques con las dos distribuciones. Un bloque con una distribución abortada por memoria queda fuera de esa comparación y figura en `anomalias.csv`.
- Si en algún bloque hay más de una corrida con fallo por distribución, la familia de recuperación usa su promedio. En la campaña hay una por tramo.
- Las figuras no se revisaron con datos de 8 bloques; las revisaré con el bloque 0 y con la campaña.
- El modelo mixto usa las corridas, no las celdas, y declara qué especificación convergió.
