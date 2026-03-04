"use client";
import { useEffect, useState, type Dispatch, type SetStateAction } from "react";
import { apiDelete, apiGet, apiPost, apiPut } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";

interface ManagedUser {
    username: string;
    display_name: string;
    role: string;
    roles: string[];
    status: string;
    notify_enabled: boolean;
    keywords: string[];
    telegram_ids: string[];
}

interface UserFormState {
    username: string;
    display_name: string;
    password: string;
    roles: string;
    status: string;
}

const EMPTY_FORM: UserFormState = {
    username: "",
    display_name: "",
    password: "",
    roles: "user",
    status: "active",
};

function normalizeRoles(value: string): string[] {
    return value === "admin" ? ["admin"] : ["user"];
}

export default function AccountManagementPanel() {
    const { role, currentUser } = useAuth();
    const [users, setUsers] = useState<ManagedUser[]>([]);
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [message, setMessage] = useState("");
    const [editForm, setEditForm] = useState<UserFormState>(EMPTY_FORM);
    const [originalUsername, setOriginalUsername] = useState("");
    const [createForm, setCreateForm] = useState<UserFormState>(EMPTY_FORM);
    const [createOpen, setCreateOpen] = useState(false);

    const loadUsers = async () => {
        setLoading(true);
        try {
            const data = await apiGet<{ ok: boolean; users: ManagedUser[] }>("/api/account/users");
            if (data.ok) {
                setUsers(data.users);
            }
        } catch {
            setMessage("❌ 加载账户失败");
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        if (role === "admin") {
            loadUsers();
        } else {
            setLoading(false);
        }
    }, [role]);

    const saveForm = async (form: UserFormState, mode: "create" | "edit") => {
        if (!form.username.trim()) {
            setMessage("❌ 用户名不能为空");
            return false;
        }

        setSaving(true);
        setMessage("");
        try {
            let data;
            if (mode === "create") {
                data = await apiPost<{ ok?: boolean; error?: string }>("/api/account/users", {
                    username: form.username.trim(),
                    display_name: form.display_name.trim(),
                    password: form.password,
                    roles: normalizeRoles(form.roles),
                    status: form.status,
                });
            } else {
                data = await apiPut<{ ok?: boolean; error?: string }>(`/api/account/users/${encodeURIComponent(originalUsername)}`, {
                    username: form.username.trim(),
                    display_name: form.display_name.trim(),
                    password: form.password,
                    roles: normalizeRoles(form.roles),
                    status: form.status,
                });
            }

            if (data.ok) {
                setMessage(mode === "create" ? "✅ 账户已创建" : "✅ 账户已保存");
                await loadUsers();
                if (mode === "edit") {
                    setOriginalUsername(form.username.trim());
                }
                return true;
            }
            setMessage(`❌ ${data.error || "保存失败"}`);
            return false;
        } catch {
            setMessage("❌ 网络错误");
            return false;
        } finally {
            setSaving(false);
        }
    };

    const handleCreate = async () => {
        const ok = await saveForm(createForm, "create");
        if (ok) {
            setCreateForm(EMPTY_FORM);
            setCreateOpen(false);
        }
    };

    const handleSaveEdit = async () => {
        const ok = await saveForm(editForm, "edit");
        if (ok) {
            setEditForm(EMPTY_FORM);
        }
    };

    const handleEdit = (user: ManagedUser) => {
        setOriginalUsername(user.username);
        setEditForm({
            username: user.username,
            display_name: user.display_name,
            password: "",
            roles: (user.roles || []).includes("admin") ? "admin" : "user",
            status: user.status,
        });
        setMessage("");
    };

    const handleDelete = async (username: string) => {
        if (!window.confirm(`确认删除账户 ${username} 吗？`)) {
            return;
        }
        try {
            const data = await apiDelete<{ ok?: boolean; error?: string }>(`/api/account/users/${encodeURIComponent(username)}`);
            if (data.ok) {
                setMessage("✅ 账户已删除");
                await loadUsers();
                if (editForm.username === username) {
                    setEditForm(EMPTY_FORM);
                }
            } else {
                setMessage(`❌ ${data.error || "删除失败"}`);
            }
        } catch {
            setMessage("❌ 删除失败");
        }
    };

    const renderForm = (
        form: UserFormState,
        setForm: Dispatch<SetStateAction<UserFormState>>,
        submitText: string,
        onSubmit: () => void,
        passwordPlaceholder: string,
    ) => (
        <div className="bsm-settings-form">
            <div className="bsm-settings-row">
                <label className="bsm-settings-label">用户名</label>
                <div className="bsm-settings-control">
                    <input
                        className="bsm-input"
                        style={{ width: "100%", maxWidth: "320px" }}
                        value={form.username}
                        onChange={(e) => setForm((prev) => ({ ...prev, username: e.target.value }))}
                    />
                </div>
            </div>
            <div className="bsm-settings-row">
                <label className="bsm-settings-label">显示名</label>
                <div className="bsm-settings-control">
                    <input
                        className="bsm-input"
                        style={{ width: "100%", maxWidth: "320px" }}
                        value={form.display_name}
                        onChange={(e) => setForm((prev) => ({ ...prev, display_name: e.target.value }))}
                    />
                </div>
            </div>
            <div className="bsm-settings-row">
                <label className="bsm-settings-label">密码</label>
                <div className="bsm-settings-control">
                    <input
                        type="password"
                        className="bsm-input"
                        style={{ width: "100%", maxWidth: "320px" }}
                        placeholder={passwordPlaceholder}
                        value={form.password}
                        onChange={(e) => setForm((prev) => ({ ...prev, password: e.target.value }))}
                    />
                </div>
            </div>
            <div className="bsm-settings-row">
                <label className="bsm-settings-label">角色</label>
                <div className="bsm-settings-control">
                    <select
                        className="bsm-input"
                        style={{ width: "100%", maxWidth: "180px" }}
                        value={form.roles}
                        onChange={(e) => setForm((prev) => ({ ...prev, roles: e.target.value }))}
                    >
                        <option value="user">user</option>
                        <option value="admin">admin</option>
                    </select>
                </div>
            </div>
            <div className="bsm-settings-row">
                <label className="bsm-settings-label">状态</label>
                <div className="bsm-settings-control">
                    <select
                        className="bsm-input"
                        style={{ width: "100%", maxWidth: "180px" }}
                        value={form.status}
                        onChange={(e) => setForm((prev) => ({ ...prev, status: e.target.value }))}
                    >
                        <option value="active">active</option>
                        <option value="disabled">disabled</option>
                    </select>
                </div>
            </div>
            <div className="bsm-settings-row">
                <div className="bsm-settings-spacer" />
                <div className="bsm-settings-control bsm-settings-actions">
                    <button className="bsm-btn bsm-btn-accent" onClick={onSubmit} disabled={saving}>
                        {saving ? "保存中…" : submitText}
                    </button>
                </div>
            </div>
        </div>
    );

    if (role !== "admin") {
        return null;
    }

    return (
        <div className="bsm-section">
            <p className="bsm-text-secondary">
                管理员可查看全部账户。你的当前账户 <strong>{currentUser || "—"}</strong> 也会出现在下方列表中。
            </p>

            <div
                style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    gap: "1rem",
                    flexWrap: "wrap",
                    marginBottom: "1rem",
                }}
            >
                <div className="bsm-section-title" style={{ marginBottom: 0 }}>账户管理</div>
                <button
                    className="bsm-btn bsm-btn-accent"
                    onClick={() => {
                        setCreateForm(EMPTY_FORM);
                        setCreateOpen(true);
                        setMessage("");
                    }}
                >
                    新建账户
                </button>
            </div>

            {loading ? (
                <div className="bsm-text-muted">加载中…</div>
            ) : users.length === 0 ? (
                <div className="bsm-text-muted">暂无账户。</div>
            ) : (
                <div style={{ display: "grid", gap: "0.85rem" }}>
                    {users.map((user) => (
                        <div
                            key={user.username}
                            style={{
                                border: "1px solid var(--brand-border)",
                                borderRadius: "var(--radius-md)",
                                padding: "1rem",
                                background: "rgba(255,255,255,0.02)",
                            }}
                        >
                            <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap" }}>
                                <div>
                                    <div style={{ fontWeight: 700 }}>{user.display_name || user.username}</div>
                                    <div className="bsm-text-muted" style={{ fontSize: "0.875rem" }}>
                                        {user.username} | {user.role} | {user.status}
                                    </div>
                                </div>
                                <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                                    <button className="bsm-btn bsm-btn-primary" onClick={() => handleEdit(user)}>
                                        编辑
                                    </button>
                                    {user.username !== currentUser && (
                                        <button className="bsm-btn bsm-btn-danger" onClick={() => handleDelete(user.username)}>
                                            删除
                                        </button>
                                    )}
                                </div>
                            </div>
                        </div>
                    ))}
                </div>
            )}

            {editForm.username && (
                <div className="bsm-section" style={{ marginTop: "1.5rem" }}>
                    <div
                        style={{
                            display: "flex",
                            justifyContent: "space-between",
                            alignItems: "center",
                            gap: "1rem",
                            flexWrap: "wrap",
                            marginBottom: "1rem",
                        }}
                    >
                        <div className="bsm-section-title" style={{ marginBottom: 0 }}>编辑账户</div>
                        <button className="bsm-btn" onClick={() => setEditForm(EMPTY_FORM)} disabled={saving}>
                            关闭
                        </button>
                    </div>
                    {renderForm(editForm, setEditForm, "保存账户", handleSaveEdit, "留空则不修改")}
                </div>
            )}

            {message && (
                <p style={{ fontSize: "0.875rem", color: message.startsWith("✅") ? "var(--brand-accent)" : "#f87171", marginTop: "1rem" }}>
                    {message}
                </p>
            )}

            {createOpen && (
                <div
                    onClick={() => !saving && setCreateOpen(false)}
                    style={{
                        position: "fixed",
                        inset: 0,
                        background: "rgba(7, 10, 18, 0.78)",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        padding: "1.25rem",
                        zIndex: 50,
                    }}
                >
                    <div
                        onClick={(e) => e.stopPropagation()}
                        style={{
                            width: "100%",
                            maxWidth: "720px",
                            border: "1px solid var(--brand-border)",
                            borderRadius: "var(--radius-lg)",
                            background: "rgba(12, 16, 28, 0.98)",
                            padding: "1.25rem",
                            boxShadow: "0 24px 80px rgba(0,0,0,0.35)",
                        }}
                    >
                        <div
                            style={{
                                display: "flex",
                                justifyContent: "space-between",
                                alignItems: "center",
                                gap: "1rem",
                                marginBottom: "1rem",
                            }}
                        >
                            <div>
                                <div className="bsm-section-title" style={{ marginBottom: "0.25rem" }}>新建账户</div>
                                <div className="bsm-text-muted" style={{ fontSize: "0.875rem" }}>
                                    新账户将在保存后立即出现在账户列表中。
                                </div>
                            </div>
                            <button className="bsm-btn" onClick={() => setCreateOpen(false)} disabled={saving}>
                                关闭
                            </button>
                        </div>
                        {renderForm(createForm, setCreateForm, "创建账户", handleCreate, "新用户必填")}
                    </div>
                </div>
            )}
        </div>
    );
}
