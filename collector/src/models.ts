/** 収集結果を受け渡すためのデータ型。値は履歴DB（sql/schema.sql）の列に対応する。 */

export const STOCK = {
  IN: "in_stock",
  LOW: "low_stock",
  OUT: "out_of_stock",
  UNKNOWN: "unknown",
} as const;
export type Stock = (typeof STOCK)[keyof typeof STOCK];

/** 1 商品ぶんの収集結果。取れなかった値は null。 */
export interface ProductItem {
  productId: string;
  name: string | null;
  price: number | null;
  stock: Stock | null;
  category: string | null;
  url: string | null;
}

export type RunStatus = "success" | "partial" | "failed" | "skipped";

/**
 * 1 対象ぶんの収集結果。
 * success=全ページ取得 / partial=一部失敗 / failed=1 件も取れない / skipped=robots.txt などの理由で見送り
 */
export interface CollectResult {
  target: string;
  items: ProductItem[];
  pagesFetched: number;
  errorCount: number;
  status: RunStatus;
  message: string;
}

export function emptyResult(target: string): CollectResult {
  return { target, items: [], pagesFetched: 0, errorCount: 0, status: "success", message: "" };
}
