"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import Shell from "@/components/Shell";
import { useAuth } from "@/contexts/AuthContext";

export default function AdminDashboardPage() {
    const router = useRouter();
    const { role, isLoading } = useAuth();

    useEffect(() => {
        if (!isLoading && role === "admin") {
            router.replace("/admin/settings");
        }
    }, [isLoading, role, router]);

    return (
        <Shell title="系统设置" adminOnly>
            <div className="bsm-text-muted">
                正在跳转到系统设置…
            </div>
        </Shell>
    );
}
