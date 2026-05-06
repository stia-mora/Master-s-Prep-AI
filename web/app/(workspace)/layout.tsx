import { WorkspaceAuthGate } from "@/components/auth/WorkspaceAuthGate";
import WorkspaceSidebar from "@/components/sidebar/WorkspaceSidebar";
import { UnifiedChatProvider } from "@/context/UnifiedChatContext";

export default function WorkspaceLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <WorkspaceAuthGate>
      <UnifiedChatProvider>
        <div className="flex h-screen overflow-hidden">
          <WorkspaceSidebar />
          <main className="flex-1 overflow-hidden bg-[var(--background)]">
            {children}
          </main>
        </div>
      </UnifiedChatProvider>
    </WorkspaceAuthGate>
  );
}
