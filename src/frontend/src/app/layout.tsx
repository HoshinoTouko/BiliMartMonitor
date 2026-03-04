import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "@/contexts/AuthContext";
import ClientToaster from "@/components/ClientToaster";

export const metadata: Metadata = {
  title: "BiliMartMonitor",
  description: "Bilibili C2C 市场监控管理系统",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>
        <AuthProvider>
          {children}
          <ClientToaster />
        </AuthProvider>
      </body>
    </html>
  );
}
