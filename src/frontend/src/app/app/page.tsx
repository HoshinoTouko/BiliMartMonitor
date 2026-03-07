"use client";
import { useCallback, useEffect, useState } from "react";
import Shell from "@/components/Shell";
import { useAuth } from "@/contexts/AuthContext";
import { apiGet } from "@/lib/api";
import { timeAgo as timeAgoFromApiDate } from "@/lib/datetime";

interface DashboardStats {
    ok: boolean;
    today_refresh_count: number;
    today_new_item_count: number;
    user_count: number;
    active_session_count: number;
    item_count: number;
    last_scan_at: string | null;
    is_running: boolean;
}

function timeAgo(iso: string | null): string {
    return timeAgoFromApiDate(iso, "暂无");
}

export default function UserDashboardPage() {
    const { currentUser, isLoading } = useAuth();
    const [stats, setStats] = useState<DashboardStats | null>(null);
    const [loading, setLoading] = useState(true);
    const [refreshing, setRefreshing] = useState(false);
    const [dbPing, setDbPing] = useState<number | null>(null);
    const [dbPingError, setDbPingError] = useState<string | null>(null);
    const [pinging, setPinging] = useState(false);

    const runDbPing = useCallback(async () => {
        setPinging(true);
        setDbPingError(null);
        try {
            const data = await apiGet<{ latency_ms?: number; error?: string }>("/api/account/db-ping");
            if (data.error) {
                setDbPing(null);
                setDbPingError(data.error);
            } else {
                setDbPing(data.latency_ms ?? null);
            }
        } catch (e) {
            setDbPing(null);
            setDbPingError(e instanceof Error ? e.message : "数据库测试失败");
        } finally {
            setPinging(false);
        }
    }, []);

    const loadDashboard = useCallback(async () => {
        try {
            const data = await apiGet<DashboardStats>("/api/account/dashboard");
            if (data.ok) {
                setStats(data);
            }
        } catch {
            // ignore
        } finally {
            setLoading(false);
        }
    }, []);

    const refreshAll = useCallback(async () => {
        setRefreshing(true);
        try {
            await Promise.all([loadDashboard(), runDbPing()]);
        } finally {
            setRefreshing(false);
        }
    }, [loadDashboard, runDbPing]);

    useEffect(() => {
        if (isLoading) return;
        if (!currentUser) {
            setLoading(false);
            return;
        }

        loadDashboard();
        runDbPing();
        const pollId = window.setInterval(loadDashboard, 10000);
        return () => window.clearInterval(pollId);
    }, [currentUser, isLoading, loadDashboard, runDbPing]);

    return (
        <Shell title="用户首页">
            <p className="bsm-text-secondary">当前监控概览。</p>

            <div className="bsm-stats-grid bsm-mt-3">
                <div className="bsm-stat-card">
                    <span className="bsm-stat-label">今日刷新次数</span>
                    <span className="bsm-stat-value">
                        {loading ? "..." : `${stats?.today_refresh_count ?? 0}`}
                    </span>
                </div>
                <div className="bsm-stat-card">
                    <span className="bsm-stat-label">今日新增商品</span>
                    <span className="bsm-stat-value">
                        {loading ? "..." : `${stats?.today_new_item_count ?? 0}`}
                    </span>
                </div>
                <div className="bsm-stat-card">
                    <span className="bsm-stat-label">数据库延迟</span>
                    <span className="bsm-stat-value" style={{ fontSize: "1.25rem" }}>
                        {pinging ? "测试中..." : dbPing != null ? `${dbPing} ms` : "—"}
                    </span>
                    <div
                        role="button"
                        tabIndex={0}
                        onClick={() => {
                            if (!pinging) {
                                void runDbPing();
                            }
                        }}
                        onKeyDown={(e) => {
                            if ((e.key === "Enter" || e.key === " ") && !pinging) {
                                e.preventDefault();
                                void runDbPing();
                            }
                        }}
                        style={{
                            fontSize: "0.75rem",
                            color: dbPingError ? "var(--error)" : "var(--text-muted)",
                            cursor: pinging ? "default" : "pointer",
                            userSelect: "none",
                        }}
                        title="点击重新测试数据库延迟"
                    >
                        {dbPingError || (pinging ? "正在测试..." : "点击重新测试")}
                    </div>
                </div>
                <div className="bsm-stat-card">
                    <span className="bsm-stat-label">活跃用户</span>
                    <span className="bsm-stat-value">
                        {loading ? "..." : `${stats?.user_count ?? 0}`}
                    </span>
                </div>
                <div className="bsm-stat-card">
                    <span className="bsm-stat-label">最近扫描</span>
                    <span className="bsm-stat-value" style={{ fontSize: "1.25rem" }}>
                        {loading ? "..." : timeAgo(stats?.last_scan_at ?? null)}
                    </span>
                </div>
                <div className="bsm-stat-card">
                    <span className="bsm-stat-label">活跃会话</span>
                    <span className="bsm-stat-value">
                        {loading ? "..." : `${stats?.active_session_count ?? 0}`}
                    </span>
                </div>
            </div>

            <p className="bsm-text-muted bsm-mt-2">
                统计来自后台扫描任务与当前数据库。
            </p>

            <div
                className="bsm-mt-3"
                style={{ display: "flex", justifyContent: "center" }}
            >
                <button
                    type="button"
                    className="bsm-btn bsm-btn-outline"
                    onClick={() => {
                        if (!refreshing) {
                            void refreshAll();
                        }
                    }}
                    disabled={refreshing}
                    style={{ width: "100%", maxWidth: "240px" }}
                >
                    {refreshing ? "刷新中..." : "刷新首页数据"}
                </button>
            </div>
        </Shell>
    );
}
