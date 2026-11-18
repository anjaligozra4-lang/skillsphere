import { afterEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { cwd } from "node:process";

const viteConfigSource = readFileSync(resolve(cwd(), "vite.config.js"), "utf8");

afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
});

describe("API base URL configuration", () => {
  it("serves the frontend on port 5174 to match the local development setup", () => {
    expect(viteConfigSource).toMatch(/port:\s*5174/);
    expect(viteConfigSource).toMatch(/strictPort:\s*true/);
  });

  it("uses the local backend on port 8001 when VITE_API_URL is empty", async () => {
    vi.stubEnv("VITE_API_URL", "");
    const { default: api } = await import("./api");

    expect(api.defaults.baseURL).toBe("http://127.0.0.1:8001");
  });

  it("preserves an explicitly configured API URL", async () => {
    vi.stubEnv("VITE_API_URL", "https://api.example.test");
    const { default: api } = await import("./api");

    expect(api.defaults.baseURL).toBe("https://api.example.test");
  });
});
