import type { Metadata } from "next";
import { Chakra_Petch, Share_Tech_Mono } from "next/font/google";

import "./globals.css";

const mono = Share_Tech_Mono({
  variable: "--font-mono",
  weight: "400",
  subsets: ["latin"],
});

const display = Chakra_Petch({
  variable: "--font-display",
  weight: ["500", "600"],
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Hole In Golf Dashboard",
  description: "Frontend visualizer for Hole In Golf agent orchestration.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${mono.variable} ${display.variable}`}>
      <body>{children}</body>
    </html>
  );
}
