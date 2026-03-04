"use client";
import { useEffect, useState, useCallback, useRef } from "react";
import Shell from "@/components/Shell";
import { apiGet, apiPost, apiPut } from "@/lib/api";

interface CronStatus {
    is_running: boolean;
    last_scan_at: string | null;
    last_scan_count: number;
    last_saved: number;
    last_inserted: number;
    last_error: string | null;
    next_scan_in: number | null;
    total_scans: number;
}

interface Settings {
    scan_mode: string;
    interval: number;
    category: string;
    timezone: string;
    app_base_url: string;
    cloudflare_validation_enabled: boolean;
    cloudflare_turnstile_site_key: string;
    cloudflare_turnstile_secret_key_configured: boolean;
    bili_session_pick_mode: string;
    bili_session_cooldown_seconds: number;
    admin_telegram_ids: string[];
    price_filters: string[];
    discount_filters: string[];
    db_backend: string;
    cron: CronStatus;
}

interface LogLine {
    ts: string;
    level: "INFO" | "WARN" | "ERROR";
    msg: string;
}

const LEVEL_COLORS: Record<string, string> = {
    INFO: "var(--text-secondary)",
    WARN: "#fbbf24",
    ERROR: "#f87171",
};

function timeAgo(iso: string): string {
    const diff = Math.floor((Date.now() - new Date(iso.replace(" ", "T")).getTime()) / 1000);
    if (diff < 0) return "刚刚";
    if (diff < 60) return `${diff} 秒前`;
    if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`;
    return `${Math.floor(diff / 3600)} 小时前`;
}

export default function SystemSettingsPage() {
    const [settings, setSettings] = useState<Settings | null>(null);
    const [cron, setCron] = useState<CronStatus | null>(null);
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [saveMsg, setSaveMsg] = useState("");
    const [restartingCron, setRestartingCron] = useState(false);
    const [triggeringScan, setTriggeringScan] = useState(false);
    const [logs, setLogs] = useState<LogLine[]>([]);
    const [autoScroll, setAutoScroll] = useState(true);
    const logWindowRef = useRef<HTMLDivElement>(null);

    // Readonly logic
    const [dbPing, setDbPing] = useState<number | null>(null);
    const [dbPingError, setDbPingError] = useState<string | null>(null);
    const [pinging, setPinging] = useState(false);

    // Editable fields
    const [scanMode, setScanMode] = useState("latest");
    const [interval, setInterval] = useState(20);
    const [category, setCategory] = useState("");
    const [timezone, setTimezone] = useState("Asia/Shanghai");
    const [appBaseUrl, setAppBaseUrl] = useState("");
    const [cloudflareValidationEnabled, setCloudflareValidationEnabled] = useState(false);
    const [cloudflareTurnstileSiteKey, setCloudflareTurnstileSiteKey] = useState("");
    const [cloudflareTurnstileSecretKeyConfigured, setCloudflareTurnstileSecretKeyConfigured] = useState(false);
    const [cloudflareTurnstileSecretKey, setCloudflareTurnstileSecretKey] = useState("");
    const [clearCloudflareTurnstileSecretKey, setClearCloudflareTurnstileSecretKey] = useState(false);
    const [biliSessionPickMode, setBiliSessionPickMode] = useState("round_robin");
    const [biliSessionCooldownSeconds, setBiliSessionCooldownSeconds] = useState(60);
    const [adminTelegramIdsText, setAdminTelegramIdsText] = useState("");
    const [priceFilters, setPriceFilters] = useState<string[]>([]);
    const [discountFilters, setDiscountFilters] = useState<string[]>([]);

    const loadSettings = useCallback(async () => {
        try {
            const data = await apiGet<Settings>("/api/settings");
            setSettings(data);
            setCron(data.cron);
            setScanMode(data.scan_mode);
            setInterval(data.interval);
            setCategory(data.category);
            setTimezone(data.timezone);
            setAppBaseUrl(data.app_base_url || "");
            setCloudflareValidationEnabled(Boolean(data.cloudflare_validation_enabled));
            setCloudflareTurnstileSiteKey(data.cloudflare_turnstile_site_key || "");
            setCloudflareTurnstileSecretKeyConfigured(Boolean(data.cloudflare_turnstile_secret_key_configured));
            setCloudflareTurnstileSecretKey("");
            setClearCloudflareTurnstileSecretKey(false);
            setBiliSessionPickMode(data.bili_session_pick_mode || "round_robin");
            setBiliSessionCooldownSeconds(data.bili_session_cooldown_seconds ?? 60);
            setAdminTelegramIdsText((data.admin_telegram_ids || []).join("\n"));
            setPriceFilters(data.price_filters || []);
            setDiscountFilters(data.discount_filters || []);
        } finally {
            setLoading(false);
        }
    }, []);

    const handlePingDb = useCallback(async () => {
        setPinging(true);
        setDbPingError(null);
        try {
            const data = await apiGet("/api/settings/db-ping") as { error?: string, latency_ms?: number };
            if (data.error) {
                setDbPingError(data.error);
                setDbPing(null);
            } else {
                setDbPing(data.latency_ms ?? null);
                setDbPingError(null);
            }
        } catch (e) {
            setDbPingError(e instanceof Error ? e.message : "Network error pinging DB");
            setDbPing(null);
        } finally {
            setPinging(false);
        }
    }, []);

    // Poll cron status every 3s
    useEffect(() => {
        loadSettings();
        handlePingDb();
    }, [loadSettings, handlePingDb]);

    useEffect(() => {
        if (loading || !settings) {
            return;
        }

        apiGet("/api/settings/logs?n=50").then((data: unknown) => {
            const d = data as { logs?: LogLine[] };
            if (d) setLogs(d.logs ?? []);
        }).catch(() => { });

        const pollCron = window.setInterval(() => {
            apiGet<CronStatus>("/api/settings/cron").then(data => {
                if (data) setCron(data);
            }).catch(() => { });

            apiGet("/api/settings/logs?n=50").then((data: unknown) => {
                const d = data as { logs?: LogLine[] };
                if (d) setLogs(d.logs ?? []);
            }).catch(() => { });
        }, 3000);
        return () => window.clearInterval(pollCron);
    }, [loading, settings]);

    useEffect(() => {
        if (autoScroll && logWindowRef.current) {
            // Using scrollTop instead of scrollIntoView to avoid browser focus shift
            logWindowRef.current.scrollTop = logWindowRef.current.scrollHeight;
        }
    }, [logs, autoScroll]);

    const handleSave = async () => {
        setSaving(true);
        setSaveMsg("");
        try {
            const payload: Record<string, unknown> = {
                scan_mode: scanMode,
                interval,
                category,
                timezone,
                app_base_url: appBaseUrl.trim(),
                cloudflare_validation_enabled: cloudflareValidationEnabled,
                cloudflare_turnstile_site_key: cloudflareTurnstileSiteKey.trim(),
                bili_session_pick_mode: biliSessionPickMode,
                bili_session_cooldown_seconds: biliSessionCooldownSeconds,
                admin_telegram_ids: adminTelegramIdsText.split(/[\n,，]/).map((item) => item.trim()).filter(Boolean),
                price_filters: priceFilters,
                discount_filters: discountFilters,
            };
            const nextSecret = cloudflareTurnstileSecretKey.trim();
            if (clearCloudflareTurnstileSecretKey) {
                payload.cloudflare_turnstile_secret_key = "";
            } else if (nextSecret) {
                payload.cloudflare_turnstile_secret_key = nextSecret;
            }
            const data = await apiPut("/api/settings", payload) as { ok?: boolean, error?: string, restarted_cron?: boolean };
            if (data.ok) {
                if (clearCloudflareTurnstileSecretKey) {
                    setCloudflareTurnstileSecretKeyConfigured(false);
                } else if (nextSecret) {
                    setCloudflareTurnstileSecretKeyConfigured(true);
                }
                setCloudflareTurnstileSecretKey("");
                setClearCloudflareTurnstileSecretKey(false);
                setSaveMsg(data.restarted_cron ? "✅ 已保存，扫描任务已重启并立即执行" : "✅ 已保存");
                const cronData = await apiGet<CronStatus>("/api/settings/cron");
                setCron(cronData);
            } else {
                setSaveMsg(`❌ ${data.error ?? "保存失败"}`);
            }
        } catch (e) {
            setSaveMsg(`❌ ${e instanceof Error ? e.message : "网络错误"}`);
        } finally {
            setSaving(false);
            setTimeout(() => setSaveMsg(""), 4000);
        }
    };

    const handleTriggerScan = async () => {
        setTriggeringScan(true);
        setSaveMsg("");
        try {
            const data = await apiPost("/api/settings/cron/trigger", {}) as { ok?: boolean };
            if (data.ok) {
                setSaveMsg("✅ 已触发，下次扫描将立即执行");
            } else {
                setSaveMsg("❌ 触发失败");
            }
            const cronData = await apiGet<CronStatus>("/api/settings/cron");
            setCron(cronData);
        } catch (e) {
            setSaveMsg(`❌ ${e instanceof Error ? e.message : "触发失败"}`);
        } finally {
            setTriggeringScan(false);
            setTimeout(() => setSaveMsg(""), 4000);
        }
    };

    const handleRestartCron = async () => {
        setRestartingCron(true);
        setSaveMsg("");
        try {
            const data = await apiPost("/api/settings/cron/restart", {}) as { ok?: boolean };
            if (data.ok) {
                setSaveMsg("✅ Cron 已重启并立即执行");
            } else {
                setSaveMsg("❌ 重启失败");
            }
            const cronData = await apiGet<CronStatus>("/api/settings/cron");
            setCron(cronData);
        } catch (e) {
            setSaveMsg(`❌ ${e instanceof Error ? e.message : "重启失败"}`);
        } finally {
            setRestartingCron(false);
            setTimeout(() => setSaveMsg(""), 4000);
        }
    };

    return (
        <Shell title="系统设置" adminOnly>
            {/* ── Cron Status ── */}
            <div className="bsm-section">
                <div className="bsm-section-title">扫描任务</div>
                {cron ? (
                    <div className="bsm-settings-cron-grid">
                        <div className="bsm-stat-card">
                            <span className="bsm-stat-label">状态</span>
                            <span className="bsm-stat-value" style={{ fontSize: "1rem" }}>
                                {cron.is_running ? (
                                    <span style={{ color: "var(--brand-accent)" }}>● 运行中</span>
                                ) : (
                                    <span style={{ color: "var(--text-muted)" }}>○ 停止</span>
                                )}
                            </span>
                        </div>
                        <div className="bsm-stat-card">
                            <span className="bsm-stat-label">上次扫描</span>
                            <span className="bsm-stat-value" style={{ fontSize: "0.95rem" }}>
                                {cron.last_scan_at ? timeAgo(cron.last_scan_at) : "—"}
                            </span>
                        </div>
                        <div className="bsm-stat-card">
                            <span className="bsm-stat-label">上次结果</span>
                            <span className="bsm-stat-value" style={{ fontSize: "0.95rem" }}>
                                {cron.last_scan_at
                                    ? `${cron.last_scan_count} 条 / ${cron.last_inserted} 新`
                                    : "—"}
                            </span>
                        </div>
                        <div className="bsm-stat-card">
                            <span className="bsm-stat-label">下次扫描</span>
                            <span className="bsm-stat-value" style={{ fontSize: "0.95rem" }}>
                                {cron.next_scan_in != null
                                    ? `${Math.ceil(cron.next_scan_in)} 秒后`
                                    : "扫描中…"}
                            </span>
                        </div>
                        <div className="bsm-stat-card">
                            <span className="bsm-stat-label">累计扫描</span>
                            <span className="bsm-stat-value" style={{ fontSize: "0.95rem" }}>
                                {cron.total_scans} 次
                            </span>
                        </div>
                        {cron.last_error && (
                            <div className="bsm-stat-card" style={{ gridColumn: "1 / -1" }}>
                                <span className="bsm-stat-label">上次错误</span>
                                <span className="bsm-stat-value" style={{ fontSize: "0.8rem", color: "#f87171" }}>
                                    {cron.last_error}
                                </span>
                            </div>
                        )}
                    </div>
                ) : (
                    <div className="bsm-text-muted">加载中…</div>
                )}
            </div>

            {/* ── Editable Config ── */}
            <div className="bsm-section">
                <div className="bsm-section-title">扫描配置</div>
                {loading ? (
                    <div className="bsm-text-muted">加载中…</div>
                ) : (
                    <div className="bsm-settings-form">
                        {/* scan_mode */}
                        <div className="bsm-settings-row">
                            <label className="bsm-settings-label">扫描模式</label>
                            <div className="bsm-settings-control">
                                <label className="bsm-settings-radio">
                                    <input type="radio" name="scan_mode" value="latest"
                                        checked={scanMode === "latest"}
                                        onChange={() => setScanMode("latest")} />
                                    <span title="每次扫描都从最新列表第一页开始，适合持续盯最新上架商品。">
                                        latest（每次扫描最新页）
                                    </span>
                                </label>
                                <label className="bsm-settings-radio">
                                    <input type="radio" name="scan_mode" value="continue"
                                        checked={scanMode === "continue"}
                                        onChange={() => setScanMode("continue")} />
                                    <span title="从上次停下的位置继续往后翻页扫描，单次最多推进 50 页；到末页或重启后会从第一页重新开始。">
                                        continue（续扫，最多 50 页）
                                    </span>
                                </label>
                                <label className="bsm-settings-radio">
                                    <input type="radio" name="scan_mode" value="continue_until_repeat"
                                        checked={scanMode === "continue_until_repeat"}
                                        onChange={() => setScanMode("continue_until_repeat")} />
                                    <span title="像 continue 一样翻页续扫，但只要当前页出现任意已存在商品，就在下一轮回到第一页；同样最多推进 30 页，重启后也会从第一页开始。">
                                        CUR（遇重复回首页，最多 30 页）
                                    </span>
                                </label>
                            </div>
                        </div>

                        {/* interval */}
                        <div className="bsm-settings-row">
                            <label className="bsm-settings-label">扫描间隔（秒）</label>
                            <div className="bsm-settings-control">
                                <input
                                    type="number" min={5} max={3600}
                                    className="bsm-input" style={{ width: "120px" }}
                                    value={interval}
                                    onChange={(e) => setInterval(Number(e.target.value))}
                                />
                                <span className="bsm-text-muted" style={{ marginLeft: "0.5rem", fontSize: "0.8125rem" }}>
                                    最小 5 秒
                                </span>
                            </div>
                        </div>

                        {/* category */}
                        <div className="bsm-settings-row">
                            <label className="bsm-settings-label bsm-settings-label-top">
                                分类 ID
                                <span className="bsm-text-muted" style={{ fontWeight: 400, marginLeft: "0.25rem", fontSize: "0.75rem" }}>(config.yaml)</span>
                            </label>
                            <div className="bsm-settings-control" style={{ flexWrap: "wrap", gap: "0.75rem" }}>
                                {[
                                    { label: "手办", id: "2312" },
                                    { label: "模型", id: "2066" },
                                    { label: "周边", id: "2331" },
                                    { label: "3C", id: "2273" },
                                    { label: "福袋", id: "fudai_cate_id" }
                                ].map((item) => {
                                    const selectedKeys = category ? category.split(",").map(k => k.trim()).filter(Boolean) : [];
                                    const isChecked = selectedKeys.includes(item.id);
                                    return (
                                        <label key={item.id} className="bsm-settings-radio" style={{ display: "inline-flex", alignItems: "center", cursor: "pointer" }}>
                                            <input
                                                type="checkbox"
                                                checked={isChecked}
                                                onChange={(e) => {
                                                    let newKeys = [...selectedKeys];
                                                    if (e.target.checked) {
                                                        if (!newKeys.includes(item.id)) newKeys.push(item.id);
                                                    } else {
                                                        newKeys = newKeys.filter((k) => k !== item.id);
                                                    }
                                                    setCategory(newKeys.join(","));
                                                }}
                                            />
                                            <span style={{ marginLeft: "0.35rem" }}>{item.label}</span>
                                        </label>
                                    );
                                })}
                            </div>
                        </div>

                        {/* timezone */}
                        <div className="bsm-settings-row">
                            <label className="bsm-settings-label">
                                时区
                                <span className="bsm-text-muted" style={{ fontWeight: 400, marginLeft: "0.25rem", fontSize: "0.75rem" }}>(config.yaml)</span>
                            </label>
                            <div className="bsm-settings-control">
                                <input
                                    type="text" className="bsm-input" style={{ width: "100%", maxWidth: "200px" }}
                                    placeholder="e.g. Asia/Shanghai"
                                    value={timezone}
                                    onChange={(e) => setTimezone(e.target.value)}
                                />
                            </div>
                        </div>

                        <div className="bsm-settings-row">
                            <label className="bsm-settings-label">
                                应用地址
                                <span className="bsm-text-muted" style={{ fontWeight: 400, marginLeft: "0.25rem", fontSize: "0.75rem" }}>(可选)</span>
                            </label>
                            <div className="bsm-settings-control">
                                <input
                                    type="text"
                                    className="bsm-input"
                                    style={{ width: "100%", maxWidth: "360px" }}
                                    placeholder="https://your-domain.example"
                                    value={appBaseUrl}
                                    onChange={(e) => setAppBaseUrl(e.target.value)}
                                />
                                <span className="bsm-text-muted" style={{ fontSize: "0.8125rem" }}>
                                    Telegram 推送会附带应用内详情页链接
                                </span>
                            </div>
                        </div>

                        <div className="bsm-settings-row">
                            <label className="bsm-settings-label">Cloudflare 验证</label>
                            <div className="bsm-settings-control">
                                <label className="bsm-settings-radio">
                                    <input
                                        type="checkbox"
                                        checked={cloudflareValidationEnabled}
                                        onChange={(e) => setCloudflareValidationEnabled(e.target.checked)}
                                    />
                                    <span>{cloudflareValidationEnabled ? "登录时启用 Turnstile 验证" : "关闭"}</span>
                                </label>
                            </div>
                        </div>

                        <div className="bsm-settings-row">
                            <label className="bsm-settings-label">Turnstile Site Key</label>
                            <div className="bsm-settings-control">
                                <input
                                    type="text"
                                    className="bsm-input"
                                    style={{ width: "100%", maxWidth: "360px" }}
                                    placeholder="Cloudflare Turnstile Site Key"
                                    value={cloudflareTurnstileSiteKey}
                                    onChange={(e) => setCloudflareTurnstileSiteKey(e.target.value)}
                                />
                            </div>
                        </div>

                        <div className="bsm-settings-row">
                            <label className="bsm-settings-label">Turnstile Secret Key</label>
                            <div className="bsm-settings-control">
                                <input
                                    type="password"
                                    className="bsm-input"
                                    style={{ width: "100%", maxWidth: "360px" }}
                                    placeholder={cloudflareTurnstileSecretKeyConfigured ? "留空则保持当前 Secret" : "Cloudflare Turnstile Secret Key"}
                                    value={cloudflareTurnstileSecretKey}
                                    disabled={clearCloudflareTurnstileSecretKey}
                                    onChange={(e) => setCloudflareTurnstileSecretKey(e.target.value)}
                                />
                                <span className="bsm-text-muted" style={{ fontSize: "0.8125rem" }}>
                                    {cloudflareTurnstileSecretKeyConfigured ? "服务端已保存 Secret，页面不会回显当前值。" : "当前未配置 Secret。"}
                                </span>
                                <label className="bsm-settings-radio">
                                    <input
                                        type="checkbox"
                                        checked={clearCloudflareTurnstileSecretKey}
                                        onChange={(e) => setClearCloudflareTurnstileSecretKey(e.target.checked)}
                                    />
                                    <span>保存时清空已保存的 Secret</span>
                                </label>
                            </div>
                        </div>

                        <div className="bsm-settings-row">
                            <label className="bsm-settings-label">BiliSession 选择机制</label>
                            <div className="bsm-settings-control">
                                <label className="bsm-settings-radio">
                                    <input
                                        type="radio"
                                        name="bili_session_pick_mode"
                                        value="round_robin"
                                        checked={biliSessionPickMode === "round_robin"}
                                        onChange={() => setBiliSessionPickMode("round_robin")}
                                    />
                                    <span>轮询（按最久未使用）</span>
                                </label>
                                <label className="bsm-settings-radio">
                                    <input
                                        type="radio"
                                        name="bili_session_pick_mode"
                                        value="random"
                                        checked={biliSessionPickMode === "random"}
                                        onChange={() => setBiliSessionPickMode("random")}
                                    />
                                    <span>随机</span>
                                </label>
                            </div>
                        </div>

                        <div className="bsm-settings-row">
                            <label className="bsm-settings-label">BiliSession 冷却期（秒）</label>
                            <div className="bsm-settings-control">
                                <input
                                    type="number"
                                    min={0}
                                    max={3600}
                                    className="bsm-input"
                                    style={{ width: "120px" }}
                                    value={biliSessionCooldownSeconds}
                                    onChange={(e) => setBiliSessionCooldownSeconds(Number(e.target.value))}
                                />
                                <span className="bsm-text-muted" style={{ marginLeft: "0.5rem", fontSize: "0.8125rem" }}>
                                    某个 Session 报错后，在冷却期内不会被再次选中；0 表示关闭
                                </span>
                            </div>
                        </div>

                        <div className="bsm-settings-row">
                            <label className="bsm-settings-label bsm-settings-label-top">Admin Telegram IDs</label>
                            <div className="bsm-settings-control">
                                <textarea
                                    className="bsm-input bsm-notification-textarea"
                                    placeholder={"每行一个 TG ID，也支持逗号分隔"}
                                    value={adminTelegramIdsText}
                                    onChange={(e) => setAdminTelegramIdsText(e.target.value)}
                                />
                                <span className="bsm-text-muted" style={{ fontSize: "0.8125rem" }}>
                                    系统告警（如扫描频率过高、Fail2Ban 触发）会推送到这些 ID
                                </span>
                            </div>
                        </div>

                        {/* price_filters */}
                        <div className="bsm-settings-row">
                            <label className="bsm-settings-label bsm-settings-label-top">
                                价格区间
                                <div className="bsm-text-muted" style={{ fontWeight: 400, fontSize: "0.75rem" }}>B站仅支持特定区间</div>
                            </label>
                            <div className="bsm-settings-control" style={{ flexWrap: "wrap", gap: "0.75rem" }}>
                                {[
                                    { label: "0-20", id: "0-2000" },
                                    { label: "20-30", id: "2000-3000" },
                                    { label: "30-50", id: "3000-5000" },
                                    { label: "50-100", id: "5000-10000" },
                                    { label: "100-200", id: "10000-20000" },
                                    { label: "200+", id: "20000-0" },
                                ].map((item) => (
                                    <label key={item.id} className="bsm-settings-radio" style={{ display: "inline-flex", alignItems: "center", cursor: "pointer" }}>
                                        <input
                                            type="checkbox"
                                            checked={priceFilters.includes(item.id)}
                                            onChange={(e) => {
                                                if (e.target.checked) {
                                                    setPriceFilters([...priceFilters, item.id]);
                                                } else {
                                                    setPriceFilters(priceFilters.filter(id => id !== item.id));
                                                }
                                            }}
                                        />
                                        <span style={{ marginLeft: "0.35rem" }}>{item.label}</span>
                                    </label>
                                ))}
                            </div>
                        </div>

                        {/* discount_filters */}
                        <div className="bsm-settings-row">
                            <label className="bsm-settings-label bsm-settings-label-top">
                                折扣区间
                                <div className="bsm-text-muted" style={{ fontWeight: 400, fontSize: "0.75rem" }}>B站仅支持特定区间</div>
                            </label>
                            <div className="bsm-settings-control" style={{ flexWrap: "wrap", gap: "0.75rem" }}>
                                {[
                                    { label: "7折-原价", id: "70-100" },
                                    { label: "5折-7折", id: "50-70" },
                                    { label: "3折-5折", id: "30-50" },
                                    { label: "3折以下", id: "0-30" },
                                ].map((item) => (
                                    <label key={item.id} className="bsm-settings-radio" style={{ display: "inline-flex", alignItems: "center", cursor: "pointer" }}>
                                        <input
                                            type="checkbox"
                                            checked={discountFilters.includes(item.id)}
                                            onChange={(e) => {
                                                if (e.target.checked) {
                                                    setDiscountFilters([...discountFilters, item.id]);
                                                } else {
                                                    setDiscountFilters(discountFilters.filter(id => id !== item.id));
                                                }
                                            }}
                                        />
                                        <span style={{ marginLeft: "0.35rem" }}>{item.label}</span>
                                    </label>
                                ))}
                            </div>
                        </div>

                        {/* Save */}
                        <div className="bsm-settings-row">
                            <div className="bsm-settings-spacer" />
                            <div className="bsm-settings-control bsm-settings-actions">
                                <button
                                    className="bsm-btn bsm-btn-primary"
                                    onClick={handleSave}
                                    disabled={saving}
                                >
                                    {saving ? "保存中…" : "保存配置"}
                                </button>
                                {saveMsg && (
                                    <span className={`bsm-settings-status ${saveMsg.startsWith("✅") ? "success" : "error"}`}>
                                        {saveMsg}
                                    </span>
                                )}
                            </div>
                        </div>
                    </div>
                )}
            </div>

            {/* ── Readonly Info ── */}
            {settings && (
                <div className="bsm-section">
                    <div className="bsm-section-title">环境信息</div>
                    <div className="bsm-info-grid">
                        <div className="bsm-info-row">
                            <span className="bsm-info-key">数据库后端</span>
                            <span className="bsm-info-value">{settings.db_backend}</span>
                        </div>
                        <div className="bsm-info-row" style={{ alignItems: "center" }}>
                            <span className="bsm-info-key">数据库延迟</span>
                            <span className="bsm-info-value" style={{ display: "flex", alignItems: "center", gap: "1rem" }}>
                                {dbPingError ? (
                                    <span style={{ color: "#f87171", fontSize: "0.85rem" }}>{dbPingError}</span>
                                ) : dbPing != null ? (
                                    <span style={{
                                        color: dbPing < 50 ? "var(--brand-accent)" : dbPing < 200 ? "#fbbf24" : "#f87171",
                                        fontWeight: 600
                                    }}>
                                        {dbPing.toFixed(1)} ms
                                    </span>
                                ) : (
                                    <span className="bsm-text-muted">未知</span>
                                )}
                                <button className="bsm-btn" style={{ padding: "0.25rem 0.5rem", fontSize: "0.85rem", height: "auto" }} onClick={handlePingDb} disabled={pinging}>
                                    {pinging ? "..." : "测试"}
                                </button>
                            </span>
                        </div>
                    </div>
                </div>
            )}

            <div className="bsm-section">
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "0.75rem" }}>
                    <div className="bsm-section-title" style={{ margin: 0 }}>系统日志</div>
                    <label style={{ display: "flex", alignItems: "center", gap: "0.375rem", fontSize: "0.8125rem", color: "var(--text-muted)", cursor: "pointer" }}>
                        <input
                            type="checkbox"
                            checked={autoScroll}
                            onChange={(e) => setAutoScroll(e.target.checked)}
                            style={{ accentColor: "var(--brand-accent)" }}
                        />
                        自动滚动
                    </label>
                </div>
                <div className="bsm-log-window" ref={logWindowRef}>
                    {logs.length === 0 ? (
                        <div className="bsm-log-empty">暂无日志。等待扫描任务启动…</div>
                    ) : (
                        logs.map((line, i) => (
                            <div key={i} className="bsm-log-line">
                                <span className="bsm-log-ts">{line.ts}</span>
                                <span
                                    className="bsm-log-level"
                                    style={{ color: LEVEL_COLORS[line.level] ?? "var(--text-secondary)" }}
                                >
                                    {line.level}
                                </span>
                                <span className="bsm-log-msg">{line.msg}</span>
                            </div>
                        ))
                    )}
                </div>
                <div style={{ display: "flex", justifyContent: "flex-start", gap: "0.5rem", flexWrap: "wrap", marginTop: "0.75rem" }}>
                    <button
                        type="button"
                        className="bsm-btn bsm-btn-outline"
                        onClick={handleTriggerScan}
                        disabled={!cron?.is_running || triggeringScan}
                    >
                        {triggeringScan ? "触发中…" : "立即扫描"}
                    </button>
                    <button
                        type="button"
                        className="bsm-btn bsm-btn-outline"
                        onClick={handleRestartCron}
                        disabled={restartingCron}
                    >
                        {restartingCron ? "重启中…" : "重启 Cron"}
                    </button>
                </div>
            </div>

        </Shell>
    );
}
