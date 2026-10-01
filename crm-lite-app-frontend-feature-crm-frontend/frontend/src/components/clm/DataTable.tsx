"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState, type ReactNode } from "react";
import { Icon } from "./icons";

export interface DataTableColumn<T> {
  key: string;
  label: string;
  className?: string;
  sortable?: boolean;
  sortValue?: (row: T) => string | number;
  render: (row: T) => ReactNode;
}

function paginationWindow(current: number, total: number): number[] {
  const span = 2;
  const start = Math.max(1, current - span);
  const end = Math.min(total, current + span);
  const pages: number[] = [];
  for (let p = start; p <= end; p++) pages.push(p);
  return pages;
}

export default function DataTable<T>({
  columns,
  rows,
  rowKey,
  rowHref,
  searchPlaceholder = "Search...",
  searchValue,
  pageSizeOptions = [10, 20, 50],
  defaultPageSize = 20,
}: {
  columns: DataTableColumn<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  rowHref?: (row: T) => string | undefined;
  searchPlaceholder?: string;
  searchValue: (row: T) => string;
  pageSizeOptions?: number[];
  defaultPageSize?: number;
}) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<{ key: string; dir: "asc" | "desc" } | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(defaultPageSize);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [goTo, setGoTo] = useState("");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((r) => searchValue(r).toLowerCase().includes(q));
  }, [rows, query, searchValue]);

  const sorted = useMemo(() => {
    if (!sort) return filtered;
    const col = columns.find((c) => c.key === sort.key);
    if (!col?.sortValue) return filtered;
    const dir = sort.dir === "asc" ? 1 : -1;
    return [...filtered].sort((a, b) => {
      const av = col.sortValue!(a);
      const bv = col.sortValue!(b);
      if (av < bv) return -1 * dir;
      if (av > bv) return 1 * dir;
      return 0;
    });
  }, [filtered, sort, columns]);

  const totalPages = Math.max(1, Math.ceil(sorted.length / pageSize));
  const clampedPage = Math.min(page, totalPages);
  const pageStart = (clampedPage - 1) * pageSize;
  const pageRows = sorted.slice(pageStart, pageStart + pageSize);

  function toggleSort(key: string) {
    setSort((prev) => {
      if (!prev || prev.key !== key) return { key, dir: "asc" };
      return { key, dir: prev.dir === "asc" ? "desc" : "asc" };
    });
    setPage(1);
  }

  function toggleRow(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const allOnPageSelected = pageRows.length > 0 && pageRows.every((r) => selected.has(rowKey(r)));

  function toggleAllOnPage() {
    setSelected((prev) => {
      const next = new Set(prev);
      if (allOnPageSelected) {
        pageRows.forEach((r) => next.delete(rowKey(r)));
      } else {
        pageRows.forEach((r) => next.add(rowKey(r)));
      }
      return next;
    });
  }

  function goToPage(n: number) {
    setPage(Math.min(totalPages, Math.max(1, n)));
  }

  function handleGoToSubmit() {
    const n = parseInt(goTo, 10);
    if (!Number.isNaN(n)) goToPage(n);
    setGoTo("");
  }

  return (
    <div className="card tablecard">
      <div className="table-toolbar">
        <div className="tsearch">
          <Icon name="search" />
          <input
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setPage(1);
            }}
            placeholder={searchPlaceholder}
          />
        </div>
      </div>
      <div className="tablescroll">
        <table>
          <thead>
            <tr>
              <th className="th-check">
                <input type="checkbox" checked={allOnPageSelected} onChange={toggleAllOnPage} aria-label="Select all rows on this page" />
              </th>
              {columns.map((col) => (
                <th key={col.key} className={col.className}>
                  {col.sortable ? (
                    <button
                      type="button"
                      className={`th-sort${sort?.key === col.key ? " on" : ""}`}
                      onClick={() => toggleSort(col.key)}
                    >
                      {col.label}
                      <Icon name={sort?.key === col.key ? (sort.dir === "asc" ? "arrowUp" : "arrowDown") : "arrowUpDown"} />
                    </button>
                  ) : (
                    col.label
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {pageRows.map((row) => {
              const id = rowKey(row);
              const href = rowHref?.(row);
              const isSelected = selected.has(id);
              return (
                <tr
                  key={id}
                  className={`${href ? "clickable" : ""}${isSelected ? " selected" : ""}`}
                  tabIndex={href ? 0 : undefined}
                  onClick={href ? () => router.push(href) : undefined}
                  onKeyDown={href ? (e) => e.key === "Enter" && router.push(href) : undefined}
                >
                  <td className="th-check" onClick={(e) => e.stopPropagation()}>
                    <input type="checkbox" checked={isSelected} onChange={() => toggleRow(id)} aria-label="Select row" />
                  </td>
                  {columns.map((col) => (
                    <td key={col.key} className={col.className}>
                      {col.render(row)}
                    </td>
                  ))}
                </tr>
              );
            })}
            {pageRows.length === 0 && (
              <tr>
                <td colSpan={columns.length + 1} className="empty-hint" style={{ padding: "26px 22px" }}>
                  No records match your search.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="table-foot">
        <div className="tf-left">
          <span>Go to</span>
          <input
            value={goTo}
            onChange={(e) => setGoTo(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleGoToSubmit()}
            onBlur={handleGoToSubmit}
            placeholder={String(clampedPage)}
            inputMode="numeric"
          />
          <select
            value={pageSize}
            onChange={(e) => {
              setPageSize(Number(e.target.value));
              setPage(1);
            }}
          >
            {pageSizeOptions.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </div>
        <div className="tf-right">
          <span className="tf-count">
            {sorted.length === 0
              ? "0 records"
              : `Showing ${pageStart + 1} to ${Math.min(pageStart + pageSize, sorted.length)} of ${sorted.length}`}
          </span>
          <div className="pg-controls">
            <button type="button" className="pg-btn" disabled={clampedPage === 1} onClick={() => goToPage(1)} aria-label="First page">
              <Icon name="chevronsLeft" />
            </button>
            <button type="button" className="pg-btn" disabled={clampedPage === 1} onClick={() => goToPage(clampedPage - 1)} aria-label="Previous page">
              <Icon name="chevronLeft" />
            </button>
            {paginationWindow(clampedPage, totalPages).map((n) => (
              <button key={n} type="button" className={`pg-btn${n === clampedPage ? " on" : ""}`} onClick={() => goToPage(n)}>
                {n}
              </button>
            ))}
            <button type="button" className="pg-btn" disabled={clampedPage === totalPages} onClick={() => goToPage(clampedPage + 1)} aria-label="Next page">
              <Icon name="chevronRight" />
            </button>
            <button type="button" className="pg-btn" disabled={clampedPage === totalPages} onClick={() => goToPage(totalPages)} aria-label="Last page">
              <Icon name="chevronsRight" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export function TableLink({ href, children }: { href?: string; children: ReactNode }) {
  if (!href) return <span className="t-strong">{children}</span>;
  return (
    <Link href={href} className="tlink" onClick={(e) => e.stopPropagation()}>
      {children}
    </Link>
  );
}
