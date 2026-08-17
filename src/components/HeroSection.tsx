import React, { useState, useEffect } from 'react';
import { Sparkles, Heart, Music, RefreshCw } from 'lucide-react';
import type { Theme, GiftConfig } from '../types';
import { GIRL_TAGLINES } from '../presets';

interface HeroSectionProps {
  theme: Theme;
  giftConfig: GiftConfig;
  currentPlaylistName: string;
  isPlaying: boolean;
}

export const HeroSection: React.FC<HeroSectionProps> = ({
  theme,
  giftConfig,
  currentPlaylistName,
  isPlaying,
}) => {
  const [taglineIndex, setTaglineIndex] = useState<number>(0);

  // Auto rotate taglines
  useEffect(() => {
    const interval = setInterval(() => {
      setTaglineIndex((prev) => (prev + 1) % GIRL_TAGLINES.length);
    }, 7000);
    return () => clearInterval(interval);
  }, []);

  const handleNextTagline = () => {
    setTaglineIndex((prev) => (prev + 1) % GIRL_TAGLINES.length);
  };

  return (
    <div className="relative w-full flex flex-col items-center justify-center pt-6 pb-28 sm:pt-10 sm:pb-36 px-4 text-center select-none overflow-hidden">
      {/* Background Animated Gradient Glow Orbs */}
      <div
        className="absolute top-1/3 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[340px] sm:w-[580px] h-[340px] sm:h-[580px] rounded-full blur-[100px] sm:blur-[140px] opacity-50 pointer-events-none transition-all duration-1000 animate-pulse-glow"
        style={{
          background: `radial-gradient(circle, ${theme.primaryColor} 0%, ${theme.accentColor} 60%, transparent 100%)`,
        }}
      />

      {/* Floating Sparkles & Hearts */}
      <div className="absolute inset-0 pointer-events-none overflow-hidden">
        <Sparkles className="absolute top-12 left-[12%] w-7 h-7 text-pink-300 animate-float-1 opacity-70" />
        <Heart className="absolute top-32 right-[15%] w-6 h-6 text-rose-400 fill-rose-400/40 animate-float-2 opacity-60" />
        <Sparkles className="absolute bottom-28 left-[18%] w-6 h-6 text-amber-300 animate-float-3 opacity-70" />
        <Heart className="absolute bottom-36 right-[22%] w-7 h-7 text-pink-400 fill-pink-400/40 animate-float-1 opacity-50" />
      </div>

      {/* BIG STYLISH ANIMATED DEDICATION HERO BANNER */}
      {giftConfig.isGiftMode && (
        <div className="relative group mb-6 transition-transform duration-500 hover:scale-105">
          {/* Animated Glowing Outline Aura */}
          <div className="absolute -inset-1 rounded-3xl bg-gradient-to-r from-pink-500 via-purple-500 to-rose-500 opacity-75 blur-md group-hover:opacity-100 transition duration-1000 group-hover:duration-200 animate-pulse" />

          {/* Main Hero Dedicated Card */}
          <div className="relative px-6 sm:px-10 py-3.5 sm:py-4 bg-black/40 backdrop-blur-xl border border-white/30 rounded-3xl flex items-center justify-center gap-3 sm:gap-4 shadow-[0_10px_35px_rgba(244,114,182,0.3)]">
            <Heart className="w-5 h-5 sm:w-7 sm:h-7 text-pink-400 fill-pink-400 animate-bounce" />

            <div className="flex flex-col items-center">
              <span className="text-[10px] sm:text-xs font-bold tracking-[0.25em] text-pink-300 uppercase">
                Crafted & Dedicated To
              </span>
              <h2 className="text-2xl sm:text-4xl font-extrabold text-transparent bg-clip-text bg-gradient-to-r from-pink-200 via-rose-100 to-white font-outfit drop-shadow-md">
                {giftConfig.friendName}
              </h2>
            </div>

            <Sparkles className="w-5 h-5 sm:w-7 sm:h-7 text-amber-300 animate-pulse" />
          </div>
        </div>
      )}

      {/* Main Brand Title */}
      <div className="flex flex-col items-center justify-center my-2">
        <h1 className="text-4xl sm:text-6xl md:text-7xl font-extrabold tracking-tight text-transparent bg-clip-text bg-gradient-to-r from-white via-pink-100 to-pink-300 drop-shadow-2xl">
          <span className="font-baloo text-pink-400 mr-2 sm:mr-3 inline-block drop-shadow-[0_4px_24px_rgba(244,114,182,0.4)]">
            {giftConfig.hindiTitle}
          </span>
          <span className="font-outfit uppercase tracking-wider text-white">
            {giftConfig.customTitle}
          </span>
        </h1>
      </div>

      {/* Dedicated Gift Note / Subtitle */}
      <p className="max-w-xl text-xs sm:text-sm md:text-base font-normal text-white/85 mt-3 mb-6 px-4 leading-relaxed tracking-wide drop-shadow">
        {giftConfig.message}
      </p>

      {/* Rotating Shayari / Highway Tagline Banner */}
      <div className="mt-1 relative inline-flex items-center gap-3 px-5 py-2.5 rounded-2xl glass-pill border border-white/20 text-xs sm:text-sm md:text-base font-semibold text-pink-200 shadow-xl backdrop-blur-xl group hover:border-pink-400/50 transition-all">
        <span className="text-lg">✨</span>
        <span className="font-outfit italic tracking-wide text-white drop-shadow-sm">
          "{GIRL_TAGLINES[taglineIndex]}"
        </span>
        <button
          onClick={handleNextTagline}
          className="p-1 rounded-full hover:bg-white/10 text-white/70 hover:text-white transition-all active:rotate-180 duration-300 cursor-pointer"
          title="Next quote"
        >
          <RefreshCw className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Active Playlist Pill Indicator */}
      <div className="mt-6 flex items-center gap-2 text-xs font-medium text-white/70 bg-white/5 px-4 py-1.5 rounded-full border border-white/10">
        <Music className={`w-3.5 h-3.5 ${isPlaying ? 'text-pink-400 animate-spin-slow' : 'text-white/60'}`} />
        <span>Playlist: <strong className="text-pink-300">{currentPlaylistName}</strong></span>
      </div>
    </div>
  );
};
