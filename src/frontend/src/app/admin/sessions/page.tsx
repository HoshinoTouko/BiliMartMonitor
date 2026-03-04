"use client";
import React, { useEffect, useState, useCallback } from "react";
import Shell from "@/components/Shell";
import { apiGet, apiDelete } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";

interface Session {
    login_username: string;
    created_by: string;
    status: string;
    fetch_count: string;
    login_at: string;
    last_success_fetch_at: string;
}

interface QrState {
    loginKey: string;
    loginUrl: string;
    qrImage: string;
    qrStatus: string;
    qrStatusType: "info" | "success" | "error";
}

export default function SessionManagementPage() {
    const { currentUser } = useAuth();
    const [sessions, setSessions] = useState<Session[]>([]);
    const [sessionsLoading, setSessionsLoading] = useState(true);
    const [sessionsError, setSessionsError] = useState("");

    const [qr, setQr] = useState<QrState>({
        loginKey: "",
        loginUrl: "",
        qrImage: "",
        qrStatus: "点击「生成二维码登录」开始，系统会自动读取 B 站用户名。",
        qrStatusType: "info",
    });
    const [qrLoading, setQrLoading] = useState(false);

    const loadSessions = useCallback(async () => {
        setSessionsLoading(true);
        setSessionsError("");
        try {
            const data = await apiGet<{ sessions: Session[] }>("/api/admin/sessions");
            setSessions(data.sessions || []);
        } catch {
            setSessionsError("加载失败，请稍后重试。");
        } finally {
            setSessionsLoading(false);
        }
    }, []);

    useEffect(() => { loadSessions(); }, [loadSessions]);

    const deleteSession = async (username: string) => {
        if (!confirm(`确定要登出会话「${username}」吗？`)) return;
        try {
            await apiDelete(`/api/admin/sessions/${encodeURIComponent(username)}`);
            await loadSessions();
        } catch {
            alert("登出失败，请稍后重试。");
        }
    };

    const generateQr = async () => {
        setQrLoading(true);
        setQr((prev) => ({ ...prev, qrStatus: "正在生成二维码...", qrStatusType: "info" }));
        try {
            const data = await apiGet<{ login_key: string; login_url: string; qr_image: string }>(
                "/api/admin/qr/create"
            );
            if (data.login_key && data.login_url) {
                setQr({
                    loginKey: data.login_key,
                    loginUrl: data.login_url,
                    qrImage: data.qr_image,
                    qrStatus: "二维码已生成，请扫码后点击「检查登录状态」。",
                    qrStatusType: "info",
                });
            } else {
                setQr((prev) => ({ ...prev, qrStatus: "生成二维码失败，请稍后重试。", qrStatusType: "error" }));
            }
        } catch {
            setQr((prev) => ({ ...prev, qrStatus: "生成失败，网络错误。", qrStatusType: "error" }));
        } finally {
            setQrLoading(false);
        }
    };

    const pollQr = async () => {
        if (!qr.loginKey) {
            setQr((prev) => ({ ...prev, qrStatus: "请先生成二维码。", qrStatusType: "error" }));
            return;
        }
        setQrLoading(true);
        setQr((prev) => ({ ...prev, qrStatus: "正在检查登录状态...", qrStatusType: "info" }));
        try {
            const data = await (await import("@/lib/api")).apiPost<{
                ok: string;
                login_username: string;
            }>("/api/admin/qr/poll", {
                login_key: qr.loginKey,
                created_by: currentUser || "",
            });
            if (data.ok) {
                setQr({
                    loginKey: "",
                    loginUrl: "",
                    qrImage: "",
                    qrStatus: `登录成功，已保存 Bili 会话：${data.login_username}`,
                    qrStatusType: "success",
                });
                await loadSessions();
            } else {
                setQr((prev) => ({
                    ...prev,
                    qrStatus: "尚未确认或未取到 B 站用户名，请在 App 中确认后再检查。",
                    qrStatusType: "info",
                }));
            }
        } catch {
            setQr((prev) => ({ ...prev, qrStatus: "检查失败，网络错误。", qrStatusType: "error" }));
        } finally {
            setQrLoading(false);
        }
    };

    return (
        <Shell title="Bili 会话管理" adminOnly>
            <p className="bsm-text-secondary">
                这里展示会话用户名、登录时间、获取条目计数和上次成功获取时间。<br />
                点击「登出 Session」会直接删除该会话，不包含 cookie。
            </p>

            {/* QR Login Section */}
            <div className="bsm-qr-section bsm-mt-3">
                <p className="bsm-qr-title">二维码登录</p>
                <p className="bsm-text-muted">会话名会自动使用登录成功后的 B 站用户名。</p>

                <div className="bsm-qr-btn-row">
                    <button
                        id="bsm-qr-btn-create"
                        className="bsm-btn bsm-btn-accent"
                        onClick={generateQr}
                        disabled={qrLoading}
                    >
                        {qrLoading ? "处理中..." : "生成二维码登录"}
                    </button>
                    <button
                        id="bsm-qr-btn-poll"
                        className="bsm-btn bsm-btn-outline"
                        onClick={pollQr}
                        disabled={qrLoading || !qr.loginKey}
                    >
                        检查登录状态
                    </button>
                    <button
                        id="bsm-qr-btn-reload"
                        className="bsm-btn bsm-btn-outline"
                        onClick={loadSessions}
                    >
                        刷新会话
                    </button>
                </div>

                <p
                    id="bsm-qr-status"
                    className={`bsm-status ${qr.qrStatusType}`}
                >
                    {qr.qrStatus}
                </p>

                {qr.qrImage && (
                    <div id="bsm-qr-box" className="bsm-qr-img-box">
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img
                            id="bsm-qr-img"
                            src={qr.qrImage}
                            alt="Bilibili 登录二维码"
                            className="bsm-qr-img"
                        />
                        <a
                            id="bsm-qr-link"
                            href={qr.loginUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="bsm-link bsm-text-small"
                        >
                            打开 B 站登录二维码
                        </a>
                    </div>
                )}
            </div>

            {/* Session List */}
            <div id="bsm-session-list">
                {sessionsLoading ? (
                    <p className="bsm-text-secondary">正在加载会话...</p>
                ) : sessionsError ? (
                    <p className="bsm-status error">{sessionsError}</p>
                ) : sessions.length === 0 ? (
                    <div className="bsm-empty">当前暂无会话。</div>
                ) : (
                    <div className="bsm-sessions-list">
                        {sessions.map((s) => (
                            <div key={s.login_username} className="bsm-session-card">
                                <div className="bsm-session-header">
                                    <span className="bsm-session-name">{s.login_username}</span>
                                    <span className="bsm-session-status">{s.status}</span>
                                </div>
                                <div className="bsm-session-meta">
                                    <span>创建人：{s.created_by}</span>
                                    <span>登录时间：{s.login_at}</span>
                                    <span>获取条目：{s.fetch_count}</span>
                                    <span>上次成功：{s.last_success_fetch_at}</span>
                                </div>
                                <div>
                                    <button
                                        className="bsm-btn bsm-btn-danger bsm-btn-sm"
                                        onClick={() => deleteSession(s.login_username)}
                                        data-login-username={s.login_username}
                                    >
                                        登出 Session
                                    </button>
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </Shell>
    );
}
