import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const templateRoot = new URL("../", import.meta.url);
process.env.ADMIN_EMAIL_ALLOWLIST ??= "admin@example.com";

async function render(pathname = "/", email = "admin@example.com") {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request(`http://localhost${pathname}`, {
      headers: {
        accept: "text/html",
        "oai-authenticated-user-email": email,
      },
    }),
    {
      ASSETS: {
        fetch: async () => new Response("Not found", { status: 404 }),
      },
    },
    {
      waitUntil() {},
      passThroughOnException() {},
    },
  );
}

test("server-renders the Thai white admin dashboard", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<html lang="th">/i);
  assert.match(html, /ภาพรวม/);
  assert.match(html, /สมาชิก/);
  assert.match(html, /คูปอง/);
  assert.match(html, /คู่มือการใช้งาน/);
  assert.doesNotMatch(html, /codex-preview|Your site is taking shape|Building your site/i);
});

test("server-renders the Thai usage guide", async () => {
  const response = await render("/guide");
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /คู่มือ Neko Control/);
  assert.match(html, /สร้างคูปองให้ลูกค้า/);
  assert.match(html, /ข้อควรระวังด้านความปลอดภัย/);
});

test("keeps the Thai white theme and guide route in source", async () => {
  const [css, layout, page, guide, packageJson] = await Promise.all([
    readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/guide/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../package.json", import.meta.url), "utf8"),
  ]);

  assert.match(css, /--canvas:\s*#fffafd/);
  assert.match(css, /--panel:\s*#ffffff/);
  assert.match(css, /Thai white workspace theme/);
  assert.match(layout, /<html lang="th">/);
  assert.match(page, /ภาพรวมระบบจัดการ/);
  assert.match(guide, /คู่มือการใช้งาน/);
  assert.doesNotMatch(packageJson, /react-loading-skeleton/);
  await assert.rejects(
    readFile(new URL("app/_sites-preview/SkeletonPreview.tsx", templateRoot)),
  );
});

test("denies a workspace user who is not on the admin allowlist", async () => {
  const response = await render("/", "intruder@example.com");
  assert.equal(response.status, 200);
  const html = await response.text();
  assert.match(html, /บัญชีนี้ไม่มีสิทธิ์ผู้ดูแลระบบ/);
});

test("keeps admin mutations behind allowlist, role checks, and RPCs", async () => {
  const [route, adminAuth, migration] = await Promise.all([
    readFile(new URL("../app/api/admin/route.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/lib/admin-auth.ts", import.meta.url), "utf8"),
    readFile(
      new URL(
        "../../supabase/migrations/20260725134935_secure_admin_operations.sql",
        import.meta.url,
      ),
      "utf8",
    ),
  ]);

  assert.match(route, /adminRpc/);
  assert.doesNotMatch(route, /tablePatch|tablePost|crypto\.subtle/);
  assert.match(adminAuth, /ADMIN_EMAIL_ALLOWLIST/);
  assert.match(adminAuth, /resolveAdminActor/);
  assert.match(migration, /admin_generate_coupon_batch/);
  assert.match(migration, /admin_revoke_coupon_batch/);
  assert.match(migration, /grant execute[\s\S]+to service_role/);
  assert.match(migration, /from public, anon, authenticated/);
});
