"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import Shell from "@/components/Shell";

export default function MyRulesPage() {
    const router = useRouter();

    useEffect(() => {
        router.replace("/notifications");
    }, [router]);

    return (
        <Shell title="通知中心">
            <div className="bsm-text-muted">
                正在跳转到通知中心…
            </div>
        </Shell>
    );
}
