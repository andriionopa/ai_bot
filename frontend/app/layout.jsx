import "./globals.css";

export const metadata = {
  title: "StogramGPT",
  description: "Telegram account automation workspace",
};

export default function RootLayout({ children }) {
  return (
    <html lang="uk">
      <body>{children}</body>
    </html>
  );
}
