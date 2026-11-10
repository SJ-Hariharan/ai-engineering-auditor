// GT:ts_cycle3|circular-dependency|CWE-NA|yes
import { q } from './q';
export const p = () => q();
