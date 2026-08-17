import React, { useState, useEffect } from 'react';
import { Clock, Palette, ListMusic, Radio } from 'lucide-react';
import type { Theme, ThemeId } from '../types';
import { THEMES } from '../presets';

interface TopBarProps {
  currentTheme: Theme;
  onSelectTheme: (themeId: ThemeId) => void;
  onOpenPlaylistDrawer: () => void;
  playlistCount: number;
}

export const TopBar: React.FC<TopBarProps> = ({
  currentTheme,
  onSelectTheme,
  onOpenPlaylistDrawer,
  playlistCount,
}) => {
  const [timeString, setTimeString] = useState<string>('');
  const [showThemeDropdown, setShowThemeDropdown] = useState<boolean>(false);

  // Real Digital Clock
  useEffect(() => {
    const updateTime = () => {
      const now = new Date();
      setTimeString(
        now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
      );
    };
    updateTime();
    const interval = setInterval(updateTime, 1000);
    return () => clearInterval(interval);
  }, []);

  return (
    <header className="w-full px-4 sm:px-8 py-3.5 flex items-center justify-between z-30 relative border-b border-white/10 backdrop-blur-md bg-black/20">
      {/* Left side: Clock & Real Live Session Indicator */}
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2 text-xs font-medium tracking-wide text-white/90 bg-white/5 px-3 py-1.5 rounded-full border border-white/10 shadow-sm">
          <Clock className="w-3.5 h-3.5 text-pink-400" />
          <span>{timeString || '12:00:00 AM'}</span>
        </div>

        {/* Real Live Indicator */}
        <div className="flex items-center gap-2 text-xs font-semibold text-emerald-300 bg-emerald-500/10 border border-emerald-500/20 px-3 py-1.5 rounded-full">
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
            <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
          </span>
          <Radio className="w-3.5 h-3.5 text-emerald-400" />
          <span>LIVE ● 1 Listener</span>
        </div>
      </div>

      {/* Right side: Music Theme Switcher & Playlists */}
      <div className="flex items-center gap-2 sm:gap-3">
        {/* Theme Picker Dropdown */}
        <div className="relative">
          <button
            onClick={() => setShowThemeDropdown(!showThemeDropdown)}
            className="flex items-center gap-1.5 text-xs font-semibold px-3.5 py-1.5 rounded-full bg-white/10 hover:bg-white/20 border border-white/15 text-white transition-all cursor-pointer shadow-sm"
            title="Music Theme Change"
          >
            <Palette className="w-3.5 h-3.5 text-purple-300" />
            <span className="hidden sm:inline">{currentTheme.name}</span>
            <span className="sm:hidden">{currentTheme.icon}</span>
          </button>

          {showThemeDropdown && (
            <div className="absolute right-0 mt-2 w-48 py-2 glass-modal rounded-2xl shadow-2xl z-50 border border-white/20">
              <div className="px-3 py-1 text-[10px] font-bold tracking-wider text-white/50 uppercase">
                Music Theme
              </div>
              {Object.values(THEMES).map((t) => (
                <button
                  key={t.id}
                  onClick={() => {
                    onSelectTheme(t.id);
                    setShowThemeDropdown(false);
                  }}
                  className={`w-full px-3 py-2 text-left text-xs font-medium flex items-center justify-between hover:bg-white/15 transition-colors cursor-pointer ${
                    currentTheme.id === t.id ? 'text-pink-300 bg-white/10 font-bold' : 'text-white/80'
                  }`}
                >
                  <span>{t.name}</span>
                  {currentTheme.id === t.id && <span className="text-pink-400 font-bold">✓</span>}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Playlist Drawer Button */}
        <button
          onClick={onOpenPlaylistDrawer}
          className="flex items-center gap-1.5 text-xs font-semibold px-3.5 py-1.5 rounded-full bg-white/15 hover:bg-white/25 border border-white/20 text-white transition-all cursor-pointer shadow-sm"
        >
          <ListMusic className="w-4 h-4 text-pink-300" />
          <span className="hidden sm:inline">Playlists ({playlistCount})</span>
        </button>
      </div>
    </header>
  );
};
