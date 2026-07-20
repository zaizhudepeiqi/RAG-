import { createRequire } from 'node:module';
import { join } from 'node:path';

const requireFromFrontend = createRequire(join(process.cwd(), 'package.json'));
const frontendPackage = requireFromFrontend('./package.json') as {
  scripts: Record<string, string>;
};

it('resolves the OpenAPI development route dependencies from the project root', () => {
  expect(() => requireFromFrontend.resolve('swagger-ui-dist')).not.toThrow();
});

it('generates Umi runtime types before the clean-environment check', () => {
  expect(frontendPackage.scripts.setup).toBe('max setup');
  expect(frontendPackage.scripts.check).toMatch(/^npm run setup && /);
});
