"use client";
import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import Shell from "@/components/Shell";
import { apiGet } from "@/lib/api";

interface MarketItem {
    id: number;
    category_id?: string | null;
    name: string;
    show_price: string | null;
    show_market_price: string | null;
    uface: string | null;
    uname: string | null;
    img_url: string;
    created_at: string | null;
    updated_at: string | null;
    recent_listed_count?: number;
    publish_status?: number | null;
    sale_status?: number | null;
    bundled_items?: { itemsId: number; name: string; imgUrl?: string; img?: string; pic?: string; image?: string }[];
}

interface Pagination {
    page: number;
    limit: number;
    total_count: number;
    total_pages: number;
}

function timeAgo(dt: string | null): string {
    if (!dt) return "—";
    // If already has timezone info (Z or +xx:xx), parse as-is; otherwise parse as local time
    const date = new Date(dt.replace(" ", "T"));
    const diff = Math.floor((Date.now() - date.getTime()) / 1000);
    if (diff < 0) return "刚刚";
    if (diff < 60) return `${diff} 秒前`;
    if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`;
    if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`;
    return `${Math.floor(diff / 86400)} 天前`;
}

function discountText(showPrice: string | null, showMarketPrice: string | null): string | null {
    const price = Number(showPrice);
    const marketPrice = Number(showMarketPrice);
    if (!Number.isFinite(price) || !Number.isFinite(marketPrice) || marketPrice <= 0 || price <= 0) {
        return null;
    }
    return `${(price / marketPrice * 10).toFixed(1)}折`;
}

function singleSelectLabel(
    options: { value: string; label: string }[],
    value: string,
    fallback: string,
): string {
    return options.find((option) => option.value === value)?.label ?? fallback;
}

export default function MarketFeedPage() {
    const categoryOptions = [
        { id: "2312", label: "手办" },
        { id: "2066", label: "模型" },
        { id: "2331", label: "周边" },
        { id: "2273", label: "3C" },
        { id: "fudai_cate_id", label: "福袋" },
    ];
    const timeOptions = [
        { value: "0", label: "全部时间" },
        { value: "1", label: "1小时内" },
        { value: "24", label: "24小时内" },
        { value: "72", label: "3天内" },
    ];
    const sortOptions = [
        { value: "TIME_DESC", label: "最新上架" },
        { value: "PRICE_ASC", label: "价格升序" },
        { value: "PRICE_DESC", label: "价格降序" },
    ];
    const [items, setItems] = useState<MarketItem[]>([]);
    const [pagination, setPagination] = useState<Pagination>({
        page: 1, limit: 20, total_count: 0, total_pages: 0,
    });
    const [query, setQuery] = useState("");
    const [inputValue, setInputValue] = useState("");
    const [autoRefresh, setAutoRefresh] = useState(false);
    const [timeFilter, setTimeFilter] = useState("0");
    const [sortBy, setSortBy] = useState("TIME_DESC");
    const [categoryFilters, setCategoryFilters] = useState<string[]>([]);
    const [categoryDraftFilters, setCategoryDraftFilters] = useState<string[]>([]);
    const [openFilter, setOpenFilter] = useState<"time" | "sort" | "category" | null>(null);
    const [loading, setLoading] = useState(true);
    const [refreshing, setRefreshing] = useState(false);
    const [countdown, setCountdown] = useState(20);
    const [error, setError] = useState("");
    const [scanInterval, setScanInterval] = useState(20);

    // Fetch scanner settings to get interval
    useEffect(() => {
        const loadSettings = async () => {
            try {
                // Use user-accessible settings endpoint instead of admin-only /api/settings
                const data = await apiGet<{ interval: number }>("/api/account/settings");
                if (data && data.interval) {
                    setScanInterval(data.interval);
                    if (!autoRefresh) setCountdown(data.interval);
                }
            } catch (err) {
                console.warn("Failed to fetch scan interval, using default 20s", err);
            }
        };
        loadSettings();
    }, [autoRefresh]);

    const fetchItems = useCallback(async (
        page: number,
        q: string,
        sort: string,
        time: string,
        categories: string[],
        isSilentRefresh: boolean = false,
    ) => {
        if (!isSilentRefresh) setLoading(true);
        else setRefreshing(true);
        setError("");
        try {
            const params = new URLSearchParams({
                page: String(page),
                limit: "20",
                sort_by: sort,
                time_filter: time
            });
            if (categories.length > 0) {
                params.set("category", categories.join(","));
            }
            let url: string;
            if (q.trim()) {
                params.set("q", q.trim());
                url = `/api/market/items/search?${params.toString()}`;
            } else {
                url = `/api/market/items?${params.toString()}`;
            }
            const data = await apiGet(url) as { items?: MarketItem[], pagination: Pagination };
            setItems(data.items ?? []);
            setPagination(data.pagination);
        } catch (e: unknown) {
            setError(e instanceof Error ? e.message : "加载失败");
        } finally {
            if (!isSilentRefresh) setLoading(false);
            else setRefreshing(false);
        }
    }, []);

    // Auto-refresh interval (1s tick)
    useEffect(() => {
        if (!openFilter) return;
        const close = () => {
            if (openFilter === "category") {
                setCategoryFilters((prev) => {
                    const next = [...categoryDraftFilters].sort();
                    const current = [...prev].sort();
                    if (next.length === current.length && next.every((item, index) => item === current[index])) {
                        return prev;
                    }
                    return categoryDraftFilters;
                });
            }
            setOpenFilter(null);
        };
        window.addEventListener("pointerdown", close);
        return () => window.removeEventListener("pointerdown", close);
    }, [openFilter, categoryDraftFilters]);

    useEffect(() => {
        if (!autoRefresh) {
            setCountdown(scanInterval);
            return;
        }
        const timer = setInterval(() => {
            setCountdown((prev) => {
                if (prev <= 1) {
                    fetchItems(pagination.page, query, sortBy, timeFilter, categoryFilters, true);
                    return scanInterval;
                }
                return prev - 1;
            });
        }, 1000);
        return () => clearInterval(timer);
    }, [autoRefresh, fetchItems, pagination.page, query, sortBy, timeFilter, categoryFilters, scanInterval]);

    // Initial fetch and dependency fetch
    useEffect(() => {
        fetchItems(1, query, sortBy, timeFilter, categoryFilters);
        setPagination((prev) => ({ ...prev, page: 1 }));
        // Reset page to 1 when sort, filter, or query changes
    }, [fetchItems, query, sortBy, timeFilter, categoryFilters]);

    const handleSearch = () => {
        const nextQuery = inputValue;
        if (nextQuery === query) {
            fetchItems(1, query, sortBy, timeFilter, categoryFilters);
            setPagination((prev) => ({ ...prev, page: 1 }));
            return;
        }
        setQuery(nextQuery);
    };

    const handleKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === "Enter") handleSearch();
    };

    const handlePage = (p: number) => {
        fetchItems(p, query, sortBy, timeFilter, categoryFilters);
        setPagination((prev) => ({ ...prev, page: p }));
    };

    const categoryLabel = categoryFilters.length === 0
        ? "全部分类"
        : categoryFilters.length === 1
            ? categoryOptions.find((option) => option.id === categoryFilters[0])?.label ?? "1个分类"
            : `${categoryFilters.length} 个分类`;

    return (
        <Shell title="市场列表">
            {/* Search bar */}
            <div className="bsm-market-search-row">
                <input
                    id="market-search"
                    className="bsm-input"
                    placeholder="搜索商品名称…"
                    value={inputValue}
                    onChange={(e) => setInputValue(e.target.value)}
                    onKeyDown={handleKeyDown}
                    style={{ flex: 1 }}
                />
                <button
                    id="market-search-btn"
                    className="bsm-btn bsm-btn-primary bsm-btn-sm"
                    onClick={handleSearch}
                >
                    搜索
                </button>
                {query && (
                    <button
                        className="bsm-btn bsm-btn-outline bsm-btn-sm"
                        onClick={() => {
                            setInputValue("");
                            setQuery("");
                        }}
                    >
                        清除
                    </button>
                )}
            </div>

            {/* Filters bar */}
            <div className="bsm-market-search-row" style={{ marginTop: "0.5rem" }}>
                <button
                    className={`bsm-btn bsm-btn-sm bsm-market-auto-refresh-btn ${autoRefresh ? 'bsm-btn-primary' : 'bsm-btn-outline'}`}
                    onClick={() => setAutoRefresh(!autoRefresh)}
                >
                    {refreshing ? (
                        "刷新中..."
                    ) : autoRefresh ? (
                        `自动刷新 (${countdown}s)`
                    ) : (
                        "自动刷新 (关)"
                    )}
                </button>
                <div className="bsm-market-filter-group">
                    <div
                        className="bsm-market-filter-dropdown"
                        onPointerDown={(e) => e.stopPropagation()}
                    >
                        <button
                            type="button"
                            className={`bsm-market-filter-trigger ${openFilter === "time" ? "open" : ""}`}
                            onClick={() => setOpenFilter((prev) => prev === "time" ? null : "time")}
                        >
                            <span>时间</span>
                            <strong>{singleSelectLabel(timeOptions, timeFilter, "全部时间")}</strong>
                            <span className="bsm-market-filter-caret">▼</span>
                        </button>
                        {openFilter === "time" && (
                            <div className="bsm-market-filter-menu">
                                {timeOptions.map((option) => (
                                    <button
                                        key={option.value}
                                        type="button"
                                        className={`bsm-market-filter-item ${timeFilter === option.value ? "active" : ""}`}
                                        onClick={() => {
                                            setTimeFilter(option.value);
                                            setOpenFilter(null);
                                        }}
                                    >
                                        {option.label}
                                    </button>
                                ))}
                            </div>
                        )}
                    </div>

                    <div
                        className="bsm-market-filter-dropdown"
                        onPointerDown={(e) => e.stopPropagation()}
                    >
                        <button
                            type="button"
                            className={`bsm-market-filter-trigger ${openFilter === "sort" ? "open" : ""}`}
                            onClick={() => setOpenFilter((prev) => prev === "sort" ? null : "sort")}
                        >
                            <span>排序</span>
                            <strong>{singleSelectLabel(sortOptions, sortBy, "最新上架")}</strong>
                            <span className="bsm-market-filter-caret">▼</span>
                        </button>
                        {openFilter === "sort" && (
                            <div className="bsm-market-filter-menu">
                                {sortOptions.map((option) => (
                                    <button
                                        key={option.value}
                                        type="button"
                                        className={`bsm-market-filter-item ${sortBy === option.value ? "active" : ""}`}
                                        onClick={() => {
                                            setSortBy(option.value);
                                            setOpenFilter(null);
                                        }}
                                    >
                                        {option.label}
                                    </button>
                                ))}
                            </div>
                        )}
                    </div>

                    <div
                        className="bsm-market-filter-dropdown"
                        onPointerDown={(e) => e.stopPropagation()}
                    >
                        <button
                            type="button"
                            className={`bsm-market-filter-trigger ${openFilter === "category" ? "open" : ""}`}
                            onClick={() => {
                                if (openFilter === "category") {
                                    setCategoryFilters((prev) => {
                                        const next = [...categoryDraftFilters].sort();
                                        const current = [...prev].sort();
                                        if (next.length === current.length && next.every((item, index) => item === current[index])) {
                                            return prev;
                                        }
                                        return categoryDraftFilters;
                                    });
                                    setOpenFilter(null);
                                    return;
                                }
                                setCategoryDraftFilters(categoryFilters);
                                setOpenFilter("category");
                            }}
                        >
                            <span>分类</span>
                            <strong>{categoryLabel}</strong>
                            <span className="bsm-market-filter-caret">▼</span>
                        </button>
                        {openFilter === "category" && (
                            <div className="bsm-market-filter-menu">
                                {categoryOptions.map((option) => {
                                    const checked = categoryDraftFilters.includes(option.id);
                                    return (
                                        <label
                                            key={option.id}
                                            className={`bsm-market-filter-check ${checked ? "active" : ""}`}
                                        >
                                            <input
                                                type="checkbox"
                                                checked={checked}
                                                onChange={(e) => {
                                                    if (e.target.checked) {
                                                        setCategoryDraftFilters((prev) => [...prev, option.id]);
                                                    } else {
                                                        setCategoryDraftFilters((prev) => prev.filter((item) => item !== option.id));
                                                    }
                                                }}
                                            />
                                            <span className="bsm-market-filter-check-box" aria-hidden="true">
                                                {checked ? "✓" : ""}
                                            </span>
                                            <span>{option.label}</span>
                                        </label>
                                    );
                                })}
                            </div>
                        )}
                    </div>
                </div>
            </div>

            {/* Stats bar */}
            <div className="bsm-market-stats-bar">
                {loading ? (
                    <span className="bsm-text-muted">加载中…</span>
                ) : (
                    <span className="bsm-text-muted">
                        {query ? (
                            <>搜索 &ldquo;<strong>{query}</strong>&rdquo; 共 </>
                        ) : (
                            <>全部商品 共 </>
                        )}
                        <strong className="bsm-stats-accent">{pagination.total_count}</strong> 件
                        {pagination.total_pages > 1 && <>，第 {pagination.page} / {pagination.total_pages} 页</>}
                    </span>
                )}
            </div>

            {error && <div className="bsm-alert bsm-alert-error">{error}</div>}

            {/* Card Grid */}
            {loading ? (
                <div className="bsm-market-skeleton-grid">
                    {Array.from({ length: 20 }).map((_, i) => (
                        <div key={i} className="bsm-market-skeleton" />
                    ))}
                </div>
            ) : items.length === 0 ? (
                <div className="bsm-empty">
                    <p style={{ fontSize: "2.5rem", marginBottom: "0.5rem" }}>🛍️</p>
                    <p>{query ? "没有匹配的商品" : "暂无市场数据"}</p>
                    <p className="bsm-text-muted" style={{ marginTop: "0.5rem", fontSize: "0.8125rem" }}>
                        {!query && "运行扫描后数据将出现在这里"}
                    </p>
                </div>
            ) : (
                <div className="bsm-market-grid">
                    {items.map((item) => (
                        <Link
                            key={item.id}
                            href={`/market/${item.id}`}
                            id={`market-item-${item.id}`}
                            className="bsm-market-card"
                        >
                            <div className="bsm-market-img-wrap">
                                {item.bundled_items && item.bundled_items.length > 1 ? (
                                    <div
                                        className="bsm-market-bundle-grid"
                                        style={{
                                            gridTemplateColumns: `repeat(${Math.min(3, Math.ceil(Math.sqrt(Math.min(item.bundled_items.length, 9))))}, 1fr)`,
                                        }}
                                    >
                                        {item.bundled_items.slice(0, 9).map((b_item, idx) => {
                                            const imgSrc = b_item.imgUrl || b_item.img || b_item.pic || b_item.image;
                                            return (
                                                <div
                                                    key={idx}
                                                    className="bsm-market-bundle-cell"
                                                >
                                                    {imgSrc ? (
                                                        /* eslint-disable-next-line @next/next/no-img-element */
                                                        <img
                                                            src={imgSrc}
                                                            alt={b_item.name}
                                                            className="bsm-market-bundle-img"
                                                            referrerPolicy="no-referrer"
                                                            onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }}
                                                        />
                                                    ) : (
                                                        <div className="bsm-market-bundle-fallback">📦</div>
                                                    )}
                                                </div>
                                            );
                                        })}
                                    </div>
                                ) : item.img_url ? (
                                    // eslint-disable-next-line @next/next/no-img-element
                                    <img
                                        src={item.img_url}
                                        alt={item.name ?? ""}
                                        className="bsm-market-img"
                                        referrerPolicy="no-referrer"
                                        onError={(e) => {
                                            (e.currentTarget as HTMLImageElement).style.display = "none";
                                            (e.currentTarget.nextSibling as HTMLElement | null)?.removeAttribute("style");
                                        }}
                                    />
                                ) : null}
                                <div
                                    className="bsm-market-img-fallback"
                                    style={(item.bundled_items && item.bundled_items.length > 1) || item.img_url ? { display: "none" } : {}}
                                >
                                    🖼️
                                </div>
                            </div>
                            <div className="bsm-market-card-body">
                                <p className="bsm-market-card-name">{item.name ?? "未知商品"}</p>
                                {item.recent_listed_count != null && item.recent_listed_count > 0 && (
                                    <div style={{ marginTop: "4px", fontSize: "0.75rem", color: "var(--brand-accent)" }}>
                                        🔥 15天上架 {item.recent_listed_count} 次
                                    </div>
                                )}
                                <div className="bsm-market-card-footer">
                                    <span className="bsm-market-price">
                                        ¥ {item.show_price ?? "—"}
                                        {discountText(item.show_price, item.show_market_price) && (
                                            <span style={{ marginLeft: "0.4rem", fontSize: "0.75rem", fontWeight: 500, color: "var(--text-secondary)" }}>
                                                {discountText(item.show_price, item.show_market_price)}
                                            </span>
                                        )}
                                        {item.publish_status === 2 && <span style={{ color: "#fff", fontWeight: "bold", marginLeft: "4px" }}>[已下架]</span>}
                                        {item.sale_status === 2 && <span style={{ color: "#fff", fontWeight: "bold", marginLeft: "4px" }}>[已售出]</span>}
                                    </span>
                                    <span className="bsm-market-time">{timeAgo(item.created_at || item.updated_at)}</span>
                                </div>
                            </div>
                        </Link>
                    ))}
                </div>
            )}

            {/* Pagination */}
            {pagination.total_pages > 1 && (
                <div className="bsm-market-pagination">
                    <button
                        className="bsm-btn bsm-btn-outline bsm-btn-sm"
                        disabled={pagination.page <= 1}
                        onClick={() => handlePage(pagination.page - 1)}
                    >
                        ← 上一页
                    </button>

                    <div className="bsm-market-page-nums">
                        {Array.from({ length: pagination.total_pages }, (_, i) => i + 1)
                            .filter(
                                (p) =>
                                    p === 1 ||
                                    p === pagination.total_pages ||
                                    Math.abs(p - pagination.page) <= 2
                            )
                            .reduce<(number | "…")[]>((acc, p, idx, arr) => {
                                if (idx > 0 && typeof arr[idx - 1] === "number" && (p as number) - (arr[idx - 1] as number) > 1) {
                                    acc.push("…");
                                }
                                acc.push(p);
                                return acc;
                            }, [])
                            .map((p, i) =>
                                p === "…" ? (
                                    <span key={`ellipsis-${i}`} className="bsm-page-ellipsis">…</span>
                                ) : (
                                    <button
                                        key={p}
                                        className={`bsm-page-btn${p === pagination.page ? " active" : ""}`}
                                        onClick={() => typeof p === "number" && handlePage(p)}
                                    >
                                        {p}
                                    </button>
                                )
                            )}
                    </div>

                    <button
                        className="bsm-btn bsm-btn-outline bsm-btn-sm"
                        disabled={pagination.page >= pagination.total_pages}
                        onClick={() => handlePage(pagination.page + 1)}
                    >
                        下一页 →
                    </button>
                </div>
            )}
        </Shell>
    );
}
