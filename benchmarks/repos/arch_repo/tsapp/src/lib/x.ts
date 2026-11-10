// GT:ts_cycle2|circular-dependency|CWE-NA|yes
import { y } from './y';
export const x = () => y();
