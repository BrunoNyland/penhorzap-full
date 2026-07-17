import { defineConfig } from 'vitest/config';
import fs from 'fs';
import path from 'path';

const angularJitPlugin = () => {
  return {
    name: 'angular-jit',
    transform(code: string, id: string) {
      if (!id.endsWith('.ts')) return;

      let newCode = code;
      const dir = path.dirname(id);

      // Match templateUrl: './abc.component.html' or templateUrl: 'abc.component.html'
      const templateUrlRegex = /templateUrl\s*:\s*['"`]([^'"`]+)['"`]/g;
      let match;
      while ((match = templateUrlRegex.exec(code)) !== null) {
        const relativePath = match[1];
        const absolutePath = path.resolve(dir, relativePath);
        if (fs.existsSync(absolutePath)) {
          const htmlContent = fs.readFileSync(absolutePath, 'utf8')
            .replace(/\\/g, '\\\\')
            .replace(/`/g, '\\`');
          newCode = newCode.replace(match[0], `template: \`${htmlContent}\``);
        }
      }

      // Match styleUrl: './abc.component.css' or styleUrl: 'abc.component.css'
      const styleUrlRegex = /styleUrl\s*:\s*['"`]([^'"`]+)['"`]/g;
      while ((match = styleUrlRegex.exec(code)) !== null) {
        const relativePath = match[1];
        const absolutePath = path.resolve(dir, relativePath);
        if (fs.existsSync(absolutePath)) {
          const cssContent = fs.readFileSync(absolutePath, 'utf8')
            .replace(/\\/g, '\\\\')
            .replace(/`/g, '\\`');
          newCode = newCode.replace(match[0], `styles: [\`${cssContent}\`]`);
        }
      }

      // Match styleUrls: ['./abc.component.css']
      const styleUrlsRegex = /styleUrls\s*:\s*\[\s*['"`]([^'"`]+)['"`]\s*\]/g;
      while ((match = styleUrlsRegex.exec(code)) !== null) {
        const relativePath = match[1];
        const absolutePath = path.resolve(dir, relativePath);
        if (fs.existsSync(absolutePath)) {
          const cssContent = fs.readFileSync(absolutePath, 'utf8')
            .replace(/\\/g, '\\\\')
            .replace(/`/g, '\\`');
          newCode = newCode.replace(match[0], `styles: [\`${cssContent}\`]`);
        }
      }

      return {
        code: newCode,
        map: null,
      };
    },
  };
};

export default defineConfig({
  plugins: [angularJitPlugin()],
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['src/setup-vitest.ts'],
    coverage: {
      provider: 'istanbul',
      reporter: ['text', 'json', 'html'],
    },
  },
});
