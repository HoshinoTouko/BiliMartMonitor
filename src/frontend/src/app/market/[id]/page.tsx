"use client";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import Shell from "@/components/Shell";
import { apiGet } from "@/lib/api";
import { formatMonthDayTime, timeAgo as timeAgoFromApiDate } from "@/lib/datetime";
import {
    ScatterChart,
    Scatter,
    XAxis,
    YAxis,
    ZAxis,
    CartesianGrid,
    Tooltip,
    ResponsiveContainer,
} from "recharts";

interface MarketItem {
    id: number;
    name: string;
    show_price: string | null;
    show_market_price: string | null;
    uface: string | null;
    uname: string | null;
    img_url: string;
    created_at: string | null;
    updated_at: string | null;
    recent_listed_count?: number;
    bundled_items?: {
        itemsId: number;
        skuId?: number;
        blindBoxId?: number;
        blindboxId?: number;
        name: string;
        imgUrl?: string;
        img?: string;
        pic?: string;
        image?: string;
    }[];
    publish_status?: number | null;
    sale_status?: number | null;
    drop_reason?: string | null;
}

interface PricePoint {
    recorded_at: string;
    price: number | null;
    show_price: string | null;
    name?: string;
    c2c_items_id?: number;
}

interface RecentListing {
    c2c_items_id: number;
    name: string;
    show_price: string | null;
    show_market_price: string | null;
    uface: string | null;
    uname: string | null;
    created_at: string | null;
    updated_at: string | null;
    show_est_price?: string | null;
    publish_status?: number | null;
    sale_status?: number | null;
    drop_reason?: string | null;
    bundled_items?: {
        itemsId: number;
        skuId?: number;
        blindBoxId?: number;
        blindboxId?: number;
        name: string;
        imgUrl?: string;
        img?: string;
        pic?: string;
        image?: string;
    }[];
}

interface ChartDataPoint {
    time: string;
    price: number;
    name?: string;
    c2c_items_id?: number;
    publish_status?: number | null;
    sale_status?: number | null;
}

interface ChartDotShapeProps {
    cx?: number;
    cy?: number;
    payload?: ChartDataPoint;
}

function timeAgo(dt: string | number | null): string {
    return timeAgoFromApiDate(dt, "—");
}

function discountText(showPrice: string | null, showMarketPrice: string | null): string | null {
    const price = Number(showPrice);
    const marketPrice = Number(showMarketPrice);
    if (!Number.isFinite(price) || !Number.isFinite(marketPrice) || marketPrice <= 0 || price <= 0) {
        return null;
    }
    return `${(price / marketPrice * 10).toFixed(1)}折`;
}

// Custom tooltip for the chart
const ChartTooltip = ({
    active,
    payload,
}: {
    active?: boolean;
    payload?: { payload: ChartDataPoint }[];
}) => {
    if (!active || !payload?.length) return null;
    const data = payload[0].payload;
    return (
        <div className="bsm-chart-tooltip">
            <p className="bsm-chart-tooltip-time">{data.time}</p>
            <p className="bsm-chart-tooltip-price">¥ {(data.price / 100).toFixed(2)}</p>
            {data.name && (
                <div style={{ marginTop: "6px", display: "flex", flexDirection: "column", gap: "4px" }}>
                    <p style={{ fontSize: "0.75rem", color: "var(--text-secondary)", lineHeight: 1.2 }}>{data.name}</p>
                    {/等\d+个商品/.test(data.name) && (
                        <span className="bsm-listing-bundle-tag" style={{ alignSelf: "flex-start" }}>打包售卖</span>
                    )}
                </div>
            )}
        </div>
    );
};

function formatDate(dt: string | number): string {
    return formatMonthDayTime(dt, "—");
}

export default function MarketItemDetailPage() {
    const params = useParams<{ id: string }>();
    const id = params?.id;

    const [item, setItem] = useState<MarketItem | null>(null);
    const [history, setHistory] = useState<PricePoint[]>([]);
    const [recentListings, setRecentListings] = useState<RecentListing[]>([]);
    const [page, setPage] = useState(1);
    const [totalPages, setTotalPages] = useState(1);
    const [sortBy, setSortBy] = useState("TIME_DESC");
    const [loading, setLoading] = useState(true);
    const [loadingChart, setLoadingChart] = useState(true);
    const [loadingListings, setLoadingListings] = useState(false);
    const [error, setError] = useState("");
    const [isZoomed, setIsZoomed] = useState(false);
    const [zoomedImgUrl, setZoomedImgUrl] = useState<string | null>(null);
    const [zoomRect, setZoomRect] = useState<DOMRect | null>(null);
    const [refreshing, setRefreshing] = useState(false);
    const [refreshingListings, setRefreshingListings] = useState(false);
    const [refreshProgress, setRefreshProgress] = useState(0);
    const [inFlightIds, setInFlightIds] = useState<number[]>([]);

    useEffect(() => {
        if (!id) return;
        const loadItem = async () => {
            setLoading(true);
            setLoadingChart(true);
            setError("");
            try {
                const itemData = await apiGet(`/api/market/items/${id}`) as { item?: MarketItem };
                setItem(itemData.item ?? null);
                const firstBundled = itemData.item?.bundled_items?.[0];
                const itemsId = firstBundled?.itemsId;
                const skuId = firstBundled?.skuId;
                if (itemsId != null && skuId != null) {
                    const histData = await apiGet(`/api/product/${itemsId}/${skuId}/price-history`) as { history?: PricePoint[] };
                    setHistory(histData.history ?? []);
                } else {
                    setHistory([]);
                }
            } catch (e: unknown) {
                console.error("加载历史价格失败", e);
                setError(e instanceof Error ? e.message : "加载失败");
            } finally {
                setLoading(false);
                setLoadingChart(false);
            }
        };
        loadItem();
    }, [id]);

    const handleRefresh = async () => {
        if (!id) return;
        setRefreshing(true);
        try {
            const { apiPost } = await import("@/lib/api");
            const data = await apiPost(`/api/market/items/${id}/refresh`, {}) as { item?: MarketItem };
            if (data?.item) {
                setItem(data.item);
                // toast could be added here
            }
        } catch (e: unknown) {
            setError(e instanceof Error ? e.message : "刷新失败");
        } finally {
            setRefreshing(false);
        }
    };

    useEffect(() => {
        if (!id) return;
        const loadListings = async () => {
            setLoadingListings(true);
            try {
                const data = await apiGet(`/api/market/items/${id}/recent-listings?page=${page}&limit=20&sort_by=${sortBy}`) as { listings?: RecentListing[], total_pages?: number };
                setRecentListings(data.listings ?? []);
                setTotalPages(data.total_pages ?? 1);
            } catch (e) {
                console.error("Failed to load listings", e);
            } finally {
                setLoadingListings(false);
            }
        };
        loadListings();
    }, [id, page, sortBy]);

    const chartData = history
        .filter((h) => h.price != null)
        .map((h) => ({
            time: formatDate(h.recorded_at),
            price: h.price as number,
            label: h.show_price ?? String((h.price ?? 0) / 100),
            name: h.name,
            c2c_items_id: h.c2c_items_id,
            publish_status: recentListings.find(l => l.c2c_items_id === h.c2c_items_id)?.publish_status,
            sale_status: recentListings.find(l => l.c2c_items_id === h.c2c_items_id)?.sale_status,
        }));

    const blindBoxIds = Array.from(
        new Set(
            (item?.bundled_items ?? [])
                .map((b) => b.blindBoxId ?? b.blindboxId)
                .filter((v): v is number => Number.isFinite(v))
        )
    );
    const bundledItemIds = Array.from(
        new Set(
            (item?.bundled_items ?? [])
                .map((b) => b.itemsId)
                .filter((v): v is number => Number.isFinite(v))
        )
    );
    const bundledSkuIds = Array.from(
        new Set(
            (item?.bundled_items ?? [])
                .map((b) => b.skuId)
                .filter((v): v is number => Number.isFinite(v))
        )
    );

    // Price delta
    const priceMin =
        chartData.length > 0 ? Math.min(...chartData.map((d) => d.price)) : null;
    const priceMax =
        chartData.length > 0 ? Math.max(...chartData.map((d) => d.price)) : null;

    let yDomain: [number | 'auto', number | 'auto'] = ['auto', 'auto'];
    if (priceMin !== null && priceMax !== null) {
        if (priceMax > priceMin) {
            const diff = priceMax - priceMin;
            yDomain = [Math.max(0, Math.floor(priceMin - diff * 0.1)), Math.ceil(priceMax + diff * 0.1)];
        } else {
            yDomain = [Math.max(0, Math.floor(priceMin * 0.9)), Math.ceil(priceMax * 1.1)];
        }
    }

    const renderChart = () => (
        <div className="bsm-section" style={{ margin: 0 }}>
            <div className="bsm-section-title">全市场估算价格记录 (近15天)</div>
            {loadingChart ? (
                <div className="bsm-market-skeleton-detail" style={{ height: "280px" }} />
            ) : chartData.length < 2 ? (
                <div className="bsm-empty" style={{ padding: "2rem 1rem" }}>
                    <p style={{ fontSize: "2rem", marginBottom: "0.5rem" }}>📊</p>
                    <p>{chartData.length === 0 ? "暂无历史记录" : "至少需要 2 条记录才能显示走势"}</p>
                    <p className="bsm-text-muted" style={{ fontSize: "0.8125rem", marginTop: "0.25rem" }}>
                        单品估算价格自动基于发售指导价等比例换算
                    </p>
                </div>
            ) : (
                <div className="bsm-chart-wrap" style={{ position: "relative" }}>
                    <div style={{ position: "absolute", top: "12px", right: "12px", display: "flex", gap: "12px", fontSize: "0.75rem", zIndex: 10 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: "4px" }}>
                            <div style={{ width: "8px", height: "8px", borderRadius: "50%", background: "#10b981" }}></div>
                            <span style={{ color: "var(--text-secondary)" }}>售卖中</span>
                        </div>
                        <div style={{ display: "flex", alignItems: "center", gap: "4px" }}>
                            <div style={{ width: "8px", height: "8px", borderRadius: "50%", background: "#ef4444" }}></div>
                            <span style={{ color: "var(--text-secondary)" }}>已下架</span>
                        </div>
                        <div style={{ display: "flex", alignItems: "center", gap: "4px" }}>
                            <div style={{ width: "8px", height: "8px", borderRadius: "50%", background: "#3b82f6" }}></div>
                            <span style={{ color: "var(--text-secondary)" }}>已售出</span>
                        </div>
                    </div>
                    <ResponsiveContainer width="100%" height={280}>
                        <ScatterChart margin={{ top: 16, right: 16, left: 0, bottom: 0 }}>
                            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                            <XAxis
                                dataKey="time"
                                name="时间"
                                tick={false}
                                label={{ value: "时间", position: "insideBottomRight", offset: 0, fill: "#6b6988", fontSize: 11 }}
                                axisLine={{ stroke: "rgba(255,255,255,0.1)" }}
                                tickLine={false}
                            />
                            <YAxis
                                dataKey="price"
                                name="价格"
                                domain={yDomain}
                                tick={{ fill: "#6b6988", fontSize: 11 }}
                                axisLine={false}
                                tickLine={false}
                                tickFormatter={(v: number) => `¥${(v / 100).toFixed(0)}`}
                                width={56}
                            />
                            <ZAxis dataKey="name" name="源商品" />
                            <Tooltip content={<ChartTooltip />} cursor={{ strokeDasharray: '3 3', stroke: 'rgba(255,255,255,0.1)' }} />
                            <Scatter
                                data={chartData}
                                shape={(props: ChartDotShapeProps) => {
                                    const { cx, cy, payload } = props;
                                    if (typeof cx !== "number" || typeof cy !== "number" || !payload) {
                                        return null;
                                    }
                                    let fill = "#10b981"; // success green
                                    if (payload.publish_status === 2) {
                                        fill = "#ef4444"; // error red
                                    } else if (payload.sale_status === 2) {
                                        fill = "#3b82f6"; // info blue
                                    }
                                    return <circle cx={cx} cy={cy} r={4} fill={fill} />;
                                }}
                                style={{ cursor: "pointer" }}
                                onClick={(e) => {
                                    if (e && e.payload && e.payload.c2c_items_id) {
                                        window.open(`/market/${e.payload.c2c_items_id}`, "_blank");
                                    }
                                }}
                            />
                        </ScatterChart>
                    </ResponsiveContainer>
                </div>
            )}
        </div>
    );

    return (
        <Shell title={loading ? <div className="bsm-market-skeleton-detail" style={{ height: "32px", width: "180px", margin: 0 }} /> : (item?.name ?? "商品详情")}>
            <div className="bsm-detail-back">
                <Link href="/market" className="bsm-link" style={{ fontSize: "0.875rem" }}>
                    ← 返回市场列表
                </Link>
            </div>

            {error && <div className="bsm-alert bsm-alert-error">{error}</div>}

            {loading ? (
                <>
                    <div className="bsm-detail-layout">
                        <div className="bsm-detail-header-container">
                            <div className="bsm-detail-header">
                                <div className="bsm-detail-img-wrap">
                                    <div className="bsm-market-skeleton-detail" style={{ width: "100%", height: "100%", borderRadius: "8px", margin: 0 }} />
                                </div>
                                <div className="bsm-detail-meta" style={{ flex: 1, padding: "0.5rem 0" }}>
                                    <div className="bsm-market-skeleton-detail" style={{ height: "32px", width: "80%", marginBottom: "1.5rem" }} />
                                    <div className="bsm-market-skeleton-detail" style={{ height: "24px", width: "40%", marginBottom: "0.75rem" }} />
                                    <div className="bsm-market-skeleton-detail" style={{ height: "36px", width: "240px" }} />
                                </div>
                            </div>
                        </div>
                        <div className="bsm-detail-sidebar">
                            <div className="bsm-detail-price-stats">
                                <div className="bsm-stat-card"><div className="bsm-market-skeleton-detail" style={{ height: "36px", width: "100%", margin: 0 }} /></div>
                                <div className="bsm-stat-card"><div className="bsm-market-skeleton-detail" style={{ height: "36px", width: "100%", margin: 0 }} /></div>
                                <div className="bsm-stat-card"><div className="bsm-market-skeleton-detail" style={{ height: "36px", width: "100%", margin: 0 }} /></div>
                                <div className="bsm-stat-card"><div className="bsm-market-skeleton-detail" style={{ height: "36px", width: "100%", margin: 0 }} /></div>
                            </div>
                        </div>
                    </div>
                </>
            ) : item ? (
                <>
                    <div className="bsm-detail-layout">
                        <div className="bsm-detail-header-container">
                            {/* Item header */}
                            <div className="bsm-detail-header">
                                <div className="bsm-detail-img-wrap">
                                    {item.img_url ? (
                                        // eslint-disable-next-line @next/next/no-img-element
                                        <img
                                            src={zoomedImgUrl || item?.img_url || ""}
                                            alt={item.name ?? ""}
                                            className="bsm-detail-img"
                                            referrerPolicy="no-referrer"
                                            onClick={(e) => {
                                                setZoomRect(e.currentTarget.getBoundingClientRect());
                                                setZoomedImgUrl(item.img_url);
                                                setIsZoomed(true);
                                            }}
                                            style={{ cursor: "zoom-in" }}
                                            onError={(e) => {
                                                (e.currentTarget as HTMLImageElement).style.display = "none";
                                            }}
                                        />
                                    ) : (
                                        <div className="bsm-detail-img-fallback">🖼️</div>
                                    )}
                                </div>
                                <div className="bsm-detail-meta">
                                    <h2 className="bsm-detail-name">
                                        {item.name}
                                        {!(item.bundled_items && item.bundled_items.length > 1) && (
                                            <span style={{ fontSize: "0.875rem", color: "var(--text-muted)", marginLeft: "0.5rem", fontWeight: "normal" }}>
                                                #{item.id}
                                            </span>
                                        )}
                                    </h2>
                                    {(blindBoxIds.length > 0 || bundledItemIds.length > 0 || bundledSkuIds.length > 0) && (
                                        <div
                                            style={{
                                                marginTop: "-0.125rem",
                                                marginBottom: "0.5rem",
                                                fontSize: "0.75rem",
                                                color: "var(--text-muted)",
                                                lineHeight: 1.3,
                                            }}
                                        >
                                            盲盒ID：{blindBoxIds.length > 0 ? blindBoxIds.join(", ") : "—"}
                                            {" | "}
                                            Item ID：{bundledItemIds.length > 0 ? bundledItemIds.join(", ") : "—"}
                                            {" | "}
                                            SKU ID：{bundledSkuIds.length > 0 ? bundledSkuIds.join(", ") : "—"}
                                        </div>
                                    )}
                                    <div className="bsm-detail-prices">
                                        <span className="bsm-detail-price-current">
                                            当前价格：<strong>¥ {item.show_price ?? "—"}</strong>
                                            {discountText(item.show_price, item.show_market_price) && (
                                                <span style={{ marginLeft: "0.5rem", fontSize: "0.8125rem", fontWeight: 500, color: "var(--text-secondary)" }}>
                                                    {discountText(item.show_price, item.show_market_price)}
                                                </span>
                                            )}
                                            {item.publish_status === 2 && (
                                                <span style={{ marginLeft: "1rem", color: "#fff", fontWeight: "bold", fontSize: "1rem" }}>已下架</span>
                                            )}
                                            {item.sale_status === 2 && (
                                                <span style={{ marginLeft: "1rem", color: "#fff", fontWeight: "bold", fontSize: "1rem" }}>已售出</span>
                                            )}
                                        </span>
                                        {item.show_market_price && (
                                            <span className="bsm-detail-price-market">
                                                市场价：¥ {item.show_market_price}
                                            </span>
                                        )}
                                    </div>
                                    <div className="bsm-detail-seller">
                                        {item.uface && (
                                            // eslint-disable-next-line @next/next/no-img-element
                                            <img
                                                src={item.uface}
                                                alt={item.uname ?? ""}
                                                className="bsm-detail-uface"
                                                referrerPolicy="no-referrer"
                                                onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }}
                                            />
                                        )}
                                        <span className="bsm-text-muted">{item.uname ?? "未知卖家"}</span>
                                    </div>
                                    <div style={{ marginTop: "1rem", display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                                        <a
                                            href={`https://mall.bilibili.com/neul-next/index.html?page=magic-market_detail&noTitleBar=1&itemsId=${item.id}`}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                            className="bsm-btn bsm-btn-primary bsm-btn-sm"
                                            style={{ textDecoration: "none" }}
                                        >
                                            跳转市集
                                        </a>
                                        {item.bundled_items && item.bundled_items.length === 1 && (
                                            <a
                                                href={`/product/${item.bundled_items[0].itemsId}`}
                                                target="_blank"
                                                rel="noopener noreferrer"
                                                className="bsm-btn bsm-btn-primary bsm-btn-sm"
                                                style={{ textDecoration: "none" }}
                                            >
                                                查看商品
                                            </a>
                                        )}
                                        <a
                                            href={`https://www.hpoi.net/search?itemType=hobby&keyword=${encodeURIComponent(item.name.replace(/等\d+个商品$/, '').trim())}`}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                            className="bsm-btn bsm-btn-outline bsm-btn-sm"
                                            style={{ textDecoration: "none" }}
                                        >
                                            HPoi 搜索
                                        </a>
                                        <button
                                            onClick={handleRefresh}
                                            disabled={refreshing}
                                            className="bsm-btn bsm-btn-outline bsm-btn-sm"
                                        >
                                            {refreshing ? "刷新中..." : "刷新状态"}
                                        </button>
                                    </div>
                                </div>
                            </div>


                        </div>
                        <div className="bsm-detail-sidebar">
                            {/* Price stats */}
                            <div className="bsm-detail-price-stats">
                                <div className="bsm-stat-card">
                                    <span className="bsm-stat-label">15天上架数</span>
                                    <span className="bsm-stat-value" style={{ fontSize: "1.25rem", color: "var(--brand-accent)" }}>
                                        {item.recent_listed_count ?? 0} 次
                                    </span>
                                </div>
                                {loadingChart ? (
                                    <>
                                        <div className="bsm-stat-card"><div className="bsm-market-skeleton-detail" style={{ height: "36px", width: "100%", margin: 0 }} /></div>
                                        <div className="bsm-stat-card"><div className="bsm-market-skeleton-detail" style={{ height: "36px", width: "100%", margin: 0 }} /></div>
                                        <div className="bsm-stat-card"><div className="bsm-market-skeleton-detail" style={{ height: "36px", width: "100%", margin: 0 }} /></div>
                                    </>
                                ) : chartData.length > 0 && priceMin !== null && priceMax !== null && (
                                    <>
                                        <div className="bsm-stat-card">
                                            <span className="bsm-stat-label">历史最低</span>
                                            <span className="bsm-stat-value" style={{ fontSize: "1.25rem" }}>
                                                ¥ {(priceMin / 100).toFixed(2)}
                                            </span>
                                        </div>
                                        <div className="bsm-stat-card">
                                            <span className="bsm-stat-label">历史最高</span>
                                            <span className="bsm-stat-value" style={{ fontSize: "1.25rem" }}>
                                                ¥ {(priceMax / 100).toFixed(2)}
                                            </span>
                                        </div>
                                        <div className="bsm-stat-card">
                                            <span className="bsm-stat-label">价格记录</span>
                                            <span className="bsm-stat-value" style={{ fontSize: "1.25rem" }}>
                                                {chartData.length} 条
                                            </span>
                                        </div>
                                    </>
                                )}
                            </div>

                            {/* Bundled Items if any */}
                            {item.bundled_items && item.bundled_items.length > 1 && (
                                <div className="bsm-section">
                                    <div className="bsm-section-title">包含商品 ({item.bundled_items.length})</div>
                                    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: "0.75rem" }}>
                                        {item.bundled_items.map((b_item, idx) => {
                                            const imgSrc = b_item.imgUrl || b_item.img || b_item.pic || b_item.image;
                                            return (
                                                <div key={idx} onClick={() => window.open(`/product/${b_item.itemsId}`, '_self')} style={{
                                                    display: "flex",
                                                    alignItems: "center",
                                                    gap: "0.75rem",
                                                    padding: "0.75rem",
                                                    backgroundColor: "rgba(255,255,255,0.02)",
                                                    borderRadius: "8px",
                                                    border: "1px solid rgba(255,255,255,0.05)",
                                                    textDecoration: "none",
                                                    color: "inherit",
                                                    cursor: "pointer"
                                                }}>
                                                    {imgSrc ? (
                                                        /* eslint-disable-next-line @next/next/no-img-element */
                                                        <img
                                                            src={imgSrc}
                                                            alt={b_item.name}
                                                            style={{ width: "48px", height: "48px", objectFit: "cover", borderRadius: "4px", backgroundColor: "rgba(255,255,255,0.05)", cursor: "zoom-in" }}
                                                            referrerPolicy="no-referrer"
                                                            onClick={(e) => {
                                                                e.preventDefault();
                                                                e.stopPropagation();
                                                                setZoomRect(e.currentTarget.getBoundingClientRect());
                                                                setZoomedImgUrl(imgSrc);
                                                                setIsZoomed(true);
                                                            }}
                                                            onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }}
                                                        />
                                                    ) : (
                                                        <div style={{ width: "48px", height: "48px", borderRadius: "4px", backgroundColor: "rgba(255,255,255,0.05)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "1.25rem" }}>📦</div>
                                                    )}
                                                    <div style={{ flex: 1, minWidth: 0, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                                                        <div style={{ minWidth: 0, paddingRight: "0.5rem" }}>
                                                            <div style={{ color: "var(--text-secondary)", fontSize: "0.75rem", marginBottom: "0.25rem" }}>#{b_item.itemsId}</div>
                                                            <div style={{ color: "var(--text-primary)", fontSize: "0.875rem", fontWeight: 500, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }} title={b_item.name}>
                                                                {b_item.name}
                                                            </div>
                                                        </div>
                                                        <a href={`https://www.hpoi.net/search?itemType=hobby&keyword=${encodeURIComponent(b_item.name.replace(/等\d+个商品$/, '').trim())}`}
                                                            target="_blank" rel="noopener noreferrer"
                                                            className="bsm-btn bsm-btn-outline bsm-btn-sm"
                                                            style={{ textDecoration: "none", padding: "0.25rem 0.5rem", fontSize: "0.75rem", whiteSpace: "nowrap", flexShrink: 0 }}
                                                            onClick={(e) => e.stopPropagation()}
                                                        >HPoi</a>
                                                    </div>
                                                </div>
                                            );
                                        })}
                                    </div>
                                </div>
                            )}

                        </div>

                        {/* Chart placement for multi-item (Inside Desktop Left Grid) */}
                        {item.bundled_items && item.bundled_items.length > 1 && (
                            <div className="bsm-detail-main-content">
                                {renderChart()}
                            </div>
                        )}
                    </div>

                    {/* Chart placement for single-item (Outside Grid Full Width) */}
                    {!(item.bundled_items && item.bundled_items.length > 1) && (
                        <div className="bsm-detail-full-width-chart">
                            {renderChart()}
                        </div>
                    )}
                </>
            ) : null
            }

            {/* Recent Listings */}
            {
                (recentListings.length > 0 || loadingListings) && (
                    <div className="bsm-section">
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem", flexWrap: "wrap", gap: "1rem" }}>
                            <div className="bsm-section-title" style={{ marginBottom: 0 }}>近15天上架清单</div>
                            <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
                                <select
                                    className="bsm-input bsm-input-sm"
                                    value={sortBy}
                                    onChange={(e) => {
                                        setSortBy(e.target.value);
                                        setPage(1);
                                    }}
                                    style={{ width: "auto" }}
                                >
                                    <option value="TIME_DESC">创建时间(新-旧)</option>
                                    <option value="ID_DESC">ID排序(大-小)</option>
                                    <option value="ID_ASC">ID排序(小-大)</option>
                                    <option value="PRICE_ASC">价格升序</option>
                                    <option value="PRICE_DESC">价格降序</option>
                                </select>
                                <button
                                    className="bsm-btn bsm-btn-outline bsm-btn-sm"
                                    disabled={refreshingListings || loadingListings}
                                    onClick={async () => {
                                        if (!id || recentListings.length === 0) return;
                                        setRefreshingListings(true);
                                        setRefreshProgress(0);
                                        setInFlightIds(recentListings.map(l => l.c2c_items_id));

                                        const { apiPost } = await import("@/lib/api");
                                        const CHUNK = 5;
                                        let done = 0;
                                        const total = recentListings.length;

                                        // Split into chunks of 5, fire ALL chunks simultaneously
                                        const chunks: RecentListing[][] = [];
                                        for (let i = 0; i < total; i += CHUNK) {
                                            chunks.push(recentListings.slice(i, i + CHUNK));
                                        }

                                        type BatchResult = { c2c_items_id: number; publish_status?: number; sale_status?: number; drop_reason?: string; ok: boolean };

                                        const refreshChunk = async (chunk: RecentListing[]) => {
                                            const chunkIds = chunk.map(l => l.c2c_items_id);
                                            try {
                                                const data = await apiPost("/api/market/items/batch-refresh", {
                                                    ids: chunkIds
                                                }) as { results?: BatchResult[] };
                                                if (data?.results) {
                                                    setRecentListings(prev => {
                                                        const next = [...prev];
                                                        for (const r of data.results!) {
                                                            if (!r.ok) continue;
                                                            const idx = next.findIndex(l => l.c2c_items_id === r.c2c_items_id);
                                                            if (idx !== -1) {
                                                                next[idx] = { ...next[idx], publish_status: r.publish_status ?? next[idx].publish_status, sale_status: r.sale_status ?? next[idx].sale_status, drop_reason: r.drop_reason ?? next[idx].drop_reason };
                                                            }
                                                        }
                                                        return next;
                                                    });
                                                }
                                            } catch { /* skip failed chunk */ }

                                            // Remove from in-flight
                                            setInFlightIds(prev => prev.filter(id => !chunkIds.includes(id)));
                                            done += chunk.length;
                                            setRefreshProgress(done);
                                        };

                                        try {
                                            await Promise.all(chunks.map(c => refreshChunk(c)));
                                        } finally {
                                            setRefreshingListings(false);
                                            setRefreshProgress(0);
                                            setInFlightIds([]);
                                        }
                                    }}
                                >
                                    {refreshingListings ? `刷新中 (${refreshProgress}/${recentListings.length})…` : "一键刷新当页状态"}
                                </button>
                            </div>
                        </div>
                        <div className="bsm-recent-listings" style={{
                            opacity: loadingListings ? 0.5 : 1,
                            pointerEvents: loadingListings ? 'none' : 'auto',
                            transition: 'opacity 0.2s',
                            minHeight: loadingListings && recentListings.length === 0 ? '150px' : '300px',
                            position: 'relative'
                        }}>
                            {loadingListings ? (
                                <div style={{ position: "absolute", inset: 0, width: "100%", zIndex: 10 }}>
                                    <div className="bsm-market-skeleton-detail" style={{ height: "100%", minHeight: "300px" }} />
                                </div>
                            ) : recentListings.length === 0 ? (
                                <div className="bsm-empty" style={{ padding: "3rem 1rem", gridColumn: "1 / -1" }}>暂无近期上架记录</div>
                            ) : null}
                            {recentListings.map((listing) => (
                                <a
                                    key={listing.c2c_items_id}
                                    href={`/market/${listing.c2c_items_id}`}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className={`bsm-listing-row ${inFlightIds.includes(listing.c2c_items_id) ? 'bsm-listing-in-flight' : ''}`}
                                >
                                    <div className="bsm-listing-main">
                                        <div className="bsm-listing-seller">
                                            {listing.uface ? (
                                                // eslint-disable-next-line @next/next/no-img-element
                                                <img
                                                    src={listing.uface}
                                                    alt={listing.uname ?? ""}
                                                    className="bsm-listing-uface"
                                                    referrerPolicy="no-referrer"
                                                    onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }}
                                                />
                                            ) : (
                                                <div className="bsm-listing-uface-fallback">👤</div>
                                            )}
                                            <div className="bsm-listing-seller-info">
                                                <span className="bsm-listing-uname">
                                                    {listing.uname ?? "未知"}
                                                </span>
                                                {/等\d+个商品/.test(listing.name || "") && (
                                                    <span className="bsm-listing-bundle-tag">
                                                        打包售卖
                                                    </span>
                                                )}
                                            </div>
                                        </div>
                                        <div className="bsm-listing-info">
                                            <span className="bsm-listing-price">
                                                {/等\d+个商品/.test(listing.name || "") && listing.show_est_price
                                                    ? `¥ ${listing.show_est_price} (¥ ${listing.show_price})`
                                                    : `¥ ${listing.show_price ?? "—"}`}
                                                {discountText(listing.show_price, listing.show_market_price) && (
                                                    <span style={{ marginLeft: "0.4rem", fontSize: "0.75rem", fontWeight: 500, color: "var(--text-secondary)" }}>
                                                        {discountText(listing.show_price, listing.show_market_price)}
                                                    </span>
                                                )}
                                                {listing.publish_status === 2 && <span style={{ color: "#fff", fontWeight: "bold", marginLeft: "4px" }}>[已下架]</span>}
                                                {listing.sale_status === 2 && <span style={{ color: "#fff", fontWeight: "bold", marginLeft: "4px" }}>[已售出]</span>}
                                            </span>
                                            <span className="bsm-listing-time">{timeAgo(listing.created_at || listing.updated_at)}</span>
                                        </div>
                                    </div>
                                    {listing.bundled_items && listing.bundled_items.length > 1 && (
                                        <div className="bsm-listing-bundles">
                                            <div className="bsm-listing-bundles-inner">
                                                {listing.bundled_items.map((b_item, b_idx) => {
                                                    const imgSrc = b_item.imgUrl || b_item.img || b_item.pic || b_item.image;
                                                    return (
                                                        <div key={b_idx} className="bsm-bundle-img-wrap" title={b_item.name}
                                                            onClick={(e) => { e.preventDefault(); e.stopPropagation(); window.open(`/product/${b_item.itemsId}`, '_blank'); }}
                                                        >
                                                            {imgSrc ? (
                                                                // eslint-disable-next-line @next/next/no-img-element
                                                                <img src={imgSrc} alt={b_item.name} className="bsm-bundle-img" referrerPolicy="no-referrer" style={{ cursor: "zoom-in" }} onClick={(e) => { e.preventDefault(); e.stopPropagation(); setZoomRect(e.currentTarget.getBoundingClientRect()); setZoomedImgUrl(imgSrc); setIsZoomed(true); }} onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }} />
                                                            ) : (
                                                                <span style={{ fontSize: '1.2rem' }}>📦</span>
                                                            )}
                                                        </div>
                                                    );
                                                })}
                                            </div>
                                        </div>
                                    )}
                                </a>
                            ))}
                        </div>
                        {totalPages > 1 && (
                            <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', marginTop: '1.5rem', gap: '1rem' }}>
                                <button
                                    className="bsm-btn bsm-btn-outline bsm-btn-sm"
                                    disabled={page <= 1}
                                    onClick={() => setPage(p => p - 1)}>
                                    上一页
                                </button>
                                <span style={{ fontSize: '0.875rem', color: 'var(--text-secondary)' }}>
                                    第 {page} / {totalPages} 页
                                </span>
                                <button
                                    className="bsm-btn bsm-btn-outline bsm-btn-sm"
                                    disabled={page >= totalPages}
                                    onClick={() => setPage(p => p + 1)}>
                                    下一页
                                </button>
                            </div>
                        )}
                    </div>
                )
            }


            {/* Image Zoom Overlay */}
            {
                isZoomed && (zoomedImgUrl || item?.img_url) && (
                    <div
                        style={{
                            position: 'fixed',
                            top: 0,
                            left: 0,
                            right: 0,
                            bottom: 0,
                            zIndex: 9999,
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            cursor: 'zoom-out',
                            padding: '2rem'
                        }}
                        onClick={() => { setIsZoomed(false); setZoomedImgUrl(null); }}
                    >
                        {/* Backdrop */}
                        <div style={{
                            position: 'absolute',
                            inset: 0,
                            backgroundColor: 'rgba(0,0,0,0.85)',
                            animation: 'bsmFadeIn 0.3s cubic-bezier(0.16, 1, 0.3, 1)'
                        }} />

                        {/* Image Wrapper */}
                        <div style={{
                            position: 'relative',
                            width: '100%',
                            height: '100%',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            pointerEvents: 'none',
                            transformOrigin: zoomRect ? `${zoomRect.left + zoomRect.width / 2}px ${zoomRect.top + zoomRect.height / 2}px` : 'center',
                            animation: 'bsmZoomFromOrigin 0.3s cubic-bezier(0.16, 1, 0.3, 1)'
                        }}>
                            {/* eslint-disable-next-line @next/next/no-img-element */}
                            <img
                                src={zoomedImgUrl || item?.img_url || ""}
                                alt="Zoomed"
                                style={{
                                    maxWidth: '100%',
                                    maxHeight: '100%',
                                    objectFit: 'contain',
                                    borderRadius: '8px',
                                    boxShadow: '0 10px 40px rgba(0,0,0,0.5)',
                                    pointerEvents: 'auto',
                                    cursor: 'zoom-out'
                                }}
                                referrerPolicy="no-referrer"
                            />
                        </div>
                    </div>
                )
            }
        </Shell >
    );
}
