"use client";

import type { ReactNode } from "react";
import * as React from "react";

import { useRouter } from "next/navigation";
import { auth } from "@/lib/auth";

import { MainContent } from "./_components/main-content";

export default function Layout({ children }: Readonly<{ children: ReactNode }>) {
  const router = useRouter();
  const [authed, setAuthed] = React.useState(false);
  React.useEffect(() => {
    if (auth.getToken()) {
      setAuthed(true);
    } else {
      auth.clearToken();
      router.replace("/login");
      router.refresh();
    }
  }, [router]);

  if (!authed) return null;

  return <MainContent>{children}</MainContent>;
}
