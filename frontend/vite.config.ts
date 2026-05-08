import { cloudflare } from "@cloudflare/vite-plugin";
import react from "@vitejs/plugin-react";
import { tanstackStart } from "@tanstack/react-start/plugin/vite";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig, loadEnv } from "vite";
import tsConfigPaths from "vite-tsconfig-paths";

function serverFnErrorLogger() {
  const hmrSendKey = "__TANSTACK_SERVER_FN_HMR_SEND__";

  return {
    name: "server-fn-error-logger",
    apply: "serve" as const,
    enforce: "pre" as const,
    configureServer(server: { ws: { send: (payload: unknown) => void } }) {
      (globalThis as Record<string, unknown>)[hmrSendKey] = (data: unknown) => {
        server.ws.send({
          type: "custom",
          event: "server-fn-error",
          data,
        });
      };
    },
    transform(code: string, id: string) {
      const normalizedId = id.replace(/\\/g, "/");
      const isTargetModule =
        normalizedId.includes("/@tanstack/start-server-core/src/server-functions-handler.ts") ||
        normalizedId.includes("/@tanstack/start-server-core/dist/esm/server-functions-handler.js");

      if (!isTargetModule) {
        return null;
      }

      const needle = "const unwrapped = res.result || res.error";
      if (!code.includes(needle)) {
        return null;
      }

      return code.replace(
        needle,
        `${needle}

      if (res?.error) {
        const err = res.error
        const payload = {
          source: 'tanstack',
          type: 'server-fn-error',
          method: request.method,
          url: request.url,
          name: err?.name ?? 'Error',
          message: err?.message ?? String(err),
          stack: typeof err?.stack === 'string' ? err.stack : undefined,
        }
        globalThis.${hmrSendKey}?.(payload)
      }`,
      );
    },
  };
}

export default defineConfig(({ command, mode }) => {
  const viteEnv = loadEnv(mode, process.cwd(), "VITE_");
  const envDefine = Object.fromEntries(
    Object.entries(viteEnv).map(([key, value]) => [`import.meta.env.${key}`, JSON.stringify(value)]),
  );

  return {
    define: envDefine,
    plugins: [
      tailwindcss(),
      tsConfigPaths({ projects: ["./tsconfig.json"] }),
      ...(command === "serve" ? [serverFnErrorLogger()] : []),
      ...(command === "build" ? [cloudflare({ viteEnvironment: { name: "ssr" } })] : []),
      tanstackStart({
        importProtection: {
          behavior: "error",
          client: {
            files: ["**/server/**"],
            specifiers: ["server-only"],
          },
        },
        server: { entry: "server" },
      }),
      react(),
    ],
    resolve: {
      alias: {
        "@": `${process.cwd()}/src`,
      },
      dedupe: [
        "react",
        "react-dom",
        "react/jsx-runtime",
        "react/jsx-dev-runtime",
        "@tanstack/react-query",
        "@tanstack/query-core",
      ],
    },
    server: {
      host: "::",
      port: 8080,
      watch: {
        awaitWriteFinish: {
          stabilityThreshold: 1000,
          pollInterval: 100,
        },
      },
    },
  };
});
