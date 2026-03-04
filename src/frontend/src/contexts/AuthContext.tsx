"use client";
import React, { createContext, useContext, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { apiGet, apiPost } from "@/lib/api";

interface AuthContextType {
    currentUser: string;
    role: string;
    login: (username: string, password: string, cfToken?: string) => Promise<{ ok: boolean; error?: string }>;
    logout: () => Promise<void>;
    isLoading: boolean;
}

const AuthContext = createContext<AuthContextType>({
    currentUser: "",
    role: "guest",
    login: async () => ({ ok: false }),
    logout: async () => { },
    isLoading: true,
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
    const [currentUser, setCurrentUser] = useState("");
    const [role, setRole] = useState("guest");
    const [isLoading, setIsLoading] = useState(true);
    const router = useRouter();

    useEffect(() => {
        let cancelled = false;

        const loadCurrentUser = async () => {
            try {
                const data = await apiGet<{
                    ok: boolean;
                    username?: string;
                    role?: string;
                }>("/api/auth/me");
                if (cancelled) {
                    return;
                }
                if (data.ok && data.username && data.role) {
                    setCurrentUser(data.username);
                    setRole(data.role);
                } else {
                    setCurrentUser("");
                    setRole("guest");
                }
            } catch {
                if (cancelled) {
                    return;
                }
                setCurrentUser("");
                setRole("guest");
                localStorage.removeItem("bsm_current_user");
                localStorage.removeItem("bsm_role");
            } finally {
                if (!cancelled) {
                    setIsLoading(false);
                }
            }
        };

        loadCurrentUser();
        return () => {
            cancelled = true;
        };
    }, []);

    const login = async (username: string, password: string, cfToken: string = "") => {
        try {
            const data = await apiPost<{
                ok: boolean;
                error?: string;
                username?: string;
                role?: string;
                redirect?: string;
            }>("/api/auth/login", { username, password, cf_token: cfToken });

            if (data.ok && data.username && data.role) {
                setCurrentUser(data.username);
                setRole(data.role);
                router.push(data.redirect || "/app");
                return { ok: true };
            }
            return { ok: false, error: data.error || "用户名或密码错误" };
        } catch (error) {
            return { ok: false, error: error instanceof Error ? error.message : "网络错误，请稍后重试" };
        }
    };

    const logout = async () => {
        try {
            await apiPost("/api/auth/logout", {});
        } catch { }
        setCurrentUser("");
        setRole("guest");
        localStorage.removeItem("bsm_current_user");
        localStorage.removeItem("bsm_role");
        router.push("/");
    };

    return (
        <AuthContext.Provider value={{ currentUser, role, login, logout, isLoading }}>
            {children}
        </AuthContext.Provider>
    );
}

export const useAuth = () => useContext(AuthContext);
