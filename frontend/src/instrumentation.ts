import { registerOTel } from "@vercel/otel";

export function register() {
  registerOTel({
    serviceName: "readforge-web",
    instrumentationConfig: {
      fetch: {
        propagateContextUrls: [
          /\/api\//,
          /\/documents$/,
          /\/chat$/,
          /\/jobs\/[^/]+/,
        ],
      },
    },
  });
}
