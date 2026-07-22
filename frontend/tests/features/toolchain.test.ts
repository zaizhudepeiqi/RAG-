import { readFileSync } from 'node:fs';
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

it('encodes literal OpenAPI action suffixes in generated clients', () => {
  const providerClient = readFileSync(
    join(process.cwd(), 'src/services/ragApi/moxinggongyingshang.ts'),
    'utf8',
  );
  const modelClient = readFileSync(
    join(process.cwd(), 'src/services/ragApi/moxingpeizhi.ts'),
    'utf8',
  );

  expect(providerClient).toMatch(/\$\{param0\}%3Adiscover-models/u);
  expect(providerClient).toMatch(/\$\{param0\}%3Atest/u);
  expect(modelClient).toMatch(/\$\{param0\}%3Adisable/u);
  expect(modelClient).toMatch(/\$\{param0\}%3Aenable/u);
  expect(modelClient).toMatch(/\$\{param0\}%3Averify/u);
});
