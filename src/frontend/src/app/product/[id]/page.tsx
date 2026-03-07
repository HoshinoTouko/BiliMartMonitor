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

interface ProductMetadata {
    items_id: number;
    sku_id: number | null;
    name: string;
    img_url: string | null;
    price_min: number | null;
    price_max: number | null;
    show_price_min: string | null;
    show_price_max: string | null;
    recent_listed_count: number;
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
    updated_at: string | null;
    show_est_price?: string | null;
    bundled_items?: { itemsId: number; name: string; imgUrl?: string; img?: string; pic?: string; image?: string }[];
}

interface ChartDataPoint {
    time: string;
    price: number;
    name?: string;
    c2c_items_id?: number;
}

function timeAgo(dt: string | number | null): string {
    return timeAgoFromApiDate(dt, "—");
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

export default function ProductDetailPage() {
    const params = useParams<{ id: string }>();
    const id = params?.id;

    const [item, setItem] = useState<ProductMetadata | null>(null);
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

    useEffect(() => {
        if (!id) return;
        const loadItem = async () => {
            setLoading(true);
            setLoadingChart(true);
            setError("");
            try {
                const itemData = await apiGet(`/api/market/product/${id}`) as { product?: ProductMetadata };
                const product = itemData.product ?? null;
                setItem(product);
                if (product?.sku_id != null) {
                    const histData = await apiGet(`/api/product/${product.items_id}/${product.sku_id}/price-history`) as { history?: PricePoint[] };
                    setHistory(histData.history ?? []);
                } else {
                    setHistory([]);
                }
            } catch (e: unknown) {
                setError(e instanceof Error ? e.message : "加载失败");
                setHistory([]);
            } finally {
                setLoading(false);
                setLoadingChart(false);
            }
        };
        loadItem();
    }, [id]);

    useEffect(() => {
        if (!id) return;
        const loadListings = async () => {
            setLoadingListings(true);
            try {
                const data = await apiGet(`/api/market/product/${id}/recent-listings?page=${page}&limit=20&sort_by=${sortBy}`) as { listings?: RecentListing[], total_pages?: number };
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
        }));

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
                <div className="bsm-chart-wrap">
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
                                fill="#00d9a5"
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
                <Link href="/market" className="bsm-link" style={{ fontSize: "0.875rem" }} prefetch={false}>
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
                                        <span style={{ fontSize: "0.875rem", color: "var(--text-muted)", marginLeft: "0.5rem", fontWeight: "normal" }}>
                                            #{item.items_id}
                                        </span>
                                    </h2>
                                    <div className="bsm-detail-prices">
                                        <span className="bsm-detail-price-current">
                                            价格区间：<strong>¥ {item.show_price_min ?? "—"} - ¥ {item.show_price_max ?? "—"}</strong>
                                        </span>
                                    </div>
                                    <div style={{ marginTop: "1rem", display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                                        <a
                                            href={`https://mall.bilibili.com/neul-next/index.html?page=magic-market_detail&noTitleBar=1&itemsId=${item.items_id}`}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                            className="bsm-btn bsm-btn-primary bsm-btn-sm"
                                            style={{ textDecoration: "none" }}
                                        >
                                            前往购买详情
                                        </a>
                                        <a
                                            href={`https://www.hpoi.net/search?itemType=hobby&keyword=${encodeURIComponent(item.name.replace(/等\d+个商品$/, '').trim())}`}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                            className="bsm-btn bsm-btn-outline bsm-btn-sm"
                                            style={{ textDecoration: "none" }}
                                        >
                                            HPoi 搜索
                                        </a>
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

                        </div>

                        {/* Chart placement for single-item (Outside Grid Full Width) */}
                        <div className="bsm-detail-full-width-chart">
                            {renderChart()}
                        </div>
                    </div>
                </>
            ) : null
            }

            {/* Recent Listings */}
            {
                (recentListings.length > 0 || loadingListings) && (
                    <div className="bsm-section">
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem", flexWrap: "wrap", gap: "1rem" }}>
                            <div className="bsm-section-title" style={{ marginBottom: 0 }}>近15天上架清单</div>
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
                        </div>
                        <div className="bsm-recent-listings" style={{
                            opacity: loadingListings ? 0.5 : 1,
                            pointerEvents: loadingListings ? 'none' : 'auto',
                            transition: 'opacity 0.2s',
                            minHeight: loadingListings && recentListings.length === 0 ? '150px' : '300px',
                            position: 'relative'
                        }}>
                            {loadingListings && recentListings.length === 0 ? (
                                <div style={{ position: "absolute", inset: 0, width: "100%" }}>
                                    <div className="bsm-market-skeleton-detail" style={{ height: "300px" }} />
                                </div>
                            ) : recentListings.length === 0 ? (
                                <div className="bsm-empty" style={{ padding: "3rem 1rem", gridColumn: "1 / -1" }}>暂无近期上架记录</div>
                            ) : null}
                            {recentListings.map((listing) => (
                                <a
                                    key={listing.c2c_items_id}
                                    href={`https://mall.bilibili.com/neul-next/index.html?page=magic-market_detail&noTitleBar=1&itemsId=${listing.c2c_items_id}`}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="bsm-listing-row"
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
                                                <span className="bsm-listing-uname">{listing.uname ?? "未知"}</span>
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
                                            </span>
                                            <span className="bsm-listing-time">{timeAgo(listing.updated_at)}</span>
                                        </div>
                                    </div>
                                    {listing.bundled_items && listing.bundled_items.length > 1 && (
                                        <div className="bsm-listing-bundles">
                                            <div className="bsm-listing-bundles-inner">
                                                {listing.bundled_items.map((b_item, b_idx) => {
                                                    const imgSrc = b_item.imgUrl || b_item.img || b_item.pic || b_item.image;
                                                    return (
                                                        <div key={b_idx} className="bsm-bundle-img-wrap" title={b_item.name}>
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
