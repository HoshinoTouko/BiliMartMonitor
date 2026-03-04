"use client";
import { useEffect, useState, useRef } from "react";
import Link from "next/link";
import { useAuth } from "@/contexts/AuthContext";
import AppFooter from "@/components/AppFooter";

interface ShellProps {
    title: React.ReactNode;
    children: React.ReactNode;
    adminOnly?: boolean;
}

const USER_NAV = [
    { label: "用户首页", href: "/app" },
    { label: "市场列表", href: "/market" },
    { label: "通知中心", href: "/notifications" },
    { label: "我的账户", href: "/account" },
];

const ADMIN_NAV = [
    { label: "Bili会话管理", href: "/admin/sessions" },
    { label: "系统设置", href: "/admin/settings" },
];

export default function Shell({ title, children, adminOnly = false }: ShellProps) {
    const { currentUser, role, logout, isLoading } = useAuth();
    const [dropdownOpen, setDropdownOpen] = useState(false);
    const dropdownRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
                setDropdownOpen(false);
            }
        };
        document.addEventListener("mousedown", handleClickOutside);
        return () => document.removeEventListener("mousedown", handleClickOutside);
    }, []);

    if (isLoading) {
        return (
            <div className="bsm-loading">
                <div className="bsm-spinner" />
            </div>
        );
    }

    const navItems = [
        ...(role !== "guest" ? USER_NAV : []),
        ...(role === "admin" ? ADMIN_NAV : []),
    ];

    return (
        <div className="bsm-root">
            {/* Top Navigation */}
            <header className="bsm-header">
                <div className="bsm-header-inner">
                    <div className="bsm-logo">
                        <span className="bsm-logo-icon">⚡</span>
                        BiliMartMonitor
                    </div>
                    <div className="bsm-header-right" ref={dropdownRef}>
                        {currentUser && (
                            <div className="bsm-user-menu-container">
                                <button
                                    className={`bsm-username-tap ${dropdownOpen ? 'active' : ''}`}
                                    onClick={() => setDropdownOpen(!dropdownOpen)}
                                >
                                    <span className="bsm-user-icon">👤</span>
                                    <span className="bsm-username-text">{currentUser}</span>
                                    <span className={`bsm-chevron ${dropdownOpen ? 'up' : ''}`}>▼</span>
                                </button>

                                {dropdownOpen && (
                                    <div className="bsm-user-dropdown">
                                        <div className="bsm-dropdown-header">
                                            <span className="bsm-role-label">当前身份</span>
                                            <span className="bsm-role-badge">{role}</span>
                                        </div>
                                        <div className="bsm-dropdown-divider" />
                                        <button className="bsm-dropdown-item logout" onClick={logout}>
                                            <span className="bsm-item-icon">🚪</span>
                                            退出登录
                                        </button>
                                    </div>
                                )}
                            </div>
                        )}
                    </div>
                </div>

                {/* Navigation bar */}
                {role !== "guest" && (
                    <nav className="bsm-nav">
                        <div className="bsm-nav-inner">
                            {navItems.map((item) => (
                                <Link key={item.href} href={item.href} className="bsm-nav-link">
                                    {item.label}
                                </Link>
                            ))}
                        </div>
                    </nav>
                )}
            </header>

            {/* Main content */}
            <main className="bsm-main">
                <div className="bsm-card">
                    {adminOnly && role !== "admin" && (
                        <div className="bsm-alert bsm-alert-error">
                            该页面仅管理员可访问。
                        </div>
                    )}
                    {role === "guest" && (
                        <div className="bsm-alert bsm-alert-info">
                            请先在{" "}
                            <Link href="/" className="bsm-link">
                                登录页
                            </Link>{" "}
                            输入账号密码进入系统。
                        </div>
                    )}
                    <h1 className="bsm-page-title">{title}</h1>
                    {children}
                </div>
            </main>
            <AppFooter />
        </div>
    );
}
