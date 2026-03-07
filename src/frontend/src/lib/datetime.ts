export type ApiDateInput = string | number | null | undefined;

function parseNumericEpoch(value: number): Date | null {
    if (!Number.isFinite(value)) return null;
    // 10-digit values are usually seconds; 13-digit are milliseconds.
    const ms = Math.abs(value) < 1e12 ? value * 1000 : value;
    const d = new Date(ms);
    return Number.isNaN(d.getTime()) ? null : d;
}

export function parseApiDate(input: ApiDateInput): Date | null {
    if (input == null) return null;
    if (typeof input === "number") return parseNumericEpoch(input);

    const raw = String(input).trim();
    if (!raw) return null;

    if (/^\d+$/.test(raw)) {
        return parseNumericEpoch(Number(raw));
    }

    const normalized = raw.includes("T") ? raw : raw.replace(" ", "T");
    const d = new Date(normalized);
    return Number.isNaN(d.getTime()) ? null : d;
}

export function timeAgo(input: ApiDateInput, emptyText: string = "—"): string {
    const date = parseApiDate(input);
    if (!date) return emptyText;
    const diff = Math.floor((Date.now() - date.getTime()) / 1000);
    if (diff < 0) return "刚刚";
    if (diff < 60) return `${diff} 秒前`;
    if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`;
    if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`;
    return `${Math.floor(diff / 86400)} 天前`;
}

export function formatMonthDayTime(input: ApiDateInput, emptyText: string = "—"): string {
    const d = parseApiDate(input);
    if (!d) return emptyText;
    return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}
