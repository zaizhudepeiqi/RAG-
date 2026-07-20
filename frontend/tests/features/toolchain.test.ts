import { createRequire } from 'node:module';
import { join } from 'node:path';

const requireFromFrontend = createRequire(join(process.cwd(), 'package.json'));

it('resolves the OpenAPI development route dependencies from the project root', () => {
  expect(() => requireFromFrontend.resolve('swagger-ui-dist')).not.toThrow();
});
