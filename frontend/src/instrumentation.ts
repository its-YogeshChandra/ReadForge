import { registerOTel } from "@vercel/otel";

export function register() {
  registerOTel({
    serviceName: "readforge-web",
    instrumentationConfig: {
      fetch: {
        propagateContextUrls: [/localhost:8000/, /\/api\//],
      },
    },
  });
}
