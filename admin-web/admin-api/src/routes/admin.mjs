import { createHash, randomBytes } from "node:crypto";
import {
  authAdminGet,
  tableCount,
  tableGet,
  tablePatch,
  tablePost,
} from "../supabase.mjs";

async function listAuthUsers() {
  const result = await authAdminGet("users", { page: "1", per_page: "1000" });
  return result.users ?? [];
}

async function getUsers() {
  const [profiles, authUsers] = await Promise.all([
    tableGet("profiles", {
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
    tableGet("licenses", {
      select:
        "id,user_id,product_id,status,valid_from,valid_until,max_devices,created_at",
      order: "valid_until.desc",
      limit: "200",
    }),
    tableGet("products", { select: "id,code,name", order: "name.asc" }),
    listAuthUsers(),
  ]);
  const productsById = new Map(products.map((product) => [product.id, product]));
  const emails = new Map(authUsers.map((user) => [user.id, user.email ?? ""]));
  return licenses.map((license) => ({
    ...license,
    email: emails.get(license.user_id) ?? "—",
    product: productsById.get(license.product_id)?.name ?? "Unknown product",
    product_code: productsById.get(license.product_id)?.code ?? "unknown",
  }));
}

async function getCoupons() {
  const [coupons, batches, products, authUsers] = await Promise.all([
    tableGet("coupons", {
      select: "id,batch_id,status,redeemed_by,redeemed_at,created_at",
      order: "created_at.desc",
      limit: "200",
    }),
    tableGet("coupon_batches", {
      select:
        "id,product_id,duration_days,quantity,expires_at,note,created_at,revoked_at",
      order: "created_at.desc",
      limit: "100",
    }),
    tableGet("products", { select: "id,name,code" }),
    listAuthUsers(),
  ]);
  const batchesById = new Map(batches.map((batch) => [batch.id, batch]));
  const productsById = new Map(products.map((product) => [product.id, product]));
  const emails = new Map(authUsers.map((user) => [user.id, user.email ?? ""]));
  return coupons.map((coupon) => {
    const batch = batchesById.get(coupon.batch_id);
    return {
      ...coupon,
      batch: batch?.note || batch?.id?.slice(0, 8) || "—",
      product: batch ? productsById.get(batch.product_id)?.name ?? "Unknown" : "—",
      days: batch?.duration_days ?? 0,
      used_by: coupon.redeemed_by
        ? emails.get(coupon.redeemed_by) ?? coupon.redeemed_by
        : "—",
    };
  });
}

async function getSessions() {
  const [sessions, authUsers, installations] = await Promise.all([
    tableGet("launcher_sessions", {
      select:
        "id,user_id,installation_id,created_at,last_seen_at,revoked_at",
      order: "last_seen_at.desc",
      limit: "200",
    }),
    listAuthUsers(),
    tableGet("installations", {
      select: "id,display_name",
      limit: "200",
    }),
  ]);
  const emails = new Map(authUsers.map((user) => [user.id, user.email ?? ""]));
  const devices = new Map(
    installations.map((installation) => [
      installation.id,
      installation.display_name ?? "Unnamed device",
    ]),
  );
  return sessions.map((session) => ({
    ...session,
    email: emails.get(session.user_id) ?? "—",
    device: devices.get(session.installation_id) ?? "Unknown device",
  }));
}

async function getOverview() {
  const [users, activeLicenses, activeSessions, unusedCoupons, audit] =
    await Promise.all([
      tableCount("profiles"),
      tableCount("licenses", { status: "eq.active" }),
      tableCount("launcher_sessions", { revoked_at: "is.null" }),
      tableCount("coupons", { status: "eq.active" }),
      tableGet("audit_events", {
        select: "id,event_type,metadata,created_at",
        order: "created_at.desc",
        limit: "8",
      }),
    ]);
  return {
    stats: { users, activeLicenses, activeSessions, unusedCoupons },
    trend: [],
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
  return tableGet("audit_events", {
    select: "id,user_id,event_type,metadata,created_at",
    order: "created_at.desc",
    limit: "200",
  });
}

function randomHex(bytes = 16) {
  return randomBytes(bytes).toString("hex").toUpperCase();
}

function hashCode(value) {
  return createHash("sha256").update(value).digest("hex");
}

async function generateCoupons(body, actor) {
  const productCode = String(body.productCode || "").toLowerCase();
  const durationDays = Number(body.durationDays);
  const quantity = Number(body.quantity);
  if (!/^[a-z0-9-]{3,64}$/.test(productCode)) throw new Error("Invalid product");
  if (!Number.isInteger(durationDays) || durationDays < 1 || durationDays > 3650) {
    throw new Error("Invalid duration");
  }
  if (!Number.isInteger(quantity) || quantity < 1 || quantity > 500) {
    throw new Error("Invalid quantity");
  }
  const products = await tableGet("products", {
    select: "id,code",
    code: `eq.${productCode}`,
  });
  const product = products[0];
  if (!product) throw new Error("Product not found");

  const codes = Array.from({ length: quantity }, () => {
    const secret = randomHex(16);
    return {
      code: `NEKO-${secret.slice(0, 8)}-${secret.slice(8, 16)}-${secret.slice(
        16,
        24,
      )}-${secret.slice(24, 32)}`,
      code_hash: hashCode(`NEKO${secret}`),
    };
  });
  const batches = await tablePost("coupon_batches", {
    product_id: product.id,
    duration_days: durationDays,
    quantity,
    expires_at: body.expiresAt ? String(body.expiresAt) : null,
    note: body.note ? String(body.note).slice(0, 500) : null,
    created_by: actor.userId,
  });
  const batch = batches[0];
  if (!batch) throw new Error("Could not create coupon batch");
  try {
    await tablePost("coupons", codes.map((coupon) => ({ ...coupon, batch_id: batch.id })));
  } catch (error) {
    await tablePatch("coupon_batches", { id: `eq.${batch.id}` }, { revoked_at: new Date().toISOString() });
    throw error;
  }
  return { batch, codes: codes.map((coupon) => coupon.code) };
}

export async function getResource(resource) {
  if (resource === "users") return getUsers();
  if (resource === "licenses") return getLicenses();
  if (resource === "coupons") return getCoupons();
  if (resource === "sessions") return getSessions();
  if (resource === "audit") return getAudit();
  return getOverview();
}

export async function performAction(body, actor) {
  const action = String(body.action || "");
  if (action === "set_user_status") {
    const status = String(body.status);
    if (!["active", "suspended", "banned"].includes(status)) throw new Error("Invalid status");
    await tablePatch("profiles", { id: `eq.${String(body.userId)}` }, { status });
    return {};
  }
  if (action === "revoke_license") {
    await tablePatch("licenses", { id: `eq.${String(body.licenseId)}` }, { status: "revoked" });
    return {};
  }
  if (action === "extend_license") {
    const licenses = await tableGet("licenses", {
      select: "id,valid_until",
      id: `eq.${String(body.licenseId)}`,
      limit: "1",
    });
    const current = licenses[0];
    if (!current) throw new Error("License not found");
    const days = Number(body.days);
    if (!Number.isInteger(days) || days < 1 || days > 3650) throw new Error("Invalid extension");
    const base = Math.max(Date.now(), Date.parse(current.valid_until));
    const validUntil = new Date(base + days * 86400000).toISOString();
    await tablePatch(
      "licenses",
      { id: `eq.${String(body.licenseId)}` },
      { valid_until: validUntil, status: "active" },
    );
    return { valid_until: validUntil };
  }
  if (action === "revoke_session") {
    await tablePatch(
      "launcher_sessions",
      { id: `eq.${String(body.sessionId)}` },
      { revoked_at: new Date().toISOString() },
    );
    return {};
  }
  if (action === "revoke_batch") {
    const batchId = String(body.batchId);
    await tablePatch("coupon_batches", { id: `eq.${batchId}` }, { revoked_at: new Date().toISOString() });
    await tablePatch(
      "coupons",
      { batch_id: `eq.${batchId}`, status: "eq.active" },
      { status: "revoked" },
    );
    return {};
  }
  if (action === "generate_coupons") return generateCoupons(body, actor);
  throw new Error("Unknown admin action");
}
