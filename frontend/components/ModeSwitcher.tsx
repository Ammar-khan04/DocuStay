import React from 'react';

const DISABLED_TOOLTIP = "Personal Mode is not available for your account.";

interface ModeSwitcherProps {
  contextMode: 'business' | 'personal';
  personalModeUnits: number[];
  onContextModeChange: (mode: 'business' | 'personal') => void;
  /** When true, use inline layout (e.g. in Settings card). Default: false (sidebar style). */
  inline?: boolean;
  /** When true, Personal mode is enabled (e.g. manager with at least one assigned property). When undefined, derived from personalModeUnits.length > 0. */
  canUsePersonal?: boolean;
}

export const ModeSwitcher: React.FC<ModeSwitcherProps> = ({
  contextMode,
  personalModeUnits,
  onContextModeChange,
  inline = false,
  canUsePersonal: canUsePersonalProp,
}) => {
  const canUsePersonal = canUsePersonalProp ?? true;

  if (contextMode === 'personal') {
    return (
      <div className={inline ? '' : 'mb-4 p-3 rounded-xl bg-slate-100 border border-slate-200'}>
        {!inline && <p className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-2">Mode</p>}
        <button
          type="button"
          onClick={() => onContextModeChange('business')}
          className={`w-full px-3 py-2 rounded-lg text-sm font-medium bg-slate-700 text-white hover:bg-slate-600 transition-colors ${inline ? '' : 'flex-1'}`}
        >
          Back to Business Mode
        </button>
      </div>
    );
  }

  const handlePersonalClick = () => {
    if (canUsePersonal) onContextModeChange('personal');
  };

  return (
    <div className={inline ? '' : 'mb-4 p-3 rounded-xl bg-slate-100 border border-slate-200'}>
      {!inline && <p className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-2">Mode</p>}
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => onContextModeChange('business')}
          className={`flex-1 px-3 py-2 rounded-lg text-sm font-medium bg-slate-700 text-white`}
        >
          Business
        </button>
        <span className={canUsePersonal ? '' : 'group relative flex-1'}>
          <button
            type="button"
            onClick={handlePersonalClick}
            disabled={!canUsePersonal}
            className={`w-full px-3 py-2 rounded-lg text-sm font-medium ${
              canUsePersonal
                ? 'bg-white text-slate-600 hover:bg-slate-50'
                : 'bg-white/60 text-slate-400 cursor-not-allowed'
            }`}
            title={!canUsePersonal ? DISABLED_TOOLTIP : undefined}
          >
            Personal
          </button>
          {!canUsePersonal && (
            <span
              className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1.5 px-3 py-1.5 bg-gray-900 text-white text-xs rounded shadow-lg min-w-64 max-w-80 whitespace-nowrap opacity-0 pointer-events-none group-hover:opacity-100 transition-opacity z-[200]"
              role="tooltip"
            >
              {DISABLED_TOOLTIP}
            </span>
          )}
        </span>
      </div>
    </div>
  );
};
