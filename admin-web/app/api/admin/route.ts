import { NextResponse } from "next/server";
import { getAdminViewer } from "../../lib/admin-auth";
import {
  authAdminGet,
  isSupabaseConfigured,
  tableCount,
  tableGet,
  tablePatch,
  tablePost,
} from "../../lib/supabase-admin";
import {
  demoCoupons,
  demoLicenses,
  demoOverview,
  demoSessions,
  demoUsers,
} from "../../lib/demo-data";

export const dynamic = "force-dynamic";

type AuthUser = {
  id: string;
  email?: string;
  created_at?: string;
};

type Profile = {
  id: string;
  display_name: string | null;
  role: string;
  status: string;
  created_at: string;
};

function jsonError(message: string, status = 400) {
  return NextResponse.json({ ok: false, error: message }, { status });
}

async function guard() {
  const viewer = await getAdminViewer();
  if (!viewer) return null;
  return viewer;
}

async function listAuthUsers(): Promise<AuthUser[]> {
  const result = await authAdminGet<{ users?: AuthUser[] }>("users", {
    page: "1",
    per_page: "1000",
  });
  return result.users ?? [];
}

async function getUsers() {
  const [profiles, authUsers] = await Promise.all([
    tableGet<Profile[]>("profiles", {
      select: "id,display_name,role,status,created_at",
      order: "created_at.desc",
      limit: "200",
    }),
    listAuthUsers(),
  ]);
  const emails = new Map(authUsers.map((user) => [user.id, user.email ?? ""]));
  return profiles.map((profile) => ({
    ...profile,
    email: emails.get(profile.id) ?? "—",
  }));
}

async function getLicenses() {
  const [licenses, products, authUsers] = await Promise.all([
    tableGet<
      Array<{
        id: string;
        user_id: string;
        product_id: string;
        status: string;
        valid_from: string;
        valid_until: string;
        max_devices: number | null;
        created_at: string;
      }>
    >("licenses", {
      select:
        "id,user_id,product_id,status,valid_from,valid_until,max_devices,created_at",
      order: "valid_until.desc",
      limit: "200",
    }),
    tableGet<Array<{ id: string; code: string; name: string }>>("products", {
      select: "id,code,name",
      order: "name.asc",
    }),
    listAuthUsers(),
  ]);
  const productMap = new Map(products.map((product) => [product.id, product]));
  const emailMap = new Map(authUsers.map((user) => [user.id, user.email ?? ""]));
  return licenses.map((license) => ({
    ...license,
    email: emailMap.get(license.user_id) ?? "—",
    product: productMap.get(license.product_id)?.name ?? "Unknown product",
    product_code: productMap.get(license.product_id)?.code ?? "unknown",
  }));
}

async function getCoupons() {
  const [coupons, batches, products, authUsers] = await Promise.all([
    tableGet<
      Array<{
        id: string;
        batch_id: string;
        status: string;
        redeemed_by: string | null;
        redeemed_at: string | null;
        created_at: string;
      }>
    >("coupons", {
      select: "id,batch_id,status,redeemed_by,redeemed_at,created_at",
      order: "created_at.desc",
      limit: "200",
    }),
    tableGet<
      Array<{
        id: string;
        product_id: string;
        duration_days: number;
        quantity: number;
        expires_at: string | null;
        note: string | null;
        created_at: string;
        revoked_at: string | null;
      }>
    >("coupon_batches", {
      select:
        "id,product_id,duration_days,quantity,expires_at,note,created_at,revoked_at",
      order: "created_at.desc",
      limit: "100",
    }),
    tableGet<Array<{ id: string; name: string; code: string }>>("products", {
      select: "id,name,code",
    }),
    listAuthUsers(),
  ]);
  const batchMap = new Map(batches.map((batch) => [batch.id, batch]));
  const productMap = new Map(products.map((product) => [product.id, product]));
  const emailMap = new Map(authUsers.map((user) => [user.id, user.email ?? ""]));
  return coupons.map((coupon) => {
    const batch = batchMap.get(coupon.batch_id);
    return {
      ...coupon,
      batch: batch?.note || batch?.id.slice(0, 8) || "—",
      product: batch ? productMap.get(batch.product_id)?.name ?? "Unknown" : "—",
      days: batch?.duration_days ?? 0,
      used_by: coupon.redeemed_by
        ? emailMap.get(coupon.redeemed_by) ?? coupon.redeemed_by
        : "—",
    };
  });
}

async function getSessions() {
  const [sessions, authUsers, installations] = await Promise.all([
    tableGet<
      Array<{
        id: string;
        user_id: string;
        installation_id: string;
        created_at: string;
        last_seen_at: string;
        revoked_at: string | null;
      }>
    >("launcher_sessions", {
      select:
        "id,user_id,installation_id,created_at,last_seen_at,revoked_at",
      order: "last_seen_at.desc",
      limit: "200",
    }),
    listAuthUsers(),
    tableGet<
      Array<{
        id: string;
        display_name: string | null;
      }>
    >("installations", {
      select: "id,display_name",
      limit: "200",
    }),
  ]);
  const emailMap = new Map(authUsers.map((user) => [user.id, user.email ?? ""]));
  const installationMap = new Map(
    installations.map((installation) => [
      installation.id,
      installation.display_name ?? "Unnamed device",
    ]),
  );
  return sessions.map((session) => ({
    ...session,
    email: emailMap.get(session.user_id) ?? "—",
    device: installationMap.get(session.installation_id) ?? "Unknown device",
  }));
}

async function getOverview() {
  const [users, activeLicenses, activeSessions, unusedCoupons, audit] =
    await Promise.all([
      tableCount("profiles"),
      tableCount("licenses", { status: "eq.active" }),
      tableCount("launcher_sessions", { revoked_at: "is.null" }),
      tableCount("coupons", { status: "eq.active" }),
      tableGet<
        Array<{
          id: number;
          event_type: string;
          metadata: Record<string, unknown>;
          created_at: string;
        }>
      >("audit_events", {
        select: "id,event_type,metadata,created_at",
        order: "created_at.desc",
        limit: "8",
      }),
    ]);
  return {
    configured: true,
    stats: { users, activeLicenses, activeSessions, unusedCoupons },
    recent: audit.map((event) => ({
      id: String(event.id),
      type: event.event_type,
      title: event.event_type.replaceAll("_", " "),
      detail: JSON.stringify(event.metadata),
      time: event.created_at,
      tone: event.event_type.includes("rejected") ? "red" : "blue",
    })),
  };
}

async function getAudit() {
  return tableGet<
    Array<{
      id: number;
      user_id: string | null;
      event_type: string;
      metadata: Record<string, unknown>;
      created_at: string;
    }>
  >("audit_events", {
    select: "id,user_id,event_type,metadata,created_at",
    order: "created_at.desc",
    limit: "200",
  });
}

function randomHex(bytes = 16): string {
  const values = new Uint8Array(bytes);
  crypto.getRandomValues(values);
  return Array.from(values, (value) => value.toString(16).padStart(2, "0"))
    .join("")
    .toUpperCase();
}

async function hashCode(value: string): Promise<string> {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(value),
  );
  return Array.from(new Uint8Array(digest), (value) =>
    value.toString(16).padStart(2, "0"),
  ).join("");
}

async function generateCoupons(body: {
  productCode: string;
  durationDays: number;
  quantity: number;
  expiresAt?: string | null;
  note?: string | null;
  createdBy?: string;
}) {
  const products = await tableGet<Array<{ id: string; code: string }>>(
    "products",
    { select: "id,code", code: `eq.${body.productCode}` },
  );
  const product = products[0];
  if (!product) throw new Error("Product not found");

  const codes = await Promise.all(
    Array.from({ length: body.quantity }, async () => {
      const secret = randomHex(16);
      const normalized = `NEKO${secret}`;
      return {
        code: `NEKO-${secret.slice(0, 8)}-${secret.slice(8, 16)}-${secret.slice(
          16,
          24,
        )}-${secret.slice(24, 32)}`,
        code_hash: await hashCode(normalized),
      };
    }),
  );

  const batches = await tablePost<
    Array<{ id: string; duration_days: number; quantity: number }>
  >("coupon_batches", {
    product_id: product.id,
    duration_days: body.durationDays,
    quantity: body.quantity,
    expires_at: body.expiresAt || null,
    note: body.note || null,
    created_by: body.createdBy || null,
  });
  const batch = batches[0];
  if (!batch) throw new Error("Could not create coupon batch");

  try {
    await tablePost(
      "coupons",
      codes.map((coupon) => ({ ...coupon, batch_id: batch.id })),
    );
  } catch (error) {
    await tablePatch(
      "coupon_batches",
      { id: `eq.${batch.id}` },
      { revoked_at: new Date().toISOString() },
    );
    throw error;
  }

  return {
    batch,
    codes: codes.map((coupon) => coupon.code),
  };
}

export async function GET(request: Request) {
  const viewer = await guard();
  if (!viewer) return jsonError("Admin access required", 403);

  const resource = new URL(request.url).searchParams.get("resource") ?? "overview";
  if (!isSupabaseConfigured()) {
    const demo = {
      overview: demoOverview,
      users: demoUsers,
      licenses: demoLicenses,
      coupons: demoCoupons,
      sessions: demoSessions,
      audit: demoOverview.recent,
    } as Record<string, unknown>;
    return NextResponse.json({
      ok: true,
      configured: false,
      resource,
      data: demo[resource] ?? demo.overview,
    });
  }

  try {
    const data =
      resource === "users"
        ? await getUsers()
        : resource === "licenses"
          ? await getLicenses()
          : resource === "coupons"
            ? await getCoupons()
            : resource === "sessions"
              ? await getSessions()
              : resource === "audit"
                ? await getAudit()
                : await getOverview();
    return NextResponse.json({ ok: true, configured: true, resource, data });
  } catch {
    return jsonError("Unable to load admin data", 502);
  }
}

export async function POST(request: Request) {
  const viewer = await guard();
  if (!viewer) return jsonError("Admin access required", 403);
  if (!isSupabaseConfigured()) {
    return jsonError("Supabase admin connection is not configured", 503);
  }

  try {
    const body = (await request.json()) as Record<string, unknown>;
    const action = String(body.action ?? "");

    if (action === "set_user_status") {
      await tablePatch(
        "profiles",
        { id: `eq.${String(body.userId)}` },
        { status: String(body.status) },
      );
      return NextResponse.json({ ok: true });
    }

    if (action === "revoke_license") {
      await tablePatch(
        "licenses",
        { id: `eq.${String(body.licenseId)}` },
        { status: "revoked" },
      );
      return NextResponse.json({ ok: true });
    }

    if (action === "extend_license") {
      const licenses = await tableGet<
        Array<{ id: string; valid_until: string }>
      >("licenses", {
        select: "id,valid_until",
        id: `eq.${String(body.licenseId)}`,
        limit: "1",
      });
      const current = licenses[0];
      if (!current) return jsonError("License not found", 404);
      const base = Math.max(Date.now(), Date.parse(current.valid_until));
      const days = Number(body.days);
      if (!Number.isFinite(days) || days < 1 || days > 3650) {
        return jsonError("Invalid extension days");
      }
      const validUntil = new Date(base + days * 86400000).toISOString();
      await tablePatch(
        "licenses",
        { id: `eq.${String(body.licenseId)}` },
        { valid_until: validUntil, status: "active" },
      );
      return NextResponse.json({ ok: true, valid_until: validUntil });
    }

    if (action === "revoke_session") {
      await tablePatch(
        "launcher_sessions",
        { id: `eq.${String(body.sessionId)}` },
        { revoked_at: new Date().toISOString() },
      );
      return NextResponse.json({ ok: true });
    }

    if (action === "revoke_batch") {
      await tablePatch(
        "coupon_batches",
        { id: `eq.${String(body.batchId)}` },
        { revoked_at: new Date().toISOString() },
      );
      await tablePatch(
        "coupons",
        { batch_id: `eq.${String(body.batchId)}`, status: "eq.active" },
        { status: "revoked" },
      );
      return NextResponse.json({ ok: true });
    }

    if (action === "generate_coupons") {
      const users = await listAuthUsers();
      const creator = users.find(
        (user) => user.email?.toLowerCase() === viewer.email.toLowerCase(),
      );
      const result = await generateCoupons({
        productCode: String(body.productCode),
        durationDays: Number(body.durationDays),
        quantity: Number(body.quantity),
        expiresAt: body.expiresAt ? String(body.expiresAt) : null,
        note: body.note ? String(body.note) : null,
        createdBy: creator?.id,
      });
      return NextResponse.json({ ok: true, ...result });
    }

    return jsonError("Unknown admin action");
  } catch {
    return jsonError("Admin action failed", 502);
  }
}
