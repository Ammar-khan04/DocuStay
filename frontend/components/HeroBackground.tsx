import React, { useState, useEffect } from 'react';

/** High-quality property/home images (Unsplash – free to use, no watermark) */
const HERO_IMAGES = [
  'https://images.unsplash.com/photo-1600596542815-ffad4c1539a9?w=1920&q=80',
  'https://images.unsplash.com/photo-1580587771525-78b9dba3b914?w=1920&q=80',
  'https://images.unsplash.com/photo-1600585154340-be6161a56a0c?w=1920&q=80',
  'https://images.unsplash.com/photo-1560448204-e02f11c3d0e2?w=1920&q=80',
  'https://images.unsplash.com/photo-1564013799919-ab600027ffc6?w=1920&q=80',
];

const CAROUSEL_INTERVAL_MS = 5000;

interface HeroBackgroundProps {
  children: React.ReactNode;
  /** Show carousel dot indicators at bottom (default true for landing, false for auth pages) */
  showDots?: boolean;
  /** Optional extra class for the content wrapper */
  className?: string;
}

/** Full-viewport background image carousel with dark overlay. Use as wrapper for landing or auth pages. */
export const HeroBackground: React.FC<HeroBackgroundProps> = ({
  children,
  showDots = false,
  className = '',
}) => {
  const [activeIndex, setActiveIndex] = useState(0);

  useEffect(() => {
    const t = setInterval(() => {
      setActiveIndex((i) => (i + 1) % HERO_IMAGES.length);
    }, CAROUSEL_INTERVAL_MS);
    return () => clearInterval(t);
  }, []);

  return (
    <div className={`relative min-h-[100dvh] flex items-center justify-center overflow-hidden ${className}`}>
      {/* Background slideshow */}
      <div className="absolute inset-0">
        {HERO_IMAGES.map((src, i) => (
          <div
            key={src}
            className={`absolute inset-0 bg-cover bg-center transition-opacity duration-1000 ease-out ${
              i === activeIndex ? 'opacity-100 z-0' : 'opacity-0 z-[-1]'
            }`}
            style={{ backgroundImage: `url(${src})` }}
            aria-hidden={i !== activeIndex}
          />
        ))}
        <div className="absolute inset-0 bg-slate-900/60 z-[1]" />
      </div>

      {/* Content on top */}
      <div className="relative z-10 w-full flex items-center justify-center p-4 py-8">
        {children}
      </div>

      {showDots && (
        <div className="absolute bottom-6 left-0 right-0 z-10 flex justify-center gap-2">
          {HERO_IMAGES.map((_, i) => (
            <button
              key={i}
              onClick={() => setActiveIndex(i)}
              className={`h-2 rounded-full transition-all duration-300 ${
                i === activeIndex ? 'w-8 bg-white' : 'w-2 bg-white/50 hover:bg-white/70'
              }`}
              aria-label={`Slide ${i + 1}`}
            />
          ))}
        </div>
      )}
    </div>
  );
};
