import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const rootEnvPath = join(dirname(fileURLToPath(import.meta.url)), "..", ".env");
if (existsSync(rootEnvPath)) {
  for (const line of readFileSync(rootEnvPath, "utf8").split(/\r?\n/)) {
    const raw = line.trim();
    if (!raw || raw.startsWith("#") || !raw.includes("=")) continue;
    const [key, ...valueParts] = raw.split("=");
    process.env[key] ??= valueParts.join("=").replace(/^['"]|['"]$/g, "");
  }
}

const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || process.env.BACKEND_URL || "http://127.0.0.1:8000";
const rawDevOrigins = (process.env.NEXT_ALLOWED_DEV_ORIGINS || "localhost,127.0.0.1,192.168.0.192")
  .split(",")
  .map((origin) => origin.trim())
  .filter(Boolean);
const devOrigins = Array.from(
  new Set(rawDevOrigins.flatMap((origin) => (origin.startsWith("http") ? [origin] : [origin, `http://${origin}:3001`]))),
);

/** @type {import('next').NextConfig} */
const nextConfig = {
  allowedDevOrigins: devOrigins,
  env: {
    NEXT_PUBLIC_BACKEND_URL: backendUrl,
  },
  async rewrites() {
    return {
      beforeFiles: [
        {
          source: "/api/:path*",
          destination: `${backendUrl}/api/:path*`,
        },
        {
          source: "/media/:path*",
          destination: `${backendUrl}/media/:path*`,
        },
        {
          source: "/static/:path*",
          destination: `${backendUrl}/static/:path*`,
        },
      ],
    };
  },
};

export default nextConfig;
