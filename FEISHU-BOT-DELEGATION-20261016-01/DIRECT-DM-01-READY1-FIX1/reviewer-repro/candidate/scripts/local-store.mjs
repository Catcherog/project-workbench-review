// REVIEWER FIXTURE ONLY. Not the product host/store and not installation code.
import {writeFileSync} from 'node:fs';
export function durableWrite(file,body){writeFileSync(file,body,{mode:0o600});}
