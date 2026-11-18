# Evidencia E9 (Etapa 4): complementarios

Estado al 18-nov-2026. Los scripts de E9.1 a E9.4 se escribieron antes de la campaña y se probaron con datos versionados de la Etapa 3. E9.1 y E9.4 se ejecutan sobre la campaña; E9.5 y E9.6 siguen pendientes.

## 1. E9.1 · Integridad de las corridas con fallo (T-25.3)

```
python3 -m analysis.campana.integridad_fallo --datos data/campana --salida analysis/salidas/<fecha>_campana
```

Entrega `integridad_fallo.csv`, con una fila por corrida con fallo, una columna por verificación (`ok`, `falla` o `no aplica`, con su detalle) y la columna `cumple`. Los umbrales son propios: un hueco máximo de 3 veces el período nominal y una cobertura de al menos 90 %.

**Continuidad, en la fase estable completa,** de estas fuentes:
- cada objetivo de Prometheus (`up`), con un período de 10 s;
- kube-state-metrics (`kube_node_status_condition`);
- el observador HTTP del host, cada 1 s;
- el estado vía `kubectl`, cada 2 s;
- los segundos de k6 con solicitudes;
- las lecturas de RAPL, que deben quedar a menos de 1 s de los bordes de la ventana.

**Secuencia de eventos:**

| Evento | Qué se verifica |
|---|---|
| Inyección | código 0, cota menor o igual a 2 s, y a ±2 s de lo programado |
| NotReady | ocurre entre 0 y la restauración |
| Migración de cada VIP | ocurre entre 0 y la restauración. Si el titular previo no era el nodo fallado, es «no aplica», y es «falla» si la VIP se movió igual. |
| API | caída y restablecimiento ordenados, antes de la restauración; «no aplica» si no cayó |
| Restauración | código 0 y a ±2 s de la retención |
| Ready | después de la restauración, dentro de la ventana, y nodo listo al final |
| Estrato de liderazgo | está determinado |

**Pruebas.**
- Autotest con huecos y cobertura conocidos. Además, una corrida sintética íntegra y otra con tres fallas inyectadas (código de inyección, VIP sin migrar y sin Ready): detecta exactamente esas tres.
- Las 10 corridas con fallo del 2-nov (`data/pilotos/2026-11-02_<dist>_fallo`) cumplen todas, con un hueco máximo de 4,8 s en el `kubectl` de K3s r01 y de 10 s en Prometheus.

## 2. E9.2 · Complejidad (`analysis/complejidad.py`)

Solo usa conteos reproducibles desde el repositorio.

| Métrica | K3s | MicroK8s |
|---|---|---|
| Tareas del rol del servidor (incluidos los handlers) | 14 | 28 |
| Tareas de Ansible en total | 60 | 79 |
| Líneas de IaC comunes | 667 | 667 |
| Líneas de IaC específicas | 114 | 227 |
| Tareas por nodo adicional | 2 | 7 |
| Órdenes (`command` o `shell`) por nodo adicional | 1 | 5 |
| Uniones secuenciales (`throttle: 1`, por Dqlite) | 0 | 1 |
| Retención de actualizaciones del snap | 0 | 1 |
| Tareas con reintentos | 0 | 4 |
| Esperas de disponibilidad de la API | 2 | 5 |
| Regeneración de certificados | 0 | 2 |
| Reinicios de la distribución | 0 | 3 |
| Servicio enmascarado (`apiserver-kicker`) | 0 | 1 |
| Token de unión por nodo (`add-node`) | 0 | 1 |

**Cómo se cuentan las líneas de IaC.** Se comparan los archivos de igual ruta en `k3sHA/` y `microk8sHA/`:
- sin comentarios ni líneas vacías;
- con el nombre de la distribución normalizado;
- con `difflib`, línea a línea.

Así, una línea que difiere solo en el nombre cuenta como común.

**Salidas:** `complejidad.csv`, `complejidad_roles.csv` y `complejidad_lineas.csv`, por archivo.

**Prueba:** el autotest normaliza y cuenta las tareas de un YAML conocido y corre sobre el repositorio.

## 3. E9.3 · Antes y después (`analysis/antes_despues.py`)

Entrega una tabla en formato largo (`antes_despues.csv`). Cada fila trae su fuente y su evidencia.

| Mejora | Antes | Después | Fuente |
|---|---|---|---|
| Boost de CPU (K3s, NGINX estático, `500m`) | activo: media a 1600 rps y alta a 2900 rps dan la misma potencia, 14,961 W (tope) | apagado: alta a 1600 rps da 7,764 W y la potencia crece con la carga | `data/exploratorio/2026-10-25_k3s_boost-activo`, `…/2026-10-26_k3s` |
| Boost de CPU, reposo del host sin VMs | 2,514 W (n = 9 ventanas) | 2,605 W (n = 9) | `data/reposo/` |
| Aplicación de referencia | estática con `500m` (900 y 1600 rps) | SHA-256 ×300 con `2000m` (450 y 900 rps). Los valores por distribución y escenario están en el CSV. | `data/pilotos/2026-10-27_<dist>`, `…/2026-10-28_<dist>` |
| kube-vip | original (K3s, 19-oct): VIP sin migrar en 0 de 1 corridas, API restablecida a los 93,7 s | contra el apiserver local: la VIP migró en 16 de 16 corridas (100 y 450 rps); mediana de la API de 18,4 a 21,7 s | `analysis/salidas/*recuperacion*/recuperacion.csv` |
| Diseño estadístico | muestras independientes | diferencias por bloque | sin datos versionados: simulación de `evidencia_T-21.md` 4.3 |
| Factor del diagnóstico | — | — | pendiente del 19-nov. El script lee `decision.json` si existe en `analysis/salidas/*diagnostico*/`. |

**Límites de la comparación.**
- Las condiciones de antes y después no tienen las mismas tasas. La tabla compara condiciones, no efectos aislados.
- En el boost apagado del 26-oct, media tiene una sd de 1,095 W por el salto de nivel documentado en `evidencia_T-20.md` 7.4.

**Prueba:** el autotest verifica el tope del boost activo frente al apagado, que la VIP original no migró y que la fila sin datos no lleva valor.

## 4. E9.4 · Capacidad máxima (`k6/calibracion/capacidad.py`, T-24.5)

Hace 3 pasadas de `k6.calibracion.calibrar` con `--tasas 800,…,1300` y `--seguir`, con los criterios de escalón sostenido de la Etapa 3, sobre el mismo clúster. Escribe `capacidad_<dist>_<ts>.json` en `data/calibracion/<sesión>/`, con lo siguiente:
- por pasada, el último escalón sostenido antes del primer fallo, el mayor escalón sostenido y los motivos de falla;
- la mediana y el rango de las 3 pasadas.

**Prueba.**
- Autotest: un fallo intermedio con un escalón sostenido después.
- `--resumir` sobre las calibraciones del 27-oct reproduce `ultima_tasa_sostenida`: 1100 rps en K3s y 1000 rps en MicroK8s.

**Procedimiento** (martes 24, o antes si hay tiempo). Lo ejecuta el usuario desde la consola de texto, en modo medición, con un clúster a la vez:

```
sudo /usr/local/sbin/tesis-modo-medicion entrar
DESPLIEGUE_REGISTRO=data/calibracion/despliegue_k3s.jsonl k6/operacion/despliegue.sh k3s construir 400
python3 -m k6.calibracion.capacidad --distribucion k3s
DESPLIEGUE_REGISTRO=data/calibracion/despliegue_k3s.jsonl k6/operacion/despliegue.sh k3s destruir 400
# lo mismo con microk8s
sudo /usr/local/sbin/tesis-modo-medicion salir
```

**Tiempo.** Cada pasada tiene 6 escalones de 60 s, con 20 s de pausa: unos 8 min. Las 3 pasadas toman unos 25 min por distribución, más la construcción y la destrucción.

**Qué devolver:** `data/calibracion/<fecha>_<dist>/` y la salida en pantalla.

## 5. Pendiente

- E9.5: reproducibilidad desde un clon limpio.
- E9.6: matriz de requisitos y evidencia, que necesita los resultados de la campaña para proponer el estado de cada requisito.
