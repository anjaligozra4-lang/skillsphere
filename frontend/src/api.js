import axios from "axios";

export const PRODUCTION_API_URL = "https://skillsphere-3beg.onrender.com";
export const LOCAL_API_URL = "http://127.0.0.1:8001";

export function getApiBaseUrl() {
  const envUrl = (import.meta.env.VITE_API_URL || "").trim();

  // When running in a browser environment:
  if (typeof window !== "undefined" && window.location) {
    const hostname = window.location.hostname;
    const isLocalhost =
      hostname === "localhost" ||
      hostname === "127.0.0.1" ||
      hostname === "0.0.0.0" ||
      hostname.endsWith(".local");

    // On any remote/deployed host (such as Vercel or Render), NEVER use or fall back to localhost
    if (!isLocalhost) {
      if (!envUrl || envUrl.includes("localhost") || envUrl.includes("127.0.0.1")) {
        return PRODUCTION_API_URL;
      }
      return envUrl.replace(/\/+$/, "");
    }
  }

  // If explicitly configured for local development or custom endpoint:
  if (envUrl) {
    return envUrl.replace(/\/+$/, "");
  }

  // When Vite builds for production mode without browser window:
  if (import.meta.env.PROD) {
    return PRODUCTION_API_URL;
  }

  // Local development / testing default
  return LOCAL_API_URL;
}

const api = axios.create({
  baseURL: getApiBaseUrl(),
});

api.interceptors.request.use((config) => {
  if (!config.baseURL) {
    config.baseURL = getApiBaseUrl();
  }
  const token = localStorage.getItem("skillsphere_token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

let refreshPromise = null;

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error?.config;
    const status = error?.response?.status;
    const url = originalRequest?.url || "";
    const isAuthRoute = url.includes("/api/auth/login") || url.includes("/api/auth/refresh");

    if (status === 401 && originalRequest && !originalRequest._retry && !isAuthRoute) {
      const refreshToken = localStorage.getItem("skillsphere_refresh_token");
      if (refreshToken) {
        originalRequest._retry = true;
        try {
          if (!refreshPromise) {
            const baseUrl = api.defaults.baseURL || getApiBaseUrl();
            refreshPromise = axios
              .post(`${baseUrl}/api/auth/refresh`, { refresh_token: refreshToken })
              .finally(() => {
                refreshPromise = null;
              });
          }
          const refreshRes = await refreshPromise;
          const data = refreshRes.data;
          localStorage.setItem("skillsphere_token", data.access_token);
          if (data.refresh_token) localStorage.setItem("skillsphere_refresh_token", data.refresh_token);
          if (data.role) localStorage.setItem("skillsphere_role", data.role);
          if (data.full_name) localStorage.setItem("skillsphere_name", data.full_name);
          if (data.id != null) localStorage.setItem("skillsphere_user_id", String(data.id));
          originalRequest.headers.Authorization = `Bearer ${data.access_token}`;
          return api(originalRequest);
        } catch {
          localStorage.removeItem("skillsphere_token");
          localStorage.removeItem("skillsphere_refresh_token");
          localStorage.removeItem("skillsphere_role");
          localStorage.removeItem("skillsphere_name");
          localStorage.removeItem("skillsphere_user_id");
        }
      }
    }
    return Promise.reject(error);
  },
);

export default api;


