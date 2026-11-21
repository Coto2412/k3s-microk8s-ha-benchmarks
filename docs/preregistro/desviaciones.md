# Desviaciones respecto del pre-registro `plan-campana-v1`

Cada entrada registra un cambio o un incidente posterior a la etiqueta `plan-campana-v1`, con su efecto sobre el análisis.

## 1. Primer lanzamiento de la jornada 1, interrumpido (20-nov)

- **Hecho.** A las 12:10, primer lanzamiento de la jornada 1. En `b01_k3s`, la primera construcción falló porque `k3s-node3` no levantó `k3s.service` al unirse al clúster («Job for k3s.service failed»). El ejecutor destruyó el clúster y lanzó el reintento previsto. El operador lo interrumpió con Ctrl+C a las 12:24, porque no sabía que el reintento era el comportamiento esperado.
- **Acción.** Se destruyó el clúster del reintento y se movió todo lo generado (sesión `b01_k3s`, diario y registro de despliegue) a `data/campana_descartada/2026-11-20_intento1/`. La jornada 1 se relanzó de cero a las 12:31.
- **Efecto en el análisis.** Ninguno. El pipeline solo lee `data/campana/`. El intento apartado no cuenta para la regla de reintento de construcción ni entra en ninguna estadística. El fallo de unión de `k3s-node3` queda como observación cualitativa sobre la construcción de K3s.

## 2. Umbral de continuidad del observador en la integridad de los fallos (E9.1)

No es una desviación del pre-registro: la integridad de los fallos (`analysis/campana/integridad_fallo.py`) es complementaria y sus umbrales son propios, fijados antes de la campaña. Se anota porque en la jornada 1 hubo 3 de 6 corridas con fallo que no alcanzaron el umbral de continuidad del observador vía `kubectl`:
- hueco máximo de 6,6 y 6,2 s, con un umbral de 6 s;
- cobertura de 0,878, con un umbral de 0,9.

En las tres, la secuencia de eventos y las demás fuentes cumplen. Los umbrales no se cambian después de ver los datos: se informan tal como salen.
