"use client";
import React, { useEffect, useRef, useState } from "react";
import { useAuth } from "@/contexts/AuthContext";

declare global {
  interface Window {
    turnstile?: {
      render: (container: string | HTMLElement, options: {
        sitekey: string;
        callback?: (token: string) => void;
        "expired-callback"?: () => void;
        "error-callback"?: () => void;
      }) => string;
      remove?: (widgetId: string) => void;
      reset?: (widgetId: string) => void;
    };
  }
}

interface PublicLoginSettings {
  cloudflare_validation_enabled: boolean;
  cloudflare_turnstile_site_key: string;
}

export default function LoginPage() {
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [status, setStatus] = useState({ msg: "请输入账号密码后登录。", type: "info" });
  const [loading, setLoading] = useState(false);
  const [cfEnabled, setCfEnabled] = useState(false);
  const [cfSiteKey, setCfSiteKey] = useState("");
  const [cfLoaded, setCfLoaded] = useState(false);
  const [cfToken, setCfToken] = useState("");
  const [cfWidgetReady, setCfWidgetReady] = useState(false);
  const widgetHostRef = useRef<HTMLDivElement | null>(null);
  const widgetIdRef = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const loadSettings = async () => {
      try {
        const resp = await fetch("/api/public/login-settings", { cache: "no-store" });
        const data = await resp.json() as PublicLoginSettings;
        if (cancelled) return;
        setCfEnabled(Boolean(data.cloudflare_validation_enabled));
        setCfSiteKey(String(data.cloudflare_turnstile_site_key || ""));
      } catch {
        if (cancelled) return;
        setCfEnabled(false);
        setCfSiteKey("");
      }
    };

    loadSettings();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!cfEnabled || !cfSiteKey) {
      setCfLoaded(false);
      setCfWidgetReady(false);
      setCfToken("");
      return;
    }

    const existing = document.querySelector('script[data-bsm-turnstile="1"]');
    if (existing) {
      setCfLoaded(true);
      return;
    }

    const script = document.createElement("script");
    script.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
    script.async = true;
    script.defer = true;
    script.dataset.bsmTurnstile = "1";
    script.onload = () => setCfLoaded(true);
    script.onerror = () => {
      setStatus({ msg: "Cloudflare 验证脚本加载失败", type: "error" });
      setCfLoaded(false);
    };
    document.head.appendChild(script);

    return () => {
      script.onload = null;
      script.onerror = null;
    };
  }, [cfEnabled, cfSiteKey]);

  useEffect(() => {
    if (!cfEnabled || !cfSiteKey || !cfLoaded || !widgetHostRef.current || !window.turnstile) {
      return;
    }
    if (widgetIdRef.current) {
      return;
    }

    widgetIdRef.current = window.turnstile.render(widgetHostRef.current, {
      sitekey: cfSiteKey,
      callback: (token: string) => {
        setCfToken(token);
        setCfWidgetReady(true);
      },
      "expired-callback": () => {
        setCfToken("");
        setCfWidgetReady(false);
      },
      "error-callback": () => {
        setCfToken("");
        setCfWidgetReady(false);
        setStatus({ msg: "Cloudflare 验证失败，请重试", type: "error" });
      },
    });
    setCfWidgetReady(false);

    return () => {
      if (widgetIdRef.current && window.turnstile?.remove) {
        window.turnstile.remove(widgetIdRef.current);
      }
      widgetIdRef.current = null;
    };
  }, [cfEnabled, cfSiteKey, cfLoaded]);

  const handleLogin = async () => {
    if (loading) return;
    if (cfEnabled) {
      if (!cfSiteKey) {
        setStatus({ msg: "Cloudflare 验证已开启，但 Site Key 未配置", type: "error" });
        return;
      }
      if (!cfToken) {
        setStatus({ msg: "请先完成 Cloudflare 验证", type: "error" });
        return;
      }
    }
    setLoading(true);
    setStatus({ msg: "正在登录...", type: "info" });
    const result = await login(username.trim(), password.trim(), cfToken);
    if (result.ok) {
      setStatus({ msg: "登录成功，正在跳转...", type: "success" });
    } else {
      setStatus({ msg: result.error || "用户名或密码错误", type: "error" });
      setCfToken("");
      setCfWidgetReady(false);
      if (widgetIdRef.current && window.turnstile?.reset) {
        window.turnstile.reset(widgetIdRef.current);
      }
      setLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") handleLogin();
  };

  return (
    <div className="bsm-login-root">
      <div className="bsm-login-box">
        <div className="bsm-login-hero">
          <h1 className="bsm-login-title">BiliMartMonitor</h1>
          <p className="bsm-login-subtitle">Bilibili C2C 市场监控管理系统</p>
        </div>

        <div className="bsm-login-card">
          <h2>登录系统</h2>

          <div className="bsm-form">
            <input
              id="bsm-username"
              className="bsm-input"
              placeholder="用户名"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              onKeyDown={handleKeyDown}
              autoComplete="username"
            />
            <input
              id="bsm-password"
              className="bsm-input"
              placeholder="密码"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onKeyDown={handleKeyDown}
              autoComplete="current-password"
            />

            <p className={`bsm-status ${status.type}`}>{status.msg}</p>

            {cfEnabled && (
              <div className="bsm-login-turnstile-wrap">
                <div ref={widgetHostRef} className="bsm-login-turnstile" />
                {!cfWidgetReady && (
                  <p className="bsm-login-turnstile-note">请先完成 Cloudflare 验证</p>
                )}
              </div>
            )}

            <button
              id="bsm-login-btn"
              className="bsm-btn bsm-btn-primary"
              onClick={handleLogin}
              disabled={loading}
            >
              {loading ? "登录中..." : "登录"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
