import { escapeHtml, display, formatDate } from "./escape.js";

export function table(headers, rows, empty = "ยังไม่มีข้อมูล") {
  if (!rows.length) return `<div class="empty">${escapeHtml(empty)}</div>`;
  return `
    <div class="table-wrap">
      <table>
        <thead><tr>${headers.map((header) => `<th>${escapeHtml(header)}</th>`).join("")}</tr></thead>
        <tbody>${rows.join("")}</tbody>
      </table>
    </div>
  `;
}

export const cell = (value, className = "") =>
  `<td class="${escapeHtml(className)}">${escapeHtml(display(value))}</td>`;

export const dateCell = (value) => cell(formatDate(value), "date-cell");

export const statusBadge = (value) => {
  const status = String(value || "unknown").toLowerCase();
  return `<span class="status status-${escapeHtml(status)}">${escapeHtml(status)}</span>`;
};
