import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "推进 · 个人项目经理工作台",
  description: "多项目总览、里程碑与依赖、风险决策、信息收件箱及模拟飞书发布。",
  other: {
    "codex-preview": "development",
  },
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body className="antialiased">{children}</body>
    </html>
  );
}
