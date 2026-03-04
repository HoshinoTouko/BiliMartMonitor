"use client";
import { useEffect, useState } from "react";
import Shell from "@/components/Shell";
import AccountManagementPanel from "@/components/AccountManagementPanel";
import { apiGet, apiPut } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";

interface AccountInfo {
    username: string;
    display_name: string;
    role: string;
    roles: string[];
    status: string;
    notify_enabled: boolean;
    keywords: string[];
    telegram_ids: string[];
}

export default function MyAccountPage() {
    const { currentUser, role, isLoading, logout } = useAuth();
    const [account, setAccount] = useState<AccountInfo | null>(null);
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [currentPassword, setCurrentPassword] = useState("");
    const [newPassword, setNewPassword] = useState("");
    const [confirmPassword, setConfirmPassword] = useState("");
    const [message, setMessage] = useState("");

    useEffect(() => {
        if (isLoading) return;
        if (!currentUser) {
            setLoading(false);
            return;
        }

        const load = async () => {
            try {
                const data = await apiGet<{ ok: boolean; account: AccountInfo }>("/api/account/me");
                if (data.ok) {
                    setAccount(data.account);
                }
            } catch {
                setMessage("❌ 登录状态已失效，请重新登录");
            } finally {
                setLoading(false);
            }
        };

        load();
    }, [currentUser, isLoading]);

    const handleChangePassword = async () => {
        if (!currentPassword || !newPassword) {
            setMessage("❌ 请填写当前密码和新密码");
            return;
        }
        if (newPassword !== confirmPassword) {
            setMessage("❌ 两次输入的新密码不一致");
            return;
        }
        if (newPassword.length < 4) {
            setMessage("❌ 新密码至少需要 4 位");
            return;
        }

        setSaving(true);
        setMessage("");
        try {
            const data = await apiPut<{ ok?: boolean; error?: string }>("/api/account/me/password", {
                current_password: currentPassword,
                new_password: newPassword,
            });
            if (data.ok) {
                setCurrentPassword("");
                setNewPassword("");
                setConfirmPassword("");
                setMessage("✅ 密码已更新，请重新登录");
                window.setTimeout(() => {
                    logout().catch(() => undefined);
                }, 600);
            } else {
                setMessage(`❌ ${data.error || "密码更新失败"}`);
            }
        } catch {
            setMessage("❌ 网络错误");
        } finally {
            setSaving(false);
        }
    };

    return (
        <Shell title="我的账户">
            <p className="bsm-text-secondary">查看当前账户，并修改你自己的登录密码。</p>

            <div className="bsm-section">
                <div className="bsm-section-title">当前账户</div>
                {loading ? (
                    <div className="bsm-text-muted">加载中…</div>
                ) : !currentUser ? (
                    <div className="bsm-text-muted">请先登录。</div>
                ) : (
                    <div className="bsm-info-grid">
                        <div className="bsm-info-row">
                            <span className="bsm-info-key">用户名</span>
                            <span className="bsm-info-value">{account?.username || currentUser}</span>
                        </div>
                        <div className="bsm-info-row">
                            <span className="bsm-info-key">显示名</span>
                            <span className="bsm-info-value">{account?.display_name || "—"}</span>
                        </div>
                        <div className="bsm-info-row">
                            <span className="bsm-info-key">角色</span>
                            <span className="bsm-info-value">{account?.role || role}</span>
                        </div>
                        <div className="bsm-info-row">
                            <span className="bsm-info-key">状态</span>
                            <span className="bsm-info-value">{account?.status || "active"}</span>
                        </div>
                    </div>
                )}
            </div>

            <div className="bsm-section">
                <div className="bsm-section-title">修改密码</div>
                {!currentUser ? (
                    <div className="bsm-text-muted">请先登录后再修改密码。</div>
                ) : (
                    <div className="bsm-settings-form">
                        <div className="bsm-settings-row">
                            <label className="bsm-settings-label">当前密码</label>
                            <div className="bsm-settings-control">
                                <input
                                    type="password"
                                    className="bsm-input"
                                    style={{ width: "100%", maxWidth: "320px" }}
                                    value={currentPassword}
                                    onChange={(e) => setCurrentPassword(e.target.value)}
                                />
                            </div>
                        </div>
                        <div className="bsm-settings-row">
                            <label className="bsm-settings-label">新密码</label>
                            <div className="bsm-settings-control">
                                <input
                                    type="password"
                                    className="bsm-input"
                                    style={{ width: "100%", maxWidth: "320px" }}
                                    value={newPassword}
                                    onChange={(e) => setNewPassword(e.target.value)}
                                />
                            </div>
                        </div>
                        <div className="bsm-settings-row">
                            <label className="bsm-settings-label">确认新密码</label>
                            <div className="bsm-settings-control">
                                <input
                                    type="password"
                                    className="bsm-input"
                                    style={{ width: "100%", maxWidth: "320px" }}
                                    value={confirmPassword}
                                    onChange={(e) => setConfirmPassword(e.target.value)}
                                />
                            </div>
                        </div>
                        <div className="bsm-settings-row">
                            <div className="bsm-settings-spacer" />
                            <div className="bsm-settings-control bsm-settings-actions">
                                <button className="bsm-btn bsm-btn-primary" onClick={handleChangePassword} disabled={saving}>
                                    {saving ? "保存中…" : "更新密码"}
                                </button>
                                {message && (
                                    <span className={`bsm-settings-status ${message.startsWith("✅") ? "success" : "error"}`}>
                                        {message}
                                    </span>
                                )}
                            </div>
                        </div>
                    </div>
                )}
            </div>

            <AccountManagementPanel />
        </Shell>
    );
}
