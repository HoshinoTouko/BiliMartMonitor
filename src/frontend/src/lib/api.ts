/**
 * BSM API client helpers.
 * In Next.js dev mode, all /api/* requests are proxied to http://localhost:8000 via next.config.ts rewrites.
 */

const SAME_DOMAIN_HOSTS = ["localhost", "127.0.0.1", "0.0.0.0", "::1"];
const API_TIMEOUT_MS = 30_000;

export function authHeaders(extra: HeadersInit = {}): HeadersInit {
    return new Headers(extra);
}

/** Compute the base URL for API calls (Next.js proxy handles it in dev). */
function apiBase(): string {
    if (typeof window === "undefined") return "";
    const { hostname, port } = window.location;
    if (port === "3000" && SAME_DOMAIN_HOSTS.includes(hostname)) {
        // In Next.js dev, the rewrite proxy handles /api/* — so we use same origin.
        return "";
    }
    return "";
}

import { toast } from "react-hot-toast";

// --------------------------------------------------------------------------
// XHR helpers
// --------------------------------------------------------------------------

/** Handle fetch responses, intercepting 401 Unauthorized. */
async function handleResponse<T>(resp: Response, path: string): Promise<T> {
    if (resp.status === 401) {
        // Skip global 401 handling for auth bootstrap/login checks.
        if (path.includes("/api/auth/login") || path.includes("/api/auth/me")) {
            const d = await resp.json().catch(() => ({}));
            throw new Error(d.error || "用户名或密码错误");
        }

        console.log("BSM API: 401 Unauthorized detected at", typeof window !== "undefined" ? window.location.href : "SSR");
        if (typeof window !== "undefined") {
            console.log("BSM API: Triggering Toast and cleanup. toast object:", !!toast);
            toast.error("会话已过期，5秒后跳回登录界面", { duration: 5000 });
            localStorage.removeItem("bsm_current_user");
            localStorage.removeItem("bsm_role");
            setTimeout(() => {
                window.location.href = "/";
            }, 5000);
        }
        throw new Error("Unauthorized");
    }
    if (!resp.ok) {
        const d = await resp.json().catch(() => ({}));
        throw new Error(d.detail || d.error || `HTTP ${resp.status}`);
    }
    return resp.json() as Promise<T>;
}

async function fetchWithTimeout(input: RequestInfo | URL, init: RequestInit): Promise<Response> {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), API_TIMEOUT_MS);
    try {
        return await fetch(input, {
            ...init,
            signal: controller.signal,
        });
    } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") {
            throw new Error(`请求超时（${API_TIMEOUT_MS / 1000}秒）`);
        }
        throw error;
    } finally {
        clearTimeout(timeoutId);
    }
}

export async function apiGet<T = unknown>(path: string): Promise<T> {
    const fullPath = apiBase() + path;
    const resp = await fetchWithTimeout(fullPath, {
        method: "GET",
        credentials: "include",
        headers: authHeaders({ Accept: "application/json" }),
    });
    return handleResponse<T>(resp, path);
}

export async function apiPost<T = unknown>(path: string, body: unknown): Promise<T> {
    const fullPath = apiBase() + path;
    const resp = await fetchWithTimeout(fullPath, {
        method: "POST",
        credentials: "include",
        headers: authHeaders({ "Content-Type": "application/json", Accept: "application/json" }),
        body: JSON.stringify(body),
    });
    return handleResponse<T>(resp, path);
}

export async function apiPut<T = unknown>(path: string, body: unknown): Promise<T> {
    const fullPath = apiBase() + path;
    const resp = await fetchWithTimeout(fullPath, {
        method: "PUT",
        credentials: "include",
        headers: authHeaders({ "Content-Type": "application/json", Accept: "application/json" }),
        body: JSON.stringify(body),
    });
    return handleResponse<T>(resp, path);
}

export async function apiDelete<T = unknown>(path: string): Promise<T> {
    const fullPath = apiBase() + path;
    const resp = await fetchWithTimeout(fullPath, {
        method: "DELETE",
        credentials: "include",
        headers: authHeaders({ Accept: "application/json" }),
    });
    return handleResponse<T>(resp, path);
}

// --------------------------------------------------------------------------
// WebSocket channel (same as original BsmWsChannel JS)
// --------------------------------------------------------------------------

type PendingResolve = (data: Record<string, unknown>) => void;

export class BsmWsChannel {
    private _ws: WebSocket | null = null;
    private _pending: Record<number, PendingResolve> = {};
    private _id = 0;
    private _path: string;

    constructor(path: string) {
        this._path = path;
    }

    private _url(): string {
        if (typeof window === "undefined") return "";
        const { hostname, port, protocol } = window.location;
        const wsProto = protocol === "https:" ? "wss:" : "ws:";
        // In dev (port 3000), the Next.js proxy doesn't handle WS rewrites by default.
        // We connect directly to the FastAPI port.
        if (port === "3000" && SAME_DOMAIN_HOSTS.includes(hostname)) {
            return `${wsProto}//${hostname}:8000${this._path}`;
        }
        return `${wsProto}//${window.location.host}${this._path}`;
    }

    private _socket(): WebSocket {
        if (this._ws && (this._ws.readyState === 0 || this._ws.readyState === 1)) {
            return this._ws;
        }
        const ws = new WebSocket(this._url());
        ws.onmessage = (e) => {
            let d: Record<string, unknown>;
            try {
                d = JSON.parse(e.data);
            } catch {
                return;
            }
            const id = d._id as number | undefined;
            if (id != null && this._pending[id]) {
                this._pending[id](d);
                delete this._pending[id];
            }
        };
        ws.onerror = () => { this._ws = null; };
        ws.onclose = () => { this._ws = null; };
        this._ws = ws;
        return ws;
    }

    send(msg: Record<string, unknown>): Promise<Record<string, unknown>> {
        return new Promise((resolve) => {
            const id = ++this._id;
            msg._id = id;
            this._pending[id] = resolve;
            const ws = this._socket();
            if (ws.readyState === 1) {
                ws.send(JSON.stringify(msg));
            } else {
                ws.onopen = () => ws.send(JSON.stringify(msg));
            }
        });
    }
}
