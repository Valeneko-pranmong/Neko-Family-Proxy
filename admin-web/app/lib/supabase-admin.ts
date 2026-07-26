import { createClient, type SupabaseClient } from "@supabase/supabase-js";

type QueryParameters = Record<string, string>;

export type AdminActor = {
  id: string;
  email: string;
};

let adminClient: SupabaseClient | null = null;

function configuration() {
  const url = process.env.SUPABASE_URL?.trim() ?? "";
  const secretKey = process.env.SUPABASE_SECRET_KEY?.trim() ?? "";
  if (!url || !secretKey) {
    throw new Error("Supabase admin connection is not configured");
  }
  return { url, secretKey };
}

function client(): SupabaseClient {
  if (adminClient) return adminClient;
  const { url, secretKey } = configuration();
  adminClient = createClient(url, secretKey, {
    auth: {
      autoRefreshToken: false,
      persistSession: false,
      detectSessionInUrl: false,
    },
  });
  return adminClient;
}

export function isSupabaseConfigured(): boolean {
  return Boolean(
    process.env.SUPABASE_URL?.trim() &&
      process.env.SUPABASE_SECRET_KEY?.trim(),
  );
}

export async function tableGet<T>(
  table: string,
  parameters: QueryParameters,
): Promise<T> {
  const select = parameters.select ?? "*";
  let query = client().from(table).select(select);
  for (const [column, expression] of Object.entries(parameters)) {
    if (column === "select" || column === "order" || column === "limit") {
      continue;
    }
    const separator = expression.indexOf(".");
    const operator = separator === -1 ? "eq" : expression.slice(0, separator);
    const value = separator === -1 ? expression : expression.slice(separator + 1);
    if (operator === "eq") query = query.eq(column, value);
    else if (operator === "is" && value === "null") query = query.is(column, null);
    else throw new Error(`Unsupported Supabase filter: ${operator}`);
  }

  if (parameters.order) {
    const [column, direction] = parameters.order.split(".");
    query = query.order(column, { ascending: direction !== "desc" });
  }
  if (parameters.limit) {
    query = query.limit(Number(parameters.limit));
  }

  const { data, error } = await query;
  if (error) throw error;
  return (data ?? []) as T;
}

export async function tableCount(
  table: string,
  parameters: QueryParameters = {},
): Promise<number> {
  let query = client().from(table).select("*", {
    count: "exact",
    head: true,
  });
  for (const [column, expression] of Object.entries(parameters)) {
    const separator = expression.indexOf(".");
    const operator = separator === -1 ? "eq" : expression.slice(0, separator);
    const value = separator === -1 ? expression : expression.slice(separator + 1);
    if (operator === "eq") query = query.eq(column, value);
    else if (operator === "is" && value === "null") query = query.is(column, null);
    else throw new Error(`Unsupported Supabase filter: ${operator}`);
  }
  const { count, error } = await query;
  if (error) throw error;
  return count ?? 0;
}

export async function authAdminGet<T>(
  path: "users",
  parameters: QueryParameters,
): Promise<T> {
  if (path !== "users") throw new Error("Unsupported Auth Admin resource");
  const { data, error } = await client().auth.admin.listUsers({
    page: Number(parameters.page ?? "1"),
    perPage: Number(parameters.per_page ?? "1000"),
  });
  if (error) throw error;
  return data as T;
}

export async function resolveAdminActor(
  email: string,
): Promise<AdminActor | null> {
  const normalizedEmail = email.trim().toLowerCase();
  const { data, error } = await client().auth.admin.listUsers({
    page: 1,
    perPage: 1000,
  });
  if (error) throw error;
  const user = data.users.find(
    (candidate) => candidate.email?.trim().toLowerCase() === normalizedEmail,
  );
  if (!user) return null;

  const { data: profile, error: profileError } = await client()
    .from("profiles")
    .select("id,role,status")
    .eq("id", user.id)
    .maybeSingle();
  if (profileError) throw profileError;
  if (!profile || profile.role !== "admin" || profile.status !== "active") {
    return null;
  }
  return { id: user.id, email: normalizedEmail };
}

export async function adminRpc<T>(
  functionName: string,
  args: Record<string, unknown>,
): Promise<T> {
  const { data, error } = await client()
    .schema("launcher")
    .rpc(functionName, args);
  if (error) throw error;
  return data as T;
}
