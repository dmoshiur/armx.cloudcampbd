import type { Metadata, Viewport } from "next";
import "./globals.css";
import { Providers } from "./providers";

// The platform ships without a font CDN dependency: Inter is used when the
// device has it, otherwise the system grotesk. Self-host Inter in /public/fonts
// and add an @font-face rule if you want byte-identical typography everywhere.

export const metadata: Metadata = {
  title: "A.R.M.X AI",
  description: "A Claude-powered assistant platform with a consent-first tool gateway.",
  applicationName: "A.R.M.X AI",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#0B1220",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark" suppressHydrationWarning>
      <body className="min-h-full font-sans">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
