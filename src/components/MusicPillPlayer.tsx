import React, { useState } from 'react';
import {
  Play,
  Pause,
  SkipBack,
  SkipForward,
  Shuffle,
  Repeat,
  Volume2,
  VolumeX,
  ListMusic,
  Disc,
} from 'lucide-react';
import type { PlaylistItem, Theme } from '../types';

interface MusicPillPlayerProps {
  theme: Theme;
  currentTrack: PlaylistItem | null;
  isPlaying: boolean;
  isBuffering: boolean;
  currentTime: number;
  duration: number;
  volume: number;
  isMuted: boolean;
  isShuffle: boolean;
  isRepeat: boolean;
  onPlayPause: () => void;
  onNextTrack: () => void;
  onPrevTrack: () => void;
  onSeek: (seconds: number) => void;
  onVolumeChange: (volume: number) => void;
  onToggleMute: () => void;
  onToggleShuffle: () => void;
  onToggleRepeat: () => void;
  onOpenPlaylistDrawer: () => void;
}

export const MusicPillPlayer: React.FC<MusicPillPlayerProps> = ({
  currentTrack,
  isPlaying,
  isBuffering,
  currentTime,
  duration,
  volume,
  isMuted,
  isShuffle,
  isRepeat,
  onPlayPause,
  onNextTrack,
  onPrevTrack,
  onSeek,
  onVolumeChange,
  onToggleMute,
  onToggleShuffle,
  onToggleRepeat,
  onOpenPlaylistDrawer,
}) => {
  const [hoverSeekTime, setHoverSeekTime] = useState<number | null>(null);

  const formatTime = (secs: number) => {
    if (isNaN(secs) || secs < 0) return '0:00';
    const m = Math.floor(secs / 60);
    const s = Math.floor(secs % 60);
    return `${m}:${s < 10 ? '0' : ''}${s}`;
  };

  const progressPercent = duration > 0 ? (currentTime / duration) * 100 : 0;

  const handleScrub = (e: React.MouseEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const clickX = e.clientX - rect.left;
    const ratio = Math.max(0, Math.min(1, clickX / rect.width));
    onSeek(ratio * duration);
  };

  const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const hoverX = e.clientX - rect.left;
    const ratio = Math.max(0, Math.min(1, hoverX / rect.width));
    setHoverSeekTime(ratio * duration);
  };

  return (
    <div className="fixed bottom-4 sm:bottom-6 left-1/2 -translate-x-1/2 z-40 w-[94%] max-w-2xl px-3 sm:px-5 py-3 rounded-3xl glass-pill shadow-[0_12px_40px_rgba(0,0,0,0.6)] border border-white/20 text-white backdrop-blur-2xl transition-all duration-300">
      {/* Top Section: Cover Art, Metadata, Controls */}
      <div className="flex items-center justify-between gap-3">
        {/* Left: Album Cover & Track Title */}
        <div className="flex items-center gap-3 min-w-0 flex-1">
          {/* Vinyl Album Thumbnail */}
          <div className="relative flex-shrink-0">
            <div
              className={`w-11 h-11 sm:w-12 sm:h-12 rounded-2xl overflow-hidden border border-white/20 shadow-md bg-black/40 flex items-center justify-center ${
                isPlaying ? 'ring-2 ring-pink-400/60 shadow-pink-500/20' : ''
              }`}
            >
              {currentTrack?.thumbnail ? (
                <img
                  src={currentTrack.thumbnail}
                  alt={currentTrack.title}
                  className={`w-full h-full object-cover ${isPlaying ? 'animate-spin-slow' : ''}`}
                />
              ) : (
                <Disc className={`w-6 h-6 text-pink-400 ${isPlaying ? 'animate-spin-slow' : ''}`} />
              )}
            </div>
            {/* Playing equalizer indicator badge */}
            {isPlaying && (
              <span className="absolute -bottom-1 -right-1 flex h-4 w-4 items-center justify-center rounded-full bg-pink-500 text-[10px]">
                🎵
              </span>
            )}
          </div>

          {/* Track Details & Marquee */}
          <div className="min-w-0 flex-1">
            <h3 className="text-xs sm:text-sm font-bold text-white truncate leading-snug">
              {currentTrack?.title || 'Click play to start highway music'}
            </h3>
            <p className="text-[11px] text-pink-200/80 truncate font-medium">
              {currentTrack?.artist || 'VibeStream Player'}
            </p>
          </div>
        </div>

        {/* Center: Controls (Prev, Play/Pause, Next) */}
        <div className="flex items-center gap-1.5 sm:gap-2">
          {/* Shuffle Button */}
          <button
            onClick={onToggleShuffle}
            className={`hidden sm:flex p-1.5 rounded-full transition-colors cursor-pointer ${
              isShuffle ? 'text-pink-400 bg-pink-500/20' : 'text-white/50 hover:text-white'
            }`}
            title="Shuffle"
          >
            <Shuffle className="w-3.5 h-3.5" />
          </button>

          {/* Previous Track */}
          <button
            onClick={onPrevTrack}
            className="p-2 rounded-full hover:bg-white/10 text-white/80 hover:text-white transition-all active:scale-90 cursor-pointer"
            title="Previous Track"
          >
            <SkipBack className="w-4 h-4 sm:w-5 sm:h-5 fill-current" />
          </button>

          {/* Main Play / Pause Button */}
          <button
            onClick={onPlayPause}
            disabled={isBuffering}
            className="p-3 sm:p-3.5 rounded-2xl bg-gradient-to-r from-pink-500 to-rose-500 hover:from-pink-400 hover:to-rose-400 text-white shadow-lg shadow-pink-500/40 transform hover:scale-105 active:scale-95 transition-all flex items-center justify-center cursor-pointer"
            title={isPlaying ? 'Pause' : 'Play'}
          >
            {isBuffering ? (
              <span className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin" />
            ) : isPlaying ? (
              <Pause className="w-5 h-5 fill-current" />
            ) : (
              <Play className="w-5 h-5 fill-current ml-0.5" />
            )}
          </button>

          {/* Next Track */}
          <button
            onClick={onNextTrack}
            className="p-2 rounded-full hover:bg-white/10 text-white/80 hover:text-white transition-all active:scale-90 cursor-pointer"
            title="Next Track"
          >
            <SkipForward className="w-4 h-4 sm:w-5 sm:h-5 fill-current" />
          </button>

          {/* Repeat Button */}
          <button
            onClick={onToggleRepeat}
            className={`hidden sm:flex p-1.5 rounded-full transition-colors cursor-pointer ${
              isRepeat ? 'text-pink-400 bg-pink-500/20' : 'text-white/50 hover:text-white'
            }`}
            title="Repeat"
          >
            <Repeat className="w-3.5 h-3.5" />
          </button>
        </div>

        {/* Right: Volume & Playlist Drawer Toggle */}
        <div className="flex items-center gap-2">
          {/* Volume Control */}
          <div className="hidden md:flex items-center gap-1.5 bg-black/30 px-2.5 py-1.5 rounded-full border border-white/10">
            <button
              onClick={onToggleMute}
              className="text-white/70 hover:text-white transition-colors cursor-pointer"
            >
              {isMuted || volume === 0 ? (
                <VolumeX className="w-3.5 h-3.5 text-rose-400" />
              ) : (
                <Volume2 className="w-3.5 h-3.5 text-pink-300" />
              )}
            </button>
            <input
              type="range"
              min="0"
              max="100"
              value={isMuted ? 0 : volume}
              onChange={(e) => onVolumeChange(Number(e.target.value))}
              className="w-14 h-1 bg-white/20 rounded-lg appearance-none cursor-pointer accent-pink-400"
            />
          </div>

          {/* Playlist Drawer Button */}
          <button
            onClick={onOpenPlaylistDrawer}
            className="p-2 rounded-xl bg-white/10 hover:bg-white/20 text-pink-300 transition-all cursor-pointer"
            title="View Playlist & Tracks"
          >
            <ListMusic className="w-4 h-4 sm:w-5 sm:h-5" />
          </button>
        </div>
      </div>

      {/* Progress Bar & Scrubbing Rail */}
      <div className="mt-2 flex items-center gap-2 text-[10px] sm:text-xs font-mono text-white/60">
        <span>{formatTime(currentTime)}</span>
        <div
          onClick={handleScrub}
          onMouseMove={handleMouseMove}
          onMouseLeave={() => setHoverSeekTime(null)}
          className="relative flex-1 h-2 bg-black/40 hover:h-3 rounded-full cursor-pointer overflow-hidden transition-all border border-white/10 group"
        >
          {/* Filled progress */}
          <div
            className="h-full bg-gradient-to-r from-pink-500 via-rose-400 to-amber-300 rounded-full transition-all"
            style={{ width: `${progressPercent}%` }}
          />

          {/* Hover indicator tooltip */}
          {hoverSeekTime !== null && (
            <div
              className="absolute -top-6 -translate-x-1/2 bg-black/90 text-white px-1.5 py-0.5 rounded text-[9px] font-mono pointer-events-none border border-white/20"
              style={{
                left: `${(hoverSeekTime / (duration || 1)) * 100}%`,
              }}
            >
              {formatTime(hoverSeekTime)}
            </div>
          )}
        </div>
        <span>{formatTime(duration)}</span>
      </div>
    </div>
  );
};
