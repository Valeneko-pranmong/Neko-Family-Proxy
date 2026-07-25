"use client";

import {
  Activity,
  ArrowUpRight,
  Ban,
  Check,
  Copy,
  KeyRound,
  LayoutDashboard,
  MonitorCog,
  MoreHorizontal,
  Plus,
  RefreshCcw,
  Search,
  Server,
  ShieldCheck,
  Ticket,
  UsersRound,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
  demoCoupons,
  demoLicenses,
  demoOverview,
  demoSessions,
  demoUsers,
} from "./lib/demo-data";

type Section =
  | "overview"
  | "users"
  | "licenses"
  | "coupons"
  | "sessions"
  | "audit";

type Row = Record<string, unknown>;

const navigation: Array<{
  id: Section;
  label: string;
  icon: typeof LayoutDashboard;
  count?: number;
}> = [
  { id: "overview", label: "ภาพรวม", icon: LayoutDashboard },
  { id: "users", label: "สมาชิก", icon: UsersRound, count: 1284 },
  { id: "licenses", label: "สิทธิ์ใช้งาน", icon: ShieldCheck, count: 916 },
  { id: "coupons", label: "คูปอง", icon: Ticket, count: 382 },
  { id: "sessions", label: "เซสชันออนไลน์", icon: MonitorCog, count: 143 },
  { id: "audit", label: "ประวัติการใช้งาน", icon: ScrollTextIcon },
];

function ScrollTextIcon(props: React.ComponentProps<typeof Activity>) {
  return <Activity {...props} />;
}

function stringValue(value: unknown, fallback = "-"): string {
  return value === null || value === undefined || value === ""
    ? fallback
    : String(value);
}

function formatDate(value: unknown): string {
  if (!value) return "-";
  const date = new Date(String(value));
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat("th-TH", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(date);
}

function formatDateTime(value: unknown): string {
  if (!value) return "-";
  const date = new Date(String(value));
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat("th-TH", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function StatusBadge({ value }: { value: unknown }) {
  const status = stringValue(value, "unknown").toLowerCase();
  const labels: Record<string, string> = {
    active: "ใช้งานอยู่",
    available: "พร้อมใช้งาน",
    redeemed: "ใช้แล้ว",
    suspended: "ระงับ",
    revoked: "ยกเลิกแล้ว",
    pending: "รอดำเนินการ",
    unknown: "ไม่ทราบสถานะ",
  };
  return <span className={`status ${status}`}>{labels[status] ?? status.replaceAll("_", " ")}</span>;
}

function StatCard({
  icon: Icon,
  label,
  value,
  foot,
  tone,
}: {
  icon: typeof UsersRound;
  label: string;
  value: string;
  foot: string;
  tone: string;
}) {
  return (
    <article className="stat-card">
      <div className="stat-card-header">
        <span>{label}</span>
        <span className={`stat-icon ${tone}`}>
          <Icon size={16} strokeWidth={1.8} />
        </span>
      </div>
      <div className="stat-number">{value}</div>
      <div className="stat-foot">{foot}</div>
    </article>
  );
}

function SectionHeading({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="panel-head">
      <div>
        <h2 className="panel-title">{title}</h2>
        <p className="panel-kicker">{subtitle}</p>
      </div>
      {action}
    </div>
  );
}

export default function AdminDashboard() {
  const [active, setActive] = useState<Section>("overview");
  const [search, setSearch] = useState("");
  const [configured, setConfigured] = useState(false);
  const [loading, setLoading] = useState(false);
  const [toast, setToast] = useState("");
  const [overview, setOverview] = useState(demoOverview);
  const [users, setUsers] = useState<Row[]>(demoUsers);
  const [licenses, setLicenses] = useState<Row[]>(demoLicenses);
  const [coupons, setCoupons] = useState<Row[]>(demoCoupons);
  const [sessions, setSessions] = useState<Row[]>(demoSessions);
  const [audit, setAudit] = useState<Row[]>(demoOverview.recent);
  const [couponModal, setCouponModal] = useState(false);
  const [generatedCodes, setGeneratedCodes] = useState<string[]>([]);
  const [couponForm, setCouponForm] = useState({
    productCode: "neko-family-proxy",
    durationDays: "30",
    quantity: "10",
    expiresAt: "",
    note: "",
  });

  async function loadSection(section: Section) {
    setLoading(true);
    try {
      const response = await fetch(`/api/admin?resource=${section}`, {
        cache: "no-store",
      });
      const payload = (await response.json()) as {
        ok?: boolean;
        configured?: boolean;
        data?: unknown;
      };
      if (!response.ok || !payload.ok) throw new Error("load");
      setConfigured(Boolean(payload.configured));
      const data = payload.data;
      if (section === "overview" && data) {
        const incoming = data as Partial<typeof demoOverview>;
        setOverview({
          ...demoOverview,
          ...incoming,
          stats: { ...demoOverview.stats, ...(incoming.stats ?? {}) },
          trend: Array.isArray(incoming.trend) ? incoming.trend : [],
          recent: Array.isArray(incoming.recent) ? incoming.recent : [],
        });
      } else if (section === "users" && Array.isArray(data)) {
        setUsers(data as Row[]);
      } else if (section === "licenses" && Array.isArray(data)) {
        setLicenses(data as Row[]);
      } else if (section === "coupons" && Array.isArray(data)) {
        setCoupons(data as Row[]);
      } else if (section === "sessions" && Array.isArray(data)) {
        setSessions(data as Row[]);
      } else if (section === "audit" && Array.isArray(data)) {
        setAudit(data as Row[]);
      }
    } catch {
      setToast("ไม่สามารถโหลดข้อมูลส่วนนี้ได้");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    const task = window.setTimeout(() => {
      void loadSection(active);
    }, 0);
    return () => window.clearTimeout(task);
  }, [active]);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(""), 3600);
    return () => window.clearTimeout(timer);
  }, [toast]);

  async function mutate(payload: Record<string, unknown>, reload = active) {
    if (!configured) {
      setToast("โหมดตัวอย่าง: เชื่อมต่อ Supabase secret key เพื่อเปิดใช้งานคำสั่ง");
      return;
    }
    try {
      const response = await fetch("/api/admin", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const result = (await response.json()) as {
        ok?: boolean;
        error?: string;
      };
      if (!response.ok || !result.ok) throw new Error(result.error ?? "action");
      setToast("ดำเนินการสำเร็จ");
      await loadSection(reload);
    } catch {
      setToast("ไม่สามารถดำเนินการได้");
    }
  }

  async function createCoupons() {
    if (!configured) {
      setToast("โหมดตัวอย่าง: เชื่อมต่อ Supabase ก่อนสร้างคูปอง");
      return;
    }
    try {
      const response = await fetch("/api/admin", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: "generate_coupons",
          productCode: couponForm.productCode,
          durationDays: Number(couponForm.durationDays),
          quantity: Number(couponForm.quantity),
          expiresAt: couponForm.expiresAt || null,
          note: couponForm.note || null,
        }),
      });
      const result = (await response.json()) as {
        ok?: boolean;
        codes?: string[];
      };
      if (!response.ok || !result.ok || !result.codes) throw new Error("coupon");
      setGeneratedCodes(result.codes);
      setToast("สร้างชุดคูปองแล้ว");
      await loadSection("coupons");
    } catch {
      setToast("ไม่สามารถสร้างชุดคูปองได้");
    }
  }

  async function copyCodes() {
    if (!generatedCodes.length) return;
    await navigator.clipboard.writeText(generatedCodes.join("\n"));
    setToast("คัดลอกรหัสคูปองแล้ว");
  }

  const filteredUsers = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return users;
    return users.filter((user) =>
      [user.email, user.display_name, user.status]
        .map((value) => stringValue(value).toLowerCase())
        .some((value) => value.includes(needle)),
    );
  }, [search, users]);

  const filteredLicenses = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return licenses;
    return licenses.filter((license) =>
      [license.email, license.product, license.status]
        .map((value) => stringValue(value).toLowerCase())
        .some((value) => value.includes(needle)),
    );
  }, [search, licenses]);

  const filteredCoupons = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return coupons;
    return coupons.filter((coupon) =>
      [coupon.batch, coupon.product, coupon.status, coupon.used_by]
        .map((value) => stringValue(value).toLowerCase())
        .some((value) => value.includes(needle)),
    );
  }, [coupons, search]);

  function renderOverview() {
    const stats = overview.stats;
    return (
      <>
        <div className="stats-grid">
          <StatCard
            icon={UsersRound}
            label="สมาชิกทั้งหมด"
            value={Number(stats.users).toLocaleString()}
            foot="บัญชีที่ลงทะเบียนทั้งหมด"
            tone="cyan"
          />
          <StatCard
            icon={ShieldCheck}
            label="สิทธิ์ที่ใช้งานอยู่"
            value={Number(stats.activeLicenses).toLocaleString()}
            foot="มีสิทธิ์ใช้งานในขณะนี้"
            tone="green"
          />
          <StatCard
            icon={Activity}
            label="เซสชันออนไลน์"
            value={Number(stats.activeSessions).toLocaleString()}
            foot="ส่งสัญญาณภายใน 90 วินาที"
            tone="blue"
          />
          <StatCard
            icon={Ticket}
            label="คูปองที่ยังไม่ใช้"
            value={Number(stats.unusedCoupons).toLocaleString()}
            foot="พร้อมส่งให้สมาชิก"
            tone="amber"
          />
        </div>

        <div className="content-grid">
          <section className="panel">
            <SectionHeading
              title="กิจกรรมเซสชัน"
              subtitle="เซสชัน Launcher ที่ทำงานอยู่ใน 12 ช่วงเวลาล่าสุด"
              action={
                <button
                  className="text-button"
                  onClick={() => void loadSection("overview")}
                >
                  รีเฟรช <RefreshCcw size={12} />
                </button>
              }
            />
            <div className="chart-wrap">
              <div className="chart" aria-label="กราฟกิจกรรมเซสชัน">
                {overview.trend.map((value, index) => (
                  <div
                    className="bar"
                    key={`${value}-${index}`}
                    style={
                      {
                        "--height": `${Math.max(16, (value / 150) * 100)}%`,
                      } as React.CSSProperties
                    }
                    title={`${value} เซสชัน`}
                  />
                ))}
              </div>
              <div className="chart-labels">
                <span>12 ช่วงเวลาก่อน</span>
                <span>ปัจจุบัน</span>
              </div>
            </div>
          </section>

          <section className="panel">
            <SectionHeading
              title="คำสั่งด่วน"
              subtitle="การจัดการที่ใช้บ่อย"
            />
            <div className="quick-actions">
              <button
                className="action-button"
                onClick={() => {
                  setGeneratedCodes([]);
                  setCouponModal(true);
                }}
              >
                <Ticket size={17} />
                <span className="action-copy">
                  <strong>สร้างคูปอง</strong>
                  <span>สร้างชุดคูปองเพื่อส่งรหัสให้สมาชิก</span>
                </span>
                <ArrowUpRight size={15} />
              </button>
              <button
                className="action-button"
                onClick={() => setActive("users")}
              >
                <UsersRound size={17} />
                <span className="action-copy">
                  <strong>ตรวจสอบสมาชิก</strong>
                  <span>ระงับหรือเปิดใช้งานบัญชี</span>
                </span>
                <ArrowUpRight size={15} />
              </button>
              <button
                className="action-button"
                onClick={() => setActive("sessions")}
              >
                <MonitorCog size={17} />
                <span className="action-copy">
                  <strong>ตรวจสอบเซสชันออนไลน์</strong>
                  <span>ยกเลิกการเชื่อมต่ออุปกรณ์ทันที</span>
                </span>
                <ArrowUpRight size={15} />
              </button>
            </div>
          </section>
        </div>

        <section className="panel" style={{ marginTop: 18 }}>
          <SectionHeading
            title="กิจกรรมล่าสุด"
            subtitle="เหตุการณ์ด้านความปลอดภัยและสิทธิ์ใช้งานล่าสุด"
            action={
              <button className="text-button" onClick={() => setActive("audit")}>
                เปิดประวัติการใช้งาน <ArrowUpRight size={12} />
              </button>
            }
          />
          <div className="activity-list">
            {overview.recent.map((event) => (
              <div className="activity-item" key={event.id}>
                <span className={`activity-dot ${event.tone}`} />
                <div className="activity-main">
                  <div className="activity-title">{event.title}</div>
                  <div className="activity-detail">{event.detail}</div>
                </div>
                <span className="activity-time">{event.time}</span>
              </div>
            ))}
          </div>
        </section>
      </>
    );
  }

  function renderUsers() {
    return (
      <section className="panel">
        <SectionHeading
          title="สมาชิก"
          subtitle="ตรวจสอบสถานะบัญชีและสิทธิ์การเข้าถึง"
          action={
            <button className="ghost-button" onClick={() => void loadSection("users")}>
              <RefreshCcw size={13} /> รีเฟรช
            </button>
          }
        />
        <div className="section-toolbar">
          <div className="toolbar-left">
            <button className="filter-button">สมาชิกทั้งหมด</button>
            <button className="filter-button">ใช้งานอยู่</button>
            <button className="filter-button">ถูกระงับ</button>
          </div>
          <span className="panel-kicker">{filteredUsers.length} รายการ</span>
        </div>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>สมาชิก</th>
                <th>บทบาท</th>
                <th>สถานะ</th>
                <th>วันที่สมัคร</th>
                <th>จัดการ</th>
              </tr>
            </thead>
            <tbody>
              {filteredUsers.map((user) => (
                <tr key={stringValue(user.id)}>
                  <td>
                    <span className="primary-cell">{stringValue(user.display_name, "ไม่ได้ระบุชื่อ")}</span>
                    <span className="secondary-cell">{stringValue(user.email)}</span>
                  </td>
                  <td>{stringValue(user.role)}</td>
                  <td><StatusBadge value={user.status} /></td>
                  <td>{formatDate(user.created_at)}</td>
                  <td>
                    <div className="row-actions">
                      <button
                        className="icon-button"
                        title={user.status === "suspended" ? "เปิดใช้งานสมาชิก" : "ระงับสมาชิก"}
                        onClick={() =>
                          void mutate({
                            action: "set_user_status",
                            userId: user.id,
                            status: user.status === "suspended" ? "active" : "suspended",
                          }, "users")
                        }
                      >
                        {user.status === "suspended" ? <Check size={14} /> : <Ban size={14} />}
                      </button>
                      <button className="icon-button" title="คำสั่งเพิ่มเติม">
                        <MoreHorizontal size={15} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    );
  }

  function renderLicenses() {
    return (
      <section className="panel">
        <SectionHeading
          title="สิทธิ์ใช้งาน"
          subtitle="ตรวจสอบสิทธิ์ผลิตภัณฑ์และวันหมดอายุ"
          action={
            <button className="ghost-button" onClick={() => void loadSection("licenses")}>
              <RefreshCcw size={13} /> รีเฟรช
            </button>
          }
        />
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>บัญชี</th>
                <th>ผลิตภัณฑ์</th>
                <th>สถานะ</th>
                <th>ใช้ได้ถึง</th>
                <th>อุปกรณ์</th>
                <th>จัดการ</th>
              </tr>
            </thead>
            <tbody>
              {filteredLicenses.map((license) => (
                <tr key={stringValue(license.id)}>
                  <td className="primary-cell">{stringValue(license.email)}</td>
                  <td>{stringValue(license.product)}</td>
                  <td><StatusBadge value={license.status} /></td>
                  <td>{formatDate(license.valid_until)}</td>
                  <td>{stringValue(license.devices, "1 / 1")}</td>
                  <td>
                    <div className="row-actions">
                      <button
                        className="icon-button"
                        title="ต่ออายุ 30 วัน"
                        onClick={() =>
                          void mutate({
                            action: "extend_license",
                            licenseId: license.id,
                            days: 30,
                          }, "licenses")
                        }
                      >
                        <Plus size={14} />
                      </button>
                      <button
                        className="icon-button"
                        title="ยกเลิกสิทธิ์ใช้งาน"
                        onClick={() =>
                          void mutate({
                            action: "revoke_license",
                            licenseId: license.id,
                          }, "licenses")
                        }
                      >
                        <Ban size={14} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    );
  }

  function renderCoupons() {
    return (
      <section className="panel">
        <SectionHeading
          title="คูปอง"
          subtitle="สร้าง ติดตาม และยกเลิกรหัสสิทธิ์ที่ออกโดยผู้ดูแล"
          action={
            <button className="primary-button" onClick={() => {
              setGeneratedCodes([]);
              setCouponModal(true);
            }}>
              <Plus size={14} /> สร้างชุดคูปอง
            </button>
          }
        />
        <div className="section-toolbar">
          <div className="toolbar-left">
            <button className="filter-button">รหัสทั้งหมด</button>
            <button className="filter-button">พร้อมใช้งาน</button>
            <button className="filter-button">ใช้แล้ว</button>
            <button className="filter-button">ยกเลิกแล้ว</button>
          </div>
          <span className="panel-kicker">{filteredCoupons.length} รายการ</span>
        </div>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>ชุดคูปอง</th>
                <th>ผลิตภัณฑ์</th>
                <th>ระยะเวลา</th>
                <th>สถานะ</th>
                <th>ผู้ใช้คูปอง</th>
                <th>วันที่สร้าง</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {filteredCoupons.map((coupon) => (
                <tr key={stringValue(coupon.id)}>
                  <td className="primary-cell">{stringValue(coupon.batch)}</td>
                  <td>{stringValue(coupon.product)}</td>
                  <td>{stringValue(coupon.days)} วัน</td>
                  <td><StatusBadge value={coupon.status} /></td>
                  <td>{stringValue(coupon.used_by)}</td>
                  <td>{formatDateTime(coupon.created_at)}</td>
                  <td>
                    {coupon.status === "available" && (
                      <button
                        className="icon-button"
                        title="ยกเลิกชุดคูปอง"
                        onClick={() =>
                          void mutate({
                            action: "revoke_batch",
                            batchId: coupon.batch_id,
                          }, "coupons")
                        }
                      >
                        <Ban size={14} />
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    );
  }

  function renderSessions() {
    return (
      <section className="panel">
        <SectionHeading
          title="เซสชันออนไลน์"
          subtitle="อุปกรณ์ที่เพิ่งส่งสัญญาณจาก Launcher"
          action={
            <button className="ghost-button" onClick={() => void loadSection("sessions")}>
              <RefreshCcw size={13} /> รีเฟรช
            </button>
          }
        />
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>สมาชิก</th>
                <th>อุปกรณ์</th>
                <th>สัญญาณล่าสุด</th>
                <th>เริ่มใช้งาน</th>
                <th>สถานะ</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {sessions.map((session) => (
                <tr key={stringValue(session.id)}>
                  <td className="primary-cell">{stringValue(session.email)}</td>
                  <td>
                    {stringValue(session.device)}
                    <span className="secondary-cell">{stringValue(session.ip, "ซ่อนหมายเลข IP")}</span>
                  </td>
                  <td>{stringValue(session.last_seen, formatDateTime(session.last_seen_at))}</td>
                  <td>{formatDateTime(session.created_at)}</td>
                  <td><StatusBadge value={session.status ?? (session.revoked_at ? "revoked" : "active")} /></td>
                  <td>
                    {!session.revoked_at && (
                      <button
                        className="icon-button"
                        title="ยกเลิกเซสชัน"
                        onClick={() =>
                          void mutate({
                            action: "revoke_session",
                            sessionId: session.id,
                          }, "sessions")
                        }
                      >
                        <Ban size={14} />
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    );
  }

  function renderAudit() {
    return (
      <section className="panel">
        <SectionHeading
          title="ประวัติการใช้งาน"
          subtitle="เหตุการณ์ด้านความปลอดภัยและสิทธิ์ใช้งาน"
          action={
            <button className="ghost-button" onClick={() => void loadSection("audit")}>
              <RefreshCcw size={13} /> รีเฟรช
            </button>
          }
        />
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>เหตุการณ์</th>
                <th>ผู้ดำเนินการ / สมาชิก</th>
                <th>รายละเอียด</th>
                <th>เวลา</th>
              </tr>
            </thead>
            <tbody>
              {audit.map((event) => (
                <tr key={stringValue(event.id)}>
                  <td><StatusBadge value={event.event_type ?? event.type} /></td>
                  <td className="primary-cell">{stringValue(event.user_id, "ระบบ")}</td>
                  <td className="secondary-cell">{stringValue(event.detail ?? event.metadata, "-")}</td>
                  <td>{formatDateTime(event.created_at ?? event.time)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    );
  }

  const currentTitle =
    navigation.find((item) => item.id === active)?.label ?? "ภาพรวม";

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">N</div>
          <div className="brand-copy">
            <strong>NEKO CONTROL</strong>
            <span>ระบบจัดการ Neko Family</span>
          </div>
        </div>
        <div className="nav-label">เมนูจัดการ</div>
        <nav className="nav" aria-label="เมนูผู้ดูแลระบบ">
          {navigation.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.id}
                className={active === item.id ? "active" : ""}
                onClick={() => {
                  setActive(item.id);
                  setSearch("");
                }}
              >
                <Icon size={16} strokeWidth={1.8} />
                <span>{item.label}</span>
                {item.count !== undefined && <span className="nav-count">{item.count}</span>}
              </button>
            );
          })}
        </nav>
        <div className="sidebar-footer">
          <div className="server-state">
            <span className="server-dot" />
            <span>ระบบออนไลน์</span>
          </div>
          <div className="panel-kicker" style={{ marginTop: 8 }}>
            Neko Family Proxy รุ่น 2
          </div>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div>
            <div className="eyebrow">Neko Family / ผู้ดูแลระบบ</div>
            <h1 className="page-title">{currentTitle}</h1>
            <p className="page-subtitle">
              จัดการสมาชิก สิทธิ์ใช้งาน คูปอง และเซสชันได้จากจุดเดียว
            </p>
          </div>
          <div className="topbar-actions">
            <label className="search">
              <Search size={15} />
              <input
                aria-label="ค้นหารายการ"
                placeholder="ค้นหาข้อมูล"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
            </label>
            <a className="guide-link" href="/guide">คู่มือการใช้งาน</a>
            <button className="icon-button" title="รีเฟรชหน้าปัจจุบัน" onClick={() => void loadSection(active)}>
              <RefreshCcw size={15} className={loading ? "spin" : ""} />
            </button>
            <div className="admin-chip">
              <span className="avatar">NF</span>
              <span>ผู้ดูแล</span>
            </div>
          </div>
        </header>

        {!configured && (
          <div className="demo-banner">
            <Server size={15} />
            <span>
              กำลังแสดงข้อมูลตัวอย่าง กรุณาตั้งค่า Supabase secret key ฝั่งเซิร์ฟเวอร์เพื่อเปิดใช้งานข้อมูลจริงและคำสั่งของผู้ดูแล
            </span>
          </div>
        )}

        {active === "overview" && renderOverview()}
        {active === "users" && renderUsers()}
        {active === "licenses" && renderLicenses()}
        {active === "coupons" && renderCoupons()}
        {active === "sessions" && renderSessions()}
        {active === "audit" && renderAudit()}
      </main>

      {couponModal && (
        <div className="modal-backdrop" role="presentation">
          <div className="modal" role="dialog" aria-modal="true" aria-labelledby="coupon-title">
            <div className="modal-head">
              <div>
                <h2 className="modal-title" id="coupon-title">
                  {generatedCodes.length ? "ชุดคูปองพร้อมใช้งาน" : "สร้างชุดคูปอง"}
                </h2>
                <p className="panel-kicker">
                  {generatedCodes.length
                    ? "กรุณาคัดลอกรหัสเหล่านี้ทันที ระบบจะไม่แสดงซ้ำอีก"
                    : "รหัสจะถูกสร้างอย่างปลอดภัยและจัดเก็บเป็นค่าแฮชเท่านั้น"}
                </p>
              </div>
              <button className="icon-button" title="ปิด" onClick={() => setCouponModal(false)}>
                <X size={15} />
              </button>
            </div>
            {generatedCodes.length ? (
              <>
                <div className="modal-body">
                  <div className="code-list">
                    {generatedCodes.map((code) => (
                      <div className="generated-code" key={code}>{code}</div>
                    ))}
                  </div>
                </div>
                <div className="modal-foot">
                  <button className="ghost-button" onClick={() => setCouponModal(false)}>ปิด</button>
                  <button className="primary-button" onClick={() => void copyCodes()}>
                    <Copy size={13} /> คัดลอกรหัส
                  </button>
                </div>
              </>
            ) : (
              <>
                <div className="modal-body">
                  <div className="field">
                    <label htmlFor="coupon-product">ผลิตภัณฑ์</label>
                    <select
                      id="coupon-product"
                      value={couponForm.productCode}
                      onChange={(event) => setCouponForm({ ...couponForm, productCode: event.target.value })}
                    >
                      <option value="neko-family-proxy">Neko Family Proxy</option>
                    </select>
                  </div>
                  <div className="two-fields">
                    <div className="field">
                      <label htmlFor="coupon-days">จำนวนวันใช้งาน</label>
                      <input id="coupon-days" type="number" min="1" max="3650" value={couponForm.durationDays} onChange={(event) => setCouponForm({ ...couponForm, durationDays: event.target.value })} />
                    </div>
                    <div className="field">
                      <label htmlFor="coupon-quantity">จำนวนคูปอง</label>
                      <input id="coupon-quantity" type="number" min="1" max="500" value={couponForm.quantity} onChange={(event) => setCouponForm({ ...couponForm, quantity: event.target.value })} />
                    </div>
                  </div>
                  <div className="field">
                    <label htmlFor="coupon-expiry">วันหมดอายุของคูปอง (ไม่บังคับ)</label>
                    <input id="coupon-expiry" type="date" value={couponForm.expiresAt} onChange={(event) => setCouponForm({ ...couponForm, expiresAt: event.target.value })} />
                  </div>
                  <div className="field">
                    <label htmlFor="coupon-note">หมายเหตุภายใน</label>
                    <textarea id="coupon-note" placeholder="ชื่อลูกค้า แคมเปญ หรือข้อมูลอ้างอิงการสนับสนุน" value={couponForm.note} onChange={(event) => setCouponForm({ ...couponForm, note: event.target.value })} />
                  </div>
                </div>
                <div className="modal-foot">
                  <button className="ghost-button" onClick={() => setCouponModal(false)}>ยกเลิก</button>
                  <button className="primary-button" onClick={() => void createCoupons()}>
                    <KeyRound size={13} /> สร้างรหัส
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {toast && (
        <div className="toast">
          <Check size={15} />
          <span>{toast}</span>
        </div>
      )}
    </div>
  );
}
