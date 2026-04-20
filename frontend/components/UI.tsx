
import React from 'react';
import { createPortal } from 'react-dom';

export const Card: React.FC<{ children: React.ReactNode; className?: string; onClick?: () => void; role?: string }> = ({ children, className, onClick, role }) => (
  <div
    role={role}
    className={`bg-white border border-gray-200 rounded-xl shadow-sm overflow-hidden ${className}`}
    onClick={onClick}
  >
    {children}
  </div>
);

export const Button: React.FC<{ 
  onClick?: () => void; 
  children: React.ReactNode; 
  variant?: 'primary' | 'secondary' | 'outline' | 'danger' | 'ghost';
  type?: 'button' | 'submit';
  disabled?: boolean;
  className?: string;
}> = ({ onClick, children, variant = 'primary', type = 'button', disabled, className }) => {
  const baseStyles = "px-4 py-2.5 rounded-lg text-sm font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-offset-white disabled:opacity-50 disabled:cursor-not-allowed";
  
  const variants = {
    primary: "bg-[#6B90F2] hover:bg-[#5a7ed9] text-white focus:ring-[#6B90F2]",
    secondary: "bg-blue-100 hover:bg-blue-200 text-blue-800 border border-blue-300 focus:ring-blue-500",
    outline: "bg-white border border-gray-300 text-gray-700 hover:bg-gray-50 focus:ring-gray-400",
    danger: "bg-red-600 hover:bg-red-700 text-white focus:ring-red-500",
    ghost: "text-gray-600 hover:text-gray-900 bg-transparent px-2 py-1",
  };

  return (
    <button 
      type={type} 
      onClick={onClick} 
      disabled={disabled}
      className={`${baseStyles} ${variants[variant]} ${className}`}
    >
      {children}
    </button>
  );
};

export const Input: React.FC<{
  label: string;
  name: string;
  type?: string;
  value: string;
  onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => void;
  onKeyDown?: (e: React.KeyboardEvent<HTMLInputElement | HTMLSelectElement>) => void;
  error?: string;
  placeholder?: string;
  options?: { value: string; label: string }[];
  required?: boolean;
  className?: string;
  disabled?: boolean;
  readOnly?: boolean;
  min?: string;
  max?: string;
  minLength?: number;
}> = ({ label, name, type = 'text', value, onChange, onKeyDown, error, placeholder, options, required, className, disabled, readOnly, min, max, minLength }) => (
  <div className={`mb-4 min-w-0 ${className}`}>
    <label htmlFor={name} className="block text-sm font-medium text-slate-700 mb-1.5">
      {label} {required && <span className="text-red-500">*</span>}
    </label>
    {options ? (
      <select
        id={name}
        name={name}
        value={value}
        onChange={onChange}
        disabled={disabled}
        className={`w-full px-4 py-2.5 bg-white border rounded-lg text-gray-900 placeholder-gray-400 appearance-none focus:ring-2 focus:ring-[#6B90F2] focus:border-[#6B90F2] outline-none transition-colors ${error ? 'border-red-500' : 'border-slate-200'} ${disabled ? 'opacity-50 cursor-not-allowed' : ''}`}
      >
        <option value="" className="bg-white text-gray-900">Select {label}</option>
        {options.map(opt => <option key={opt.value} value={opt.value} className="bg-white text-gray-900">{opt.label}</option>)}
      </select>
    ) : (
      <input
        id={name}
        name={name}
        type={type}
        value={value}
        onChange={onChange}
        onKeyDown={onKeyDown}
        placeholder={placeholder}
        disabled={disabled}
        readOnly={readOnly}
        min={min}
        max={max}
        minLength={minLength}
        className={`w-full px-4 py-2.5 bg-white border rounded-lg text-gray-900 placeholder-gray-400 focus:ring-2 focus:ring-[#6B90F2] focus:border-[#6B90F2] outline-none transition-colors ${error ? 'border-red-500' : 'border-slate-200'} ${disabled ? 'opacity-50 cursor-not-allowed' : ''} ${readOnly ? 'bg-slate-50 cursor-default' : ''}`}
      />
    )}
    {error && (
      <p className="mt-1.5 text-xs text-red-400 flex items-center gap-1 ml-1">
        <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clipRule="evenodd" /></svg>
        {error}
      </p>
    )}
  </div>
);

export const LoadingOverlay: React.FC<{ message?: string }> = ({ message = "Loading..." }) => (
  <div className="fixed inset-0 bg-white/80 z-50 flex flex-col items-center justify-center">
    <div className="relative">
      <div className="w-10 h-10 border-2 border-gray-200 rounded-full"></div>
      <div className="w-10 h-10 border-2 border-t-gray-700 rounded-full animate-spin absolute top-0 left-0"></div>
    </div>
    <p className="mt-4 text-gray-600 text-sm font-medium">{message}</p>
  </div>
);

export const Modal: React.FC<{
  open: boolean;
  title?: string;
  children: React.ReactNode;
  onClose: () => void;
  className?: string;
  /** When true, clicking the backdrop does not close the modal (e.g. while submitting or showing result) */
  disableBackdropClose?: boolean;
}> = ({ open, title, children, onClose, className, disableBackdropClose = false }) => {
  if (!open) return null;
  return createPortal(
    <div className="fixed inset-0 z-[100]">
      <div className="absolute inset-0 bg-slate-900/60" onClick={disableBackdropClose ? undefined : onClose} aria-hidden="true" />
      <div className="absolute inset-0 p-4 flex items-center justify-center pointer-events-none">
        <div className={`w-full max-w-4xl bg-white border border-gray-200 rounded-xl shadow-lg overflow-hidden pointer-events-auto ${className || ""}`} onClick={(e) => e.stopPropagation()}>
          <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
            <div className="min-w-0">
              <h2 className="text-lg font-semibold text-gray-900 truncate">{title || "Modal"}</h2>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="p-2 rounded-lg text-gray-500 hover:text-gray-900 hover:bg-gray-100 transition-colors"
              aria-label="Close"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
          {children}
        </div>
      </div>
    </div>,
    document.body
  );
};

/** Reusable error modal for auth and form errors. */
export const ErrorModal: React.FC<{
  open: boolean;
  title?: string;
  message: React.ReactNode;
  onClose: () => void;
  /**
   * When both are set, footer is [Cancel] [actionLabel] (error-style destructive primary).
   * When omitted, a single OK button is shown.
   */
  actionLabel?: string;
  onAction?: () => void | Promise<void>;
  cancelLabel?: string;
  /** Block backdrop / header close while e.g. a request is in flight */
  disableBackdropClose?: boolean;
  /** Disable footer buttons (e.g. while submitting) */
  primaryDisabled?: boolean;
}> = ({
  open,
  title = "Error",
  message,
  onClose,
  actionLabel,
  onAction,
  cancelLabel = "Cancel",
  disableBackdropClose = false,
  primaryDisabled = false,
}) => {
  if (!open) return null;
  const hasDualFooter = Boolean(actionLabel && onAction);
  return createPortal(
    <div className="fixed inset-0 z-[200]">
      <div
        className="absolute inset-0 bg-slate-900/60"
        onClick={disableBackdropClose ? undefined : onClose}
        aria-hidden
      />
      <div className="absolute inset-0 p-4 flex items-center justify-center">
        <div
          className="w-full max-w-md bg-white border border-red-200 rounded-xl shadow-lg overflow-hidden"
          role="alertdialog"
          aria-labelledby="error-modal-title"
          aria-describedby="error-modal-desc"
        >
          <div className="flex items-center gap-3 px-6 py-4 border-b border-red-100 bg-red-50/50">
            <div className="w-10 h-10 rounded-full bg-red-100 flex items-center justify-center flex-shrink-0">
              <svg className="w-5 h-5 text-red-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
            <h2 id="error-modal-title" className="text-lg font-semibold text-red-900">{title}</h2>
            <button
              type="button"
              onClick={onClose}
              disabled={disableBackdropClose}
              className="ml-auto p-2 rounded-lg text-red-600 hover:text-red-800 hover:bg-red-100 transition-colors disabled:opacity-40 disabled:pointer-events-none"
              aria-label="Close"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
          <div className="px-6 py-4">
            {typeof message === "string" ? (
              <p id="error-modal-desc" className="text-slate-700 leading-relaxed whitespace-pre-line">
                {message}
              </p>
            ) : (
              <div id="error-modal-desc" className="text-slate-700 leading-relaxed">
                {message}
              </div>
            )}
            <div className="mt-6 flex justify-end gap-3 flex-wrap">
              {hasDualFooter ? (
                <>
                  <Button variant="outline" onClick={onClose} disabled={primaryDisabled}>
                    {cancelLabel}
                  </Button>
                  <Button
                    variant="danger"
                    onClick={() => {
                      void Promise.resolve(onAction?.());
                    }}
                    disabled={primaryDisabled}
                  >
                    {actionLabel}
                  </Button>
                </>
              ) : (
                <Button variant="primary" onClick={onClose} className="bg-red-600 hover:bg-red-700 focus:ring-red-500" disabled={primaryDisabled}>
                  OK
                </Button>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>,
    document.body
  );
};

/** Success modal for invite acceptance, property assignment, etc. */
export const SuccessModal: React.FC<{
  open: boolean;
  title?: string;
  message: string;
  onClose: () => void;
  /** Primary button label. Default "Continue" */
  buttonLabel?: string;
}> = ({ open, title = "Success", message, onClose, buttonLabel = "Continue" }) => {
  if (!open) return null;
  return createPortal(
    <div className="fixed inset-0 z-[200]">
      <div className="absolute inset-0 bg-slate-900/60" onClick={onClose} aria-hidden />
      <div className="absolute inset-0 p-4 flex items-center justify-center">
        <div
          className="w-full max-w-md bg-white border border-emerald-200 rounded-xl shadow-lg overflow-hidden"
          role="alertdialog"
          aria-labelledby="success-modal-title"
          aria-describedby="success-modal-desc"
        >
          <div className="flex items-center gap-3 px-6 py-4 border-b border-emerald-100 bg-emerald-50/50">
            <div className="w-10 h-10 rounded-full bg-emerald-100 flex items-center justify-center flex-shrink-0">
              <svg className="w-5 h-5 text-emerald-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <h2 id="success-modal-title" className="text-lg font-semibold text-emerald-900">{title}</h2>
          </div>
          <div className="px-6 py-4">
            <p id="success-modal-desc" className="text-slate-700 leading-relaxed">{message}</p>
            <div className="mt-6 flex justify-end">
              <Button variant="primary" onClick={onClose} className="bg-emerald-600 hover:bg-emerald-700 focus:ring-emerald-500">
                {buttonLabel}
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>,
    document.body
  );
};
