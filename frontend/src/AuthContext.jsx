import { createContext, useContext, useMemo, useState } from "react";
import api from "./api";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [session, setSession] = useState(() => ({
    token: localStorage.getItem("skillsphere_token"),
    refreshToken: localStorage.getItem("skillsphere_refresh_token"),
    role: localStorage.getItem("skillsphere_role"),
    fullName: localStorage.getItem("skillsphere_name"),
    userId: localStorage.getItem("skillsphere_user_id"),
  }));

  const loginSession = (data) => {
    localStorage.setItem("skillsphere_token", data.access_token);
    if (data.refresh_token) {
      localStorage.setItem("skillsphere_refresh_token", data.refresh_token);
    }
    localStorage.setItem("skillsphere_role", data.role);
    localStorage.setItem("skillsphere_name", data.full_name);
    if (data.id != null) localStorage.setItem("skillsphere_user_id", String(data.id));
    setSession({
      token: data.access_token,
      refreshToken: data.refresh_token || null,
      role: data.role,
      fullName: data.full_name,
      userId: data.id,
    });
  };

  const logout = () => {
    const currentRefresh = localStorage.getItem("skillsphere_refresh_token");
    if (currentRefresh && typeof api.post === "function") {
      Promise.resolve(api.post("/api/auth/logout", { refresh_token: currentRefresh })).catch(() => {});
    }
    localStorage.removeItem("skillsphere_token");
    localStorage.removeItem("skillsphere_refresh_token");
    localStorage.removeItem("skillsphere_role");
    localStorage.removeItem("skillsphere_name");
    localStorage.removeItem("skillsphere_user_id");
    setSession({ token: null, refreshToken: null, role: null, fullName: null, userId: null });
  };

  const value = useMemo(() => ({ ...session, loginSession, logout }), [session]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  return useContext(AuthContext);
}
