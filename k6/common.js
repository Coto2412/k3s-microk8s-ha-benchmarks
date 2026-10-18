import http from 'k6/http';
import { check } from 'k6';

// Parámetros comunes de los escenarios. Las tasas no tienen valor por defecto: se calibran en T-20.5.
function num(nombre, defecto) {
  const bruto = __ENV[nombre];
  if (bruto === undefined || bruto === '') {
    if (defecto === undefined) throw new Error(`Falta la variable de entorno ${nombre}`);
    return defecto;
  }
  const v = Number(bruto);
  if (!Number.isFinite(v) || v < 0) throw new Error(`${nombre} inválida: ${bruto}`);
  return v;
}

export function config(nombre) {
  return {
    objetivo: __ENV.OBJETIVO || 'http://192.168.100.150:80/',
    rampa: num('RAMPA_S', 30),
    estable: num('ESTABLE_S', 180),
    descenso: num('DESCENSO_S', 30),
    preVUs: num('PRE_VUS', 50),
    maxVUs: num('MAX_VUS', 200),
    distribucion: __ENV.DISTRIBUCION || 'sin-definir',
    escenario: __ENV.ESCENARIO || nombre,
    repeticion: __ENV.REPETICION || '0',
  };
}

export function opcionesAbiertas(c, tasa) {
  return {
    discardResponseBodies: true,
    tags: { distribucion: c.distribucion, escenario: c.escenario, repeticion: c.repeticion },
    scenarios: {
      carga: {
        executor: 'ramping-arrival-rate',
        startRate: 0,
        timeUnit: '1s',
        preAllocatedVUs: c.preVUs,
        maxVUs: c.maxVUs,
        stages: [
          { target: tasa, duration: `${c.rampa}s` },
          { target: tasa, duration: `${c.estable}s` },
          { target: 0, duration: `${c.descenso}s` },
        ],
      },
    },
  };
}

export function carga(nombre) {
  const c = config(nombre);
  return {
    options: opcionesAbiertas(c, num('TASA')),
    ejecutar: () => {
      const r = http.get(c.objetivo);
      check(r, { 'status 200': (x) => x.status === 200 });
    },
  };
}

export { num };
