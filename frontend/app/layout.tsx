import type { Metadata } from "next";
import { IBM_Plex_Mono, Public_Sans, Sora } from "next/font/google";
import "./globals.css";
import { TopNav } from "@/components/nav/TopNav";
import { cn } from "@/lib/utils";

const ibmPlexMono = IBM_Plex_Mono({ subsets: ["latin"], weight: ["400", "500", "600"], variable: "--font-mono" });

const publicSans = Public_Sans({
  variable: "--font-sans",
  subsets: ["latin"],
});

const sora = Sora({
  weight: ["500", "600", "700"],
  variable: "--font-heading",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Fathom",
  description: "Company fundamentals valuation",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={cn("h-full", "dark", "antialiased", publicSans.variable, sora.variable, ibmPlexMono.variable)}
    >
      <body className="min-h-full flex flex-col bg-page text-text-primary">
        <TopNav />
        <main className="flex flex-1 flex-col">{children}</main>
      </body>
    </html>
  );
}
