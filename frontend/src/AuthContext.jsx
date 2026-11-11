import { createContext, useContext, useMemo, useState } from "react";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [session, setSession] = useState(() => ({
    token: localStorage.getItem("skillsphere_token"),
    role: localStorage.getItem("skillsphere_role"),
    fullName: localStorage.getItem("skillsphere_name"),
    userId: localStorage.getItem("skillsphere_user_id"),
  }));

  const loginSession = (data) => {
    localStorage.setItem("skillsphere_token", data.access_token);
    localStorage.setItem("skillsphere_role", data.role);
    localStorage.setItem("skillsphere_name", data.full_name);
    if (data.id != null) localStorage.setItem("skillsphere_user_id", data.id);
    setSession({ token: data.access_token, role: data.role, fullName: data.full_name, userId: data.id });
  };

  const logout = () => {
    localStorage.removeItem("skillsphere_token");
    localStorage.removeItem("skillsphere_role");
    localStorage.removeItem("skillsphere_name");
    localStorage.removeItem("skillsphere_user_id");
    setSession({ token: null, role: null, fullName: null, userId: null });
  };

  const value = useMemo(() => ({ ...session, loginSession, logout }), [session]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  return useContext(AuthContext);
}
