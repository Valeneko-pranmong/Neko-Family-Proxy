import { sections } from "../config.js";
import { escapeHtml } from "./escape.js";

export function loginView(error = "") {
  return `
    <main class="auth-page">
      <section class="auth-card">
        <div class="brand-mark">NEKO CONTROL</div>
        <h1>เข้าสู่ระบบผู้ดูแล</h1>
        <p class="muted">ใช้บัญชี Supabase ที่มี role เป็น admin</p>
        <form id="login-form" class="stack">
          <label for="admin-email">อีเมล</label>
          <input id="admin-email" name="email" type="email" autocomplete="username" required />
          <label for="admin-password">รหัสผ่าน</label>
          <input id="admin-password" name="password" type="password" autocomplete="current-password" required />
          <button class="button button-primary" type="submit">เข้าสู่ระบบ</button>
          ${error ? `<div class="form-error">${escapeHtml(error)}</div>` : ""}
        </form>
      </section>
    </main>
  `;
}

export function shellView(active, viewer) {
  return `
    <div class="app-shell">
      <aside class="sidebar">
        <div class="brand">
          <div class="brand-mark">NEKO CONTROL</div>
          <div class="brand-subtitle">Local Admin Console</div>
        </div>
        <nav class="nav" aria-label="เมนูผู้ดูแล">
          ${sections
            .map(
              (section) =>
                `<button class="nav-item ${section.id === active ? "is-active" : ""}" data-section="${section.id}">${section.label}</button>`,
            )
            .join("")}
        </nav>
        <div class="sidebar-footer">
          <div class="admin-label">ผู้ดูแล: ${escapeHtml(viewer?.name || viewer?.email || "Admin")}</div>
          <button class="button button-ghost" data-action="logout">ออกจากระบบ</button>
        </div>
      </aside>
      <main class="main">
        <header class="topbar">
          <div>
            <div class="eyebrow">Neko Family Proxy</div>
            <h1>Control Room</h1>
          </div>
          <span class="local-chip">LOCAL ONLY</span>
        </header>
        <div id="content"></div>
      </main>
    </div>
    <div id="toast" class="toast" hidden></div>
  `;
}
