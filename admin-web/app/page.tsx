import type { Metadata } from "next";
import AdminDashboard from "./admin-dashboard";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "ภาพรวม | Neko Control",
  description: "หน้าภาพรวมระบบจัดการ Neko Family Proxy สำหรับผู้ดูแล",
};

export default function Home() {
  return <AdminDashboard />;
}
