import React from 'react';

/** Shared layout for login/signup pages. Ensures consistent, modern UI across all auth flows. */
export const AuthCardLayout: React.FC<{
  /** Left panel content (hidden on mobile). Use for role-specific info. */
  leftPanel?: React.ReactNode;
  /** Form or main content. */
  children: React.ReactNode;
  /** Min height of the card (default 520px for login, can be higher for signup). */
  minHeight?: string;
  /** Max width of the card (default 5xl for two-column, 2xl for single). Use 6xl/7xl for form-heavy pages. */
  maxWidth?: '2xl' | '4xl' | '5xl' | '6xl' | '7xl';
  /** Single column (no left panel) - e.g. ResetPassword, RegisterManagerLanding. */
  singleColumn?: boolean;
}> = ({ leftPanel, children, minHeight = '520px', maxWidth = '5xl', singleColumn = false }) => {
  const maxW =
    maxWidth === '2xl' ? 'max-w-2xl'
    : maxWidth === '4xl' ? 'max-w-4xl'
    : maxWidth === '6xl' ? 'max-w-6xl'
    : maxWidth === '7xl' ? 'max-w-7xl'
    : 'max-w-5xl';
  const showLeftPanel = !singleColumn && leftPanel;
  return (
    <div
      className={`w-full ${maxW} flex rounded-2xl overflow-hidden bg-white/80 backdrop-blur-md border border-slate-200/80 shadow-xl ${singleColumn ? 'flex-col' : ''}`}
      style={{ minHeight: singleColumn ? undefined : minHeight }}
    >
      {showLeftPanel && (
        <div className="hidden lg:flex w-[38%] min-w-[300px] flex-col justify-center p-10 bg-gradient-to-br from-slate-50/90 via-white/90 to-slate-50/90 backdrop-blur-sm border-r border-slate-200/80">
          {leftPanel}
        </div>
      )}
      <div className={`flex-1 flex flex-col justify-center p-8 md:p-10 min-w-0 ${singleColumn ? '' : 'lg:w-[62%]'}`}>
        {children}
      </div>
    </div>
  );
};

/** Bullet list item for left panel. */
export const AuthBullet: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <li className="flex items-center gap-3 text-sm text-slate-600">
    <span className="flex h-2 w-2 shrink-0 rounded-full bg-[#6B90F2]" />
    {children}
  </li>
);
