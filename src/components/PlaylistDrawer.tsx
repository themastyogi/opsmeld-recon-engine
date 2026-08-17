import React, { useState } from 'react';
import { X, Play, Music, Search, Sparkles } from 'lucide-react';
import type { Playlist, PlaylistItem } from '../types';

interface PlaylistDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  playlists: Playlist[];
  currentPlaylistId: string;
  onSelectPlaylist: (playlist: Playlist) => void;
  currentTrackIndex: number;
  currentTracks: PlaylistItem[];
  onSelectTrack: (index: number) => void;
}

export const PlaylistDrawer: React.FC<PlaylistDrawerProps> = ({
  isOpen,
  onClose,
  playlists,
  currentPlaylistId,
  onSelectPlaylist,
  currentTrackIndex,
  currentTracks,
  onSelectTrack,
}) => {
  const [activeTab, setActiveTab] = useState<'playlists' | 'tracklist'>('playlists');
  const [searchQuery, setSearchQuery] = useState<string>('');

  if (!isOpen) return null;

  const filteredPlaylists = playlists.filter(
    (p) =>
      p.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      p.description.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const filteredTracks = currentTracks.filter(
    (t) =>
      t.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
      t.artist.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="fixed inset-0 z-50 overflow-hidden">
      {/* Backdrop */}
      <div
        onClick={onClose}
        className="absolute inset-0 bg-black/70 backdrop-blur-sm transition-opacity animate-in fade-in duration-200"
      />

      {/* Drawer Panel */}
      <div className="absolute inset-y-0 right-0 max-w-full flex pl-10">
        <div className="w-screen max-w-md glass-modal border-l border-white/20 text-white flex flex-col shadow-2xl animate-in slide-in-from-right duration-300">
          {/* Drawer Header */}
          <div className="p-6 border-b border-white/10 flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="p-2.5 rounded-xl bg-pink-500/20 text-pink-300 border border-pink-500/30">
                <Music className="w-5 h-5" />
              </div>
              <div>
                <h2 className="text-lg font-bold text-white flex items-center gap-2">
                  Library & Tracklist <Sparkles className="w-4 h-4 text-pink-400" />
                </h2>
                <p className="text-xs text-white/60">Choose a playlist or jump to a track</p>
              </div>
            </div>
            <button
              onClick={onClose}
              className="p-2 rounded-full hover:bg-white/10 text-white/70 hover:text-white transition-all cursor-pointer"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* Navigation Tabs & Search */}
          <div className="px-6 pt-4 pb-2 border-b border-white/10 space-y-3">
            <div className="flex bg-black/40 p-1 rounded-xl border border-white/10">
              <button
                onClick={() => setActiveTab('playlists')}
                className={`flex-1 py-2 text-xs font-bold rounded-lg transition-all cursor-pointer ${
                  activeTab === 'playlists'
                    ? 'bg-pink-500/30 text-white border border-pink-500/40 shadow-sm'
                    : 'text-white/60 hover:text-white'
                }`}
              >
                Playlists ({playlists.length})
              </button>
              <button
                onClick={() => setActiveTab('tracklist')}
                className={`flex-1 py-2 text-xs font-bold rounded-lg transition-all cursor-pointer ${
                  activeTab === 'tracklist'
                    ? 'bg-pink-500/30 text-white border border-pink-500/40 shadow-sm'
                    : 'text-white/60 hover:text-white'
                }`}
              >
                Now Playing ({currentTracks.length})
              </button>
            </div>

            {/* Search Input */}
            <div className="relative">
              <Search className="w-3.5 h-3.5 absolute left-3.5 top-1/2 -translate-y-1/2 text-white/40" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder={activeTab === 'playlists' ? 'Search playlists...' : 'Search tracks...'}
                className="w-full pl-9 pr-4 py-2 rounded-xl bg-black/30 border border-white/10 focus:border-pink-400 focus:outline-none text-xs text-white placeholder-white/40"
              />
            </div>
          </div>

          {/* Tab Content */}
          <div className="flex-1 overflow-y-auto p-4 space-y-2.5">
            {activeTab === 'playlists' ? (
              <>
                {filteredPlaylists.map((p) => {
                  const isActive = p.id === currentPlaylistId;
                  return (
                    <div
                      key={p.id}
                      onClick={() => onSelectPlaylist(p)}
                      className={`p-3.5 rounded-2xl border transition-all cursor-pointer flex items-center justify-between group ${
                        isActive
                          ? 'bg-gradient-to-r from-pink-500/30 to-purple-500/20 border-pink-400/60 shadow-lg'
                          : 'bg-white/5 border-white/10 hover:bg-white/10 hover:border-white/20'
                      }`}
                    >
                      <div className="flex items-center gap-3 min-w-0 pr-2">
                        <div className="text-2xl p-2 rounded-xl bg-black/30 border border-white/10 flex-shrink-0">
                          {p.icon}
                        </div>
                        <div className="min-w-0">
                          <h4 className="text-xs sm:text-sm font-bold text-white truncate flex items-center gap-1.5">
                            {p.name}
                            {isActive && (
                              <span className="inline-block w-2 h-2 rounded-full bg-pink-400 animate-pulse" />
                            )}
                          </h4>
                          <p className="text-[11px] text-white/60 line-clamp-1 mt-0.5">
                            {p.description}
                          </p>
                        </div>
                      </div>

                      <div className="flex items-center gap-1 flex-shrink-0">
                        <div className="p-2 rounded-lg bg-pink-500/20 text-pink-300 opacity-80 group-hover:opacity-100 transition-opacity">
                          <Play className="w-3.5 h-3.5 fill-pink-300" />
                        </div>
                      </div>
                    </div>
                  );
                })}
              </>
            ) : (
              /* Tracklist Tab */
              <>
                {filteredTracks.length === 0 ? (
                  <div className="text-center py-12 text-white/50 text-xs">
                    Press Play to start playing playlist tracks.
                  </div>
                ) : (
                  filteredTracks.map((t, idx) => {
                    const isSelected = idx === currentTrackIndex;
                    return (
                      <div
                        key={t.id + idx}
                        onClick={() => onSelectTrack(idx)}
                        className={`p-2.5 rounded-xl border transition-all cursor-pointer flex items-center justify-between ${
                          isSelected
                            ? 'bg-pink-500/25 border-pink-400/50 shadow-md'
                            : 'bg-white/5 border-white/5 hover:bg-white/10'
                        }`}
                      >
                        <div className="flex items-center gap-3 min-w-0">
                          <span className="text-xs font-mono text-white/40 w-5 text-center flex-shrink-0">
                            {idx + 1}
                          </span>
                          <img
                            src={t.thumbnail || `https://img.youtube.com/vi/${t.id}/hqdefault.jpg`}
                            alt={t.title}
                            className="w-9 h-9 rounded-lg object-cover flex-shrink-0 border border-white/10"
                            onError={(e) => {
                              (e.target as HTMLElement).style.display = 'none';
                            }}
                          />
                          <div className="min-w-0 pr-2">
                            <p
                              className={`text-xs font-semibold truncate ${
                                isSelected ? 'text-pink-300 font-bold' : 'text-white/90'
                              }`}
                            >
                              {t.title}
                            </p>
                            <p className="text-[10px] text-white/50 truncate">{t.artist}</p>
                          </div>
                        </div>
                        {isSelected && (
                          <div className="flex items-center gap-1 text-pink-400">
                            <span className="w-1 h-3 bg-pink-400 rounded-full eq-bar-1" />
                            <span className="w-1 h-4 bg-pink-400 rounded-full eq-bar-2" />
                            <span className="w-1 h-2 bg-pink-400 rounded-full eq-bar-3" />
                          </div>
                        )}
                      </div>
                    );
                  })
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
