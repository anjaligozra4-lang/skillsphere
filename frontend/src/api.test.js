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

  it("preserves an explicitly configured API URL and trims trailing slashes", async () => {
    vi.stubEnv("VITE_API_URL", "https://api.example.test/");
    const { default: api } = await import("./api");

    expect(api.defaults.baseURL).toBe("https://api.example.test");
  });

  it("defaults to the production backend on deployed hosts when VITE_API_URL is empty", async () => {
    vi.stubEnv("VITE_API_URL", "");
    const originalLocation = window.location;
    delete window.location;
    window.location = new URL("https://skillsphere-xi-mocha.vercel.app");

    try {
      const { default: api } = await import("./api");
      expect(api.defaults.baseURL).toBe("https://skillsphere-3beg.onrender.com");
    } finally {
      window.location = originalLocation;
    }
  });

  it("overrides a localhost VITE_API_URL when running on a deployed host like Vercel", async () => {
    vi.stubEnv("VITE_API_URL", "http://127.0.0.1:8001");
    const originalLocation = window.location;
    delete window.location;
    window.location = new URL("https://skillsphere-xi-mocha.vercel.app");

    try {
      const { default: api } = await import("./api");
      expect(api.defaults.baseURL).toBe("https://skillsphere-3beg.onrender.com");
    } finally {
      window.location = originalLocation;
    }
  });
});
