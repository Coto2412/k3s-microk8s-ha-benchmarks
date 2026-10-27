import { sleep } from 'k6';
import { config } from './common.js';

const c = config('idle');
const total = c.rampa + c.estable + c.descenso;

export const options = {
  tags: { distribucion: c.distribucion, escenario: c.escenario, repeticion: c.repeticion },
  scenarios: { idle: { executor: 'constant-vus', vus: 1, duration: `${total}s` } },
};

export default function () {
  sleep(1);
}
