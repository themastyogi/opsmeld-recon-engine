import React, { useState } from 'react';
import { X, Plus, Video, AlertCircle, Sparkles } from 'lucide-react';
import type { Playlist } from '../types';

interface AddPlaylistModalProps {
  isOpen: boolean;
  onClose: () => void;
  onAddPlaylist: (playlist: Playlist) => void;
}

export const AddPlaylistModal: React.FC<AddPlaylistModalProps> = ({
  isOpen,
  onClose,
  onAddPlaylist,
}) => {
  const [urlInput, setUrlInput] = useState<string>('');
  const [customName, setCustomName] = useState<string>('');
  const [description, setDescription] = useState<string>('');
  const [selectedIcon, setSelectedIcon] = useState<string>('🌸');
  const [errorMsg, setErrorMsg] = useState<string>('');

  if (!isOpen) return null;

  const EMOJI_OPTIONS = ['🌸', '💖', '🎀', '✨', '⚡', '🚛', '🌌', '🌶️', '🎶', '🔥', '🍯', '👑'];

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMsg('');

    const input = urlInput.trim();
    if (!input) {
      setErrorMsg('Please paste a YouTube playlist link or playlist ID.');
      return;
    }

    let listId = '';
    // Check if user pasted full YouTube URL with list=... parameter
    if (input.includes('list=')) {
      try {
        const urlParams = new URLSearchParams(input.split('?')[1] || input.split('&')[1] || '');
        listId = urlParams.get('list') || '';
        if (!listId) {
          const match = input.match(/list=([a-zA-Z0-9_-]+)/);
          if (match) listId = match[1];
        }
      } catch (err) {
        const match = input.match(/list=([a-zA-Z0-9_-]+)/);
        if (match) listId = match[1];
      }
    } else if (input.startsWith('PL') || input.startsWith('RD') || input.startsWith('FL') || input.length >= 10) {
      // Direct playlist ID or list code
      listId = input;
    }

    if (!listId) {
      setErrorMsg('Could not find a valid YouTube Playlist ID in the link. Make sure the URL contains "list=..."');
      return;
    }

    const newPlaylist: Playlist = {
      id: `custom-${Date.now()}`,
      name: customName.trim() || 'My Favorite Playlist',
      description: description.trim() || 'Custom added YouTube playlist',
      category: 'custom',
      icon: selectedIcon,
      youtubeListId: listId,
      isCustom: true,
    };

    onAddPlaylist(newPlaylist);
    setUrlInput('');
    setCustomName('');
    setDescription('');
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-md animate-in fade-in duration-200">
      <div className="relative w-full max-w-lg glass-modal rounded-3xl p-6 sm:p-8 shadow-2xl border border-white/20 text-white">
        {/* Close Button */}
        <button
          onClick={onClose}
          className="absolute top-5 right-5 p-2 rounded-full hover:bg-white/10 text-white/70 hover:text-white transition-all cursor-pointer"
        >
          <X className="w-5 h-5" />
        </button>

        {/* Modal Header */}
        <div className="flex items-center gap-3 mb-6">
          <div className="p-3 rounded-2xl bg-pink-500/20 border border-pink-500/30 text-pink-300">
            <Video className="w-6 h-6" />
          </div>
          <div>
            <h2 className="text-xl sm:text-2xl font-bold text-white flex items-center gap-2">
              Add YouTube Playlist <Sparkles className="w-4 h-4 text-pink-400" />
            </h2>
            <p className="text-xs text-white/70 mt-0.5">
              Paste any YouTube or YouTube Music playlist link to stream non-stop.
            </p>
          </div>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-4">
          {/* YouTube Playlist URL input */}
          <div>
            <label className="block text-xs font-semibold text-pink-200 mb-1.5 uppercase tracking-wider">
              YouTube Playlist Link or ID <span className="text-pink-400">*</span>
            </label>
            <input
              type="text"
              value={urlInput}
              onChange={(e) => setUrlInput(e.target.value)}
              placeholder="e.g. https://www.youtube.com/playlist?list=PLgObA3p..."
              className="w-full px-4 py-3 rounded-xl bg-black/40 border border-white/15 focus:border-pink-400 focus:outline-none text-sm text-white placeholder-white/40 transition-all"
            />
            <p className="text-[11px] text-white/50 mt-1">
              Supports YouTube playlists, YouTube Music links, and list IDs.
            </p>
          </div>

          {/* Custom Name */}
          <div>
            <label className="block text-xs font-semibold text-white/80 mb-1.5 uppercase tracking-wider">
              Playlist Title
            </label>
            <input
              type="text"
              value={customName}
              onChange={(e) => setCustomName(e.target.value)}
              placeholder="e.g. My Highway Roadtrip Hits 🚗"
              className="w-full px-4 py-2.5 rounded-xl bg-black/40 border border-white/15 focus:border-pink-400 focus:outline-none text-sm text-white placeholder-white/40 transition-all"
            />
          </div>

          {/* Icon Selector */}
          <div>
            <label className="block text-xs font-semibold text-white/80 mb-1.5 uppercase tracking-wider">
              Choose Emoji Icon
            </label>
            <div className="flex flex-wrap gap-2">
              {EMOJI_OPTIONS.map((emoji) => (
                <button
                  type="button"
                  key={emoji}
                  onClick={() => setSelectedIcon(emoji)}
                  className={`w-9 h-9 rounded-xl text-lg flex items-center justify-center transition-all cursor-pointer ${
                    selectedIcon === emoji
                      ? 'bg-pink-500/40 border-2 border-pink-400 scale-110 shadow-lg'
                      : 'bg-white/5 border border-white/10 hover:bg-white/15'
                  }`}
                >
                  {emoji}
                </button>
              ))}
            </div>
          </div>

          {/* Description */}
          <div>
            <label className="block text-xs font-semibold text-white/80 mb-1.5 uppercase tracking-wider">
              Description (Optional)
            </label>
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="e.g. Added with love for late night vibes"
              className="w-full px-4 py-2.5 rounded-xl bg-black/40 border border-white/15 focus:border-pink-400 focus:outline-none text-sm text-white placeholder-white/40 transition-all"
            />
          </div>

          {/* Error Message */}
          {errorMsg && (
            <div className="flex items-center gap-2 p-3 rounded-xl bg-rose-500/20 border border-rose-500/40 text-rose-200 text-xs">
              <AlertCircle className="w-4 h-4 text-rose-400 flex-shrink-0" />
              <span>{errorMsg}</span>
            </div>
          )}

          {/* Action buttons */}
          <div className="flex items-center justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-5 py-2.5 rounded-xl text-xs font-semibold bg-white/10 hover:bg-white/20 text-white/80 transition-all cursor-pointer"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="px-6 py-2.5 rounded-xl text-xs font-semibold bg-gradient-to-r from-pink-500 to-rose-500 hover:from-pink-400 hover:to-rose-400 text-white shadow-lg shadow-pink-500/30 transition-all transform hover:scale-105 active:scale-95 flex items-center gap-2 cursor-pointer"
            >
              <Plus className="w-4 h-4" />
              <span>Save & Play</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
