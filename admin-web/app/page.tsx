import type { Metadata } from "next";
import AdminDashboard from "./admin-dashboard";
import { requireChatGPTUser } from "./chatgpt-auth";
import { getAdminViewer } from "./lib/admin-auth";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "ภาพรวม | Neko Control",
  description: "หน้าภาพรวมระบบจัดการ Neko Family Proxy สำหรับผู้ดูแล",
};

export default async function Home() {
  const authenticatedUser = await requireChatGPTUser("/");
  const viewer = await getAdminViewer(authenticatedUser);

  if (!viewer) {
    return (
      <main className="access-denied">
        <section>
          <span>NEKO CONTROL</span>
          <h1>บัญชีนี้ไม่มีสิทธิ์ผู้ดูแลระบบ</h1>
          <p>
            โปรดใช้บัญชีที่อยู่ในรายชื่อผู้ดูแลและมีบทบาท Admin ที่เปิดใช้งาน
          </p>
        </section>
      </main>
    );
  }

  return <AdminDashboard viewerName={viewer.displayName} />;
}
