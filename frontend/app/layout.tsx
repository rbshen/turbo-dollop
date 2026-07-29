import type { Metadata } from "next";
import { Inter, JetBrains_Mono, Space_Grotesk } from "next/font/google";
import "./globals.css";
import { TopNav } from "@/components/nav/TopNav";
import { cn } from "@/lib/utils";

const jetbrainsMono = JetBrains_Mono({subsets:['latin'],variable:'--font-mono'});

const inter = Inter({
  variable: "--font-sans",
  subsets: ["latin"],
});

const spaceGrotesk = Space_Grotesk({
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
      className={cn("h-full", "dark", "antialiased", inter.variable, spaceGrotesk.variable, jetbrainsMono.variable)}
    >
      <body className="min-h-full flex flex-col bg-zinc-950">
        <TopNav />
        <main className="flex flex-1 flex-col">{children}</main>
      </body>
    </html>
  );
}
