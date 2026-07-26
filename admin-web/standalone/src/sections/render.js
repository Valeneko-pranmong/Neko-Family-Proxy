import { escapeHtml } from "../ui/escape.js";
import { cell, dateCell, statusBadge, table } from "../ui/table.js";

function heading(title, subtitle, action = "") {
  return `
    <div class="section-head">
      <div><h2>${escapeHtml(title)}</h2><p class="muted">${escapeHtml(subtitle)}</p></div>
      ${action}
    </div>
  `;
}

function actionButton(action, id, label, extra = "") {
  return `<button class="button button-small ${extra}" data-action="${action}" data-id="${escapeHtml(id)}">${escapeHtml(label)}</button>`;
}

export function renderOverview(data = {}) {
  const stats = data.stats || {};
  const cards = [
    ["สมาชิก", stats.users ?? 0, "users"],
    ["License ที่ใช้งาน", stats.activeLicenses ?? 0, "active"],
    ["Session ออนไลน์", stats.activeSessions ?? 0, "session"],
    ["คูปองพร้อมใช้", stats.unusedCoupons ?? 0, "coupon"],
  ];
  const recent = (data.recent || []).map(
    (event) =>
      `<tr>${cell(event.title)}${cell(event.detail)}${dateCell(event.time)}</tr>`,
  );
  return `
    ${heading("ภาพรวมระบบ", "สถานะล่าสุดจากฐานข้อมูล")}
    <section class="stats-grid">${cards
      .map(([label, value, tone]) => `<article class="stat-card stat-${tone}"><span>${label}</span><strong>${value}</strong></article>`)
      .join("")}</section>
    <section class="panel">
      <div class="panel-title-row"><h3>กิจกรรมล่าสุด</h3></div>
      ${table(["รายการ", "รายละเอียด", "เวลา"], recent)}
    </section>
  `;
}

export function renderUsers(rows = []) {
  const body = rows.map(
    (row) =>
      `<tr>${cell(row.email, "primary")}${cell(row.display_name)}${cell(row.role)}<td>${statusBadge(row.status)}</td>${dateCell(row.created_at)}<td class="actions">${actionButton("toggle_user_status", row.id, row.status === "active" ? "ระงับ" : "เปิดใช้", row.status === "active" ? "button-danger" : "button-success")}</td></tr>`,
  );
  return `${heading("สมาชิก", "จัดการสถานะบัญชีลูกค้า")}${table(["อีเมล", "ชื่อ", "บทบาท", "สถานะ", "สร้างเมื่อ", "คำสั่ง"], body)}`;
}

export function renderLicenses(rows = []) {
  const body = rows.map(
    (row) =>
      `<tr>${cell(row.email, "primary")}${cell(row.product)}<td>${statusBadge(row.status)}</td>${dateCell(row.valid_until)}${cell(row.max_devices)}<td class="actions">${actionButton("extend_license", row.id, "ต่ออายุ")} ${actionButton("revoke_license", row.id, "ยกเลิก", "button-danger")}</td></tr>`,
  );
  return `${heading("สิทธิ์ใช้งาน", "ต่ออายุหรือยกเลิก License")}${table(["สมาชิก", "สินค้า", "สถานะ", "หมดอายุ", "อุปกรณ์", "คำสั่ง"], body)}`;
}

export function renderCoupons(rows = []) {
  const body = rows.map(
    (row) =>
      `<tr>${cell(row.batch)}${cell(row.product)}${cell(row.days)}<td>${statusBadge(row.status)}</td>${cell(row.used_by)}${dateCell(row.created_at)}<td class="actions">${row.status === "active" ? actionButton("revoke_batch", row.batch_id, "ยกเลิกชุด", "button-danger") : ""}</td></tr>`,
  );
  return `
    ${heading("คูปอง", "สร้างและยกเลิกชุดคูปอง", `<button class="button button-primary" data-action="show-coupon-form">สร้างคูปอง</button>`)}
    <div id="coupon-form-host"></div>
    ${table(["ชุด", "สินค้า", "วัน", "สถานะ", "ใช้โดย", "สร้างเมื่อ", "คำสั่ง"], body)}
  `;
}

export function couponForm() {
  return `
    <form id="coupon-form" class="panel inline-form">
      <label>Product code<input name="productCode" value="neko-family-proxy" required /></label>
      <label>จำนวนวัน<input name="durationDays" type="number" min="1" max="3650" value="30" required /></label>
      <label>จำนวนคูปอง<input name="quantity" type="number" min="1" max="500" value="10" required /></label>
      <label>หมายเหตุ<input name="note" maxlength="500" /></label>
      <div class="form-actions"><button class="button button-primary" type="submit">สร้าง</button><button class="button" type="button" data-action="hide-coupon-form">ยกเลิก</button></div>
    </form>
  `;
}

export function renderSessions(rows = []) {
  const body = rows.map(
    (row) =>
      `<tr>${cell(row.email, "primary")}${cell(row.device)}<td>${statusBadge(row.revoked_at ? "revoked" : "active")}</td>${dateCell(row.last_seen_at)}<td class="actions">${row.revoked_at ? "" : actionButton("revoke_session", row.id, "ยกเลิก", "button-danger")}</td></tr>`,
  );
  return `${heading("เซสชันออนไลน์", "ตรวจสอบและยกเลิกการเชื่อมต่อของเครื่องลูกค้า")}${table(["สมาชิก", "อุปกรณ์", "สถานะ", "ใช้งานล่าสุด", "คำสั่ง"], body)}`;
}

export function renderAudit(rows = []) {
  const body = rows.map(
    (row) =>
      `<tr>${cell(row.event_type)}${cell(JSON.stringify(row.metadata))}${dateCell(row.created_at)}</tr>`,
  );
  return `${heading("ประวัติการใช้งาน", "Audit log จากระบบ Launcher")}${table(["ประเภท", "รายละเอียด", "เวลา"], body)}`;
}

export function renderSection(section, data) {
  if (section === "users") return renderUsers(data);
  if (section === "licenses") return renderLicenses(data);
  if (section === "coupons") return renderCoupons(data);
  if (section === "sessions") return renderSessions(data);
  if (section === "audit") return renderAudit(data);
  return renderOverview(data);
}
