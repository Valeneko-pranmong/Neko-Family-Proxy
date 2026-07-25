import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { headers } from "next/headers";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export async function generateMetadata(): Promise<Metadata> {
  const requestHeaders = await headers();
  const host = requestHeaders.get("x-forwarded-host") ?? requestHeaders.get("host");
  const protocol = requestHeaders.get("x-forwarded-proto") ?? "https";
  const origin =
    process.env.SITE_URL ??
    (host ? `${protocol}://${host}` : "http://localhost:3000");

  return {
    metadataBase: new URL(origin),
    title: "Neko Control - ระบบจัดการ",
    description: "ระบบจัดการสมาชิก สิทธิ์ใช้งาน คูปอง และเซสชันของ Neko Family Proxy",
    icons: {
      icon: "/favicon.svg",
      shortcut: "/favicon.svg",
    },
    openGraph: {
      title: "Neko Control - ระบบจัดการ",
      description: "ระบบจัดการสมาชิก สิทธิ์ใช้งาน คูปอง และเซสชันสำหรับผู้ดูแล",
      type: "website",
      images: [
        {
          url: "/og.png",
          width: 1200,
          height: 630,
          alt: "Neko Control Room",
        },
      ],
    },
    twitter: {
      card: "summary_large_image",
      title: "Neko Control - ระบบจัดการ",
      description: "ระบบจัดการสมาชิก สิทธิ์ใช้งาน คูปอง และเซสชันสำหรับผู้ดูแล",
      images: ["/og.png"],
    },
  };
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="th">
      <body className={`${geistSans.variable} ${geistMono.variable}`}>
        {children}
      </body>
    </html>
  );
}
