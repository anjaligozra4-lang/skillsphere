import axios from "axios";

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || "http://127.0.0.1:8000",
});

api.interceptors.request.use((config) => {
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
            refreshPromise = axios
              .post(`${api.defaults.baseURL}/api/auth/refresh`, { refresh_token: refreshToken })
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


