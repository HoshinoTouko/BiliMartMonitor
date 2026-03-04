"use client";
import { useEffect, useState } from "react";
import Shell from "@/components/Shell";
import { useAuth } from "@/contexts/AuthContext";
import { apiGet, apiPost, apiPut } from "@/lib/api";

interface UserNotificationSettings {
    username: string;
    notify_enabled: boolean;
    keywords: string[];
    telegram_ids: string[];
    bot_id?: string;
}

const RULES = [
    "1. 在“监听关键词”里填写你要监控的关键词或正则。",
    "2. 关闭“监听开关”后，当前用户将不再接收定向通知。",
    "3. 可以同时配置多个 Telegram ID，命中时会全部发送。",
];

function parseLines(value: string): string[] {
    return value
        .split(/[\n,，]/)
        .map((item) => item.trim())
        .filter(Boolean);
}

export default function NotificationsPage() {
    const { currentUser, isLoading } = useAuth();
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [testing, setTesting] = useState(false);
    const [saveMsg, setSaveMsg] = useState("");
    const [testMsg, setTestMsg] = useState("");
    const [notifyEnabled, setNotifyEnabled] = useState(true);
    const [keywordsText, setKeywordsText] = useState("");
    const [telegramIdsText, setTelegramIdsText] = useState("");
    const [bindCode, setBindCode] = useState("");
    const [bindMsg, setBindMsg] = useState("");
    const [refreshing, setRefreshing] = useState(false);
    const [botId, setBotId] = useState("");

    useEffect(() => {
        if (isLoading) return;
        if (!currentUser) {
            setLoading(false);
            return;
        }

        const loadConfig = async () => {
            try {
                const data = await apiGet<UserNotificationSettings>(`/api/settings/user-notifications?username=${encodeURIComponent(currentUser)}`);
                setNotifyEnabled(Boolean(data.notify_enabled));
                setKeywordsText((data.keywords ?? []).join("\n"));
                setTelegramIdsText((data.telegram_ids ?? []).join("\n"));
                setBotId((data.bot_id ?? "").replace(/^@/, ""));
            } catch {
                // ignore
            } finally {
                setLoading(false);
            }
        };

        loadConfig();
    }, [currentUser, isLoading]);

    const handleSave = async () => {
        if (!currentUser) return;
        setSaving(true);
        setSaveMsg("");
        try {
            const data = await apiPut("/api/settings/user-notifications", {
                username: currentUser,
                notify_enabled: notifyEnabled,
                keywords: parseLines(keywordsText),
                telegram_ids: parseLines(telegramIdsText),
            }) as { ok?: boolean, error?: string };
            if (data.ok) {
                setSaveMsg("✅ 已保存");
            } else {
                setSaveMsg(`❌ ${data.error ?? "保存失败"}`);
            }
        } catch (e) {
            setSaveMsg(`❌ ${e instanceof Error ? e.message : "网络错误"}`);
        } finally {
            setSaving(false);
            window.setTimeout(() => setSaveMsg(""), 4000);
        }
    };

    const handleTestPush = async () => {
        if (!currentUser) return;
        setTesting(true);
        setTestMsg("");
        try {
            const data = await apiPost("/api/settings/user-notifications/test", {
                username: currentUser,
                keywords: parseLines(keywordsText),
                telegram_ids: parseLines(telegramIdsText),
            }) as { ok?: boolean, error?: string, failed_chat_ids?: string[], sent?: number };
            if (data.ok) {
                const failed = Array.isArray(data.failed_chat_ids) && data.failed_chat_ids.length > 0
                    ? `，失败 ${data.failed_chat_ids.length} 个`
                    : "";
                setTestMsg(`✅ 已发送 ${data.sent} 个测试通知${failed}`);
            } else {
                setTestMsg(`❌ ${data.error ?? "测试发送失败"}`);
            }
        } catch (e) {
            setTestMsg(`❌ ${e instanceof Error ? e.message : "网络错误"}`);
        } finally {
            setTesting(false);
            window.setTimeout(() => setTestMsg(""), 4000);
        }
    };

    const handleGetBindCode = async () => {
        if (!currentUser) return;
        try {
            const data = await apiPost<{ ok: boolean; code: string }>("/api/account/telegram/bind-code", {});
            if (data.ok) {
                setBindCode(data.code);
                setBindMsg("");
            }
        } catch {
            setSaveMsg("❌ 获取绑定码失败");
        }
    };

    const handleCopyBindCommand = async () => {
        if (!bindCode) return;
        const command = `/bind ${bindCode}`;
        try {
            await navigator.clipboard.writeText(command);
            setBindMsg("✅ 已复制绑定命令（10分钟内有效）");
        } catch {
            setBindMsg("❌ 复制失败，请手动复制");
        } finally {
            window.setTimeout(() => setBindMsg(""), 4000);
        }
    };

    const handleManualRefresh = async () => {
        setRefreshing(true);
        try {
            const data = await apiPost<{ ok: boolean }>("/api/account/telegram/refresh", {});
            if (data.ok) {
                const previousIds = (parseLines(telegramIdsText) ?? []).join("\n");
                let latestIds = previousIds;

                for (let attempt = 0; attempt < 6; attempt += 1) {
                    if (attempt > 0) {
                        await new Promise<void>((resolve) => {
                            window.setTimeout(resolve, 1000);
                        });
                    }

                    const updated = await apiGet<UserNotificationSettings>(`/api/settings/user-notifications?username=${encodeURIComponent(currentUser!)}`);
                    latestIds = (updated.telegram_ids ?? []).join("\n");
                    setTelegramIdsText(latestIds);

                    if (latestIds !== previousIds) {
                        break;
                    }
                }

                setTestMsg(latestIds !== previousIds ? "✅ 已同步 Telegram 绑定状态" : "✅ 已触发机器人刷新");
            }
        } catch {
            setTestMsg("❌ 刷新失败");
        } finally {
            setRefreshing(false);
            window.setTimeout(() => setTestMsg(""), 4000);
        }
    };

    return (
        <Shell title="通知中心">
            <p className="bsm-text-secondary" style={{ marginBottom: "1.25rem" }}>
                配置你自己的监听关键词、Telegram ID 和接收开关。
            </p>

            <div className="bsm-section">
                <div className="bsm-section-title">个人通知设置</div>
                {loading ? (
                    <div className="bsm-text-muted">加载中…</div>
                ) : !currentUser ? (
                    <div className="bsm-text-muted">请先登录后再配置通知。</div>
                ) : (
                    <div className="bsm-settings-form">
                        <div className="bsm-settings-row">
                            <label className="bsm-settings-label">监听开关</label>
                            <div className="bsm-settings-control">
                                <label className="bsm-settings-radio">
                                    <input
                                        type="checkbox"
                                        checked={notifyEnabled}
                                        onChange={(e) => setNotifyEnabled(e.target.checked)}
                                    />
                                    <span>{notifyEnabled ? "已开启" : "已关闭"}</span>
                                </label>
                            </div>
                        </div>

                        <div className="bsm-settings-row">
                            <label className="bsm-settings-label bsm-settings-label-top">
                                监听关键词
                            </label>
                            <div className="bsm-settings-control">
                                <textarea
                                    className="bsm-input bsm-notification-textarea"
                                    placeholder={"每行一个关键词，也支持逗号分隔\n例如：\n洛琪希\n艾莉丝"}
                                    value={keywordsText}
                                    onChange={(e) => setKeywordsText(e.target.value)}
                                />
                            </div>
                        </div>

                        <div className="bsm-settings-row">
                            <label className="bsm-settings-label bsm-settings-label-top">
                                Telegram ID
                            </label>
                            <div className="bsm-settings-control">
                                <textarea
                                    className="bsm-input bsm-notification-textarea"
                                    placeholder={"每行一个 TG ID，也支持逗号分隔"}
                                    value={telegramIdsText}
                                    onChange={(e) => setTelegramIdsText(e.target.value)}
                                />
                            </div>
                        </div>

                        <div className="bsm-settings-row bsm-notification-save-row">
                            <div className="bsm-settings-spacer" />
                            <div className="bsm-settings-control bsm-notification-actions">
                                <button
                                    className="bsm-btn bsm-btn-primary"
                                    onClick={handleSave}
                                    disabled={saving}
                                >
                                    {saving ? "保存中…" : "保存监听关键词 / Telegram ID"}
                                </button>
                                {saveMsg && (
                                    <span className={`bsm-notification-status ${saveMsg.startsWith("✅") ? "success" : "error"}`}>
                                        {saveMsg}
                                    </span>
                                )}
                            </div>
                        </div>

                        <div className="bsm-settings-row">
                            <label className="bsm-settings-label">Telegram 绑定</label>
                            <div className="bsm-settings-control bsm-notification-actions">
                                <button className="bsm-btn bsm-btn-accent" onClick={handleGetBindCode}>
                                    {bindCode ? `绑定码: ${bindCode}` : "生成绑定码"}
                                </button>
                                {bindCode && (
                                    <>
                                        <button
                                            className="bsm-btn bsm-btn-primary"
                                            onClick={handleCopyBindCommand}
                                            type="button"
                                            title="复制 Telegram 绑定命令"
                                        >
                                            复制绑定命令
                                        </button>
                                        <span className="bsm-text-secondary bsm-notification-inline-note">
                                            请向机器人发送指令：<code>/bind {bindCode}</code>（10分钟内有效）
                                        </span>
                                    </>
                                )}
                                <button
                                    className="bsm-btn bsm-btn-primary"
                                    onClick={handleManualRefresh}
                                    disabled={refreshing}
                                    title="点击立即同步 Telegram 绑定状态"
                                >
                                    {refreshing ? "同步中…" : "同步/刷新机器人"}
                                </button>
                                {bindMsg && (
                                    <span className={`bsm-notification-status ${bindMsg.startsWith("✅") ? "success" : "error"}`}>
                                        {bindMsg}
                                    </span>
                                )}
                            </div>
                        </div>

                        <div className="bsm-settings-row">
                            <label className="bsm-settings-label">测试推送</label>
                            <div className="bsm-settings-control bsm-notification-actions">
                                <button
                                    className="bsm-btn bsm-btn-accent"
                                    onClick={handleTestPush}
                                    disabled={testing}
                                >
                                    {testing ? "测试中…" : "发送测试消息"}
                                </button>
                                {botId && (
                                    <a
                                        className="bsm-btn bsm-btn-primary"
                                        href={`https://t.me/${botId}`}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        style={{ textDecoration: "none" }}
                                    >
                                        跳转 Bot ↗
                                    </a>
                                )}
                                {testMsg && (
                                    <span className={`bsm-notification-status ${testMsg.startsWith("✅") ? "success" : "error"}`}>
                                        {testMsg}
                                    </span>
                                )}
                            </div>
                        </div>
                    </div>
                )}
            </div>

            <div className="bsm-section">
                <div className="bsm-section-title">规则说明</div>
                <div
                    className="bsm-notification-rules"
                >
                    {RULES.map((rule) => (
                        <p key={rule} className="bsm-text-secondary bsm-mt-1 bsm-notification-rule-text">
                            {rule}
                        </p>
                    ))}
                </div>
            </div>
        </Shell>
    );
}
