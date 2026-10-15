import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Nightshift · FS-AI Evidence Console',
  description: 'Local progression, model justification, alterations, and deterministic evidence for the FS-AI Example Plate.',
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
