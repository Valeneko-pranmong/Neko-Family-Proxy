const now = new Date();
const hoursAgo = (hours: number) =>
  new Date(now.getTime() - hours * 60 * 60 * 1000).toISOString();
const daysFromNow = (days: number) =>
  new Date(now.getTime() + days * 24 * 60 * 60 * 1000).toISOString();

export const demoUsers = [
  {
    id: "demo-user-1",
    display_name: "Neko Admin",
    email: "admin@example.com",
    role: "admin",
    status: "active",
    created_at: hoursAgo(720),
  },
  {
    id: "demo-user-2",
    display_name: "สมาชิกตัวอย่าง",
    email: "member@example.com",
    role: "customer",
    status: "active",
    created_at: hoursAgo(168),
  },
];

export const demoLicenses = [
  {
    id: "demo-license-1",
    email: "member@example.com",
    product: "Neko Family Proxy",
    product_code: "neko-family-proxy",
    status: "active",
    valid_until: daysFromNow(28),
    devices: "1 / 1",
  },
];

export const demoCoupons = [
  {
    id: "demo-coupon-1",
    batch_id: "demo-batch-1",
    batch: "ชุดทดลองเดือนกรกฎาคม",
    product: "Neko Family Proxy",
    days: 30,
    status: "active",
    used_by: "—",
    created_at: hoursAgo(24),
  },
  {
    id: "demo-coupon-2",
    batch_id: "demo-batch-1",
    batch: "ชุดทดลองเดือนกรกฎาคม",
    product: "Neko Family Proxy",
    days: 30,
    status: "redeemed",
    used_by: "member@example.com",
    created_at: hoursAgo(24),
  },
];

export const demoSessions = [
  {
    id: "demo-session-1",
    email: "member@example.com",
    device: "Windows PC",
    last_seen_at: hoursAgo(0),
    created_at: hoursAgo(3),
    status: "active",
    revoked_at: null,
  },
];

export const demoOverview = {
  configured: false,
  stats: {
    users: 2,
    activeLicenses: 1,
    activeSessions: 1,
    unusedCoupons: 1,
  },
  trend: [32, 48, 45, 67, 74, 91, 86, 110, 104, 126, 119, 138],
  recent: [
    {
      id: "demo-event-1",
      type: "session_claimed",
      event_type: "session_claimed",
      title: "มีการเปิดเซสชัน Launcher",
      detail: "สมาชิกตัวอย่างเริ่มใช้งานจาก Windows PC",
      time: hoursAgo(0),
      created_at: hoursAgo(0),
      tone: "blue",
    },
    {
      id: "demo-event-2",
      type: "coupon_redeemed",
      event_type: "coupon_redeemed",
      title: "ใช้คูปองสำเร็จ",
      detail: "เพิ่มสิทธิ์ Neko Family Proxy จำนวน 30 วัน",
      time: hoursAgo(2),
      created_at: hoursAgo(2),
      tone: "green",
    },
  ],
};
