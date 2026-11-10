// GT:ts_broken_alias|unresolved-import|CWE-NA|yes
import { nope } from '@lib/nonexistent';
import { util } from '@lib/util';
// GT:ts_broken_relative|unresolved-import|CWE-NA|yes
import { gone } from './missing/module';
export const main = () => util() + nope + gone;
