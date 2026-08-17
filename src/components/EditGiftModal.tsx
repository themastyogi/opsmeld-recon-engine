import React, { useState } from 'react';
import { X, Gift, Heart, Check } from 'lucide-react';
import type { GiftConfig } from '../types';

interface EditGiftModalProps {
  isOpen: boolean;
  onClose: () => void;
  giftConfig: GiftConfig;
  onSaveGiftConfig: (newConfig: GiftConfig) => void;
}

export const EditGiftModal: React.FC<EditGiftModalProps> = ({
  isOpen,
  onClose,
  giftConfig,
  onSaveGiftConfig,
}) => {
  const [friendName, setFriendName] = useState<string>(giftConfig.friendName);
  const [hindiTitle, setHindiTitle] = useState<string>(giftConfig.hindiTitle);
  const [customTitle, setCustomTitle] = useState<string>(giftConfig.customTitle);
  const [message, setMessage] = useState<string>(giftConfig.message);
  const [tagline, setTagline] = useState<string>(giftConfig.tagline);

  if (!isOpen) return null;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSaveGiftConfig({
      friendName: friendName.trim() || 'My Bestie 🌸',
      hindiTitle: hindiTitle.trim() || 'मेरी पसंदीदा',
      customTitle: customTitle.trim() || 'Music',
      message: message.trim() || 'Crafted with love for continuous aesthetic beats.',
      tagline: tagline.trim() || 'Drive Safe, Sparkle Always ✨',
      isGiftMode: true,
    });
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
            <Gift className="w-6 h-6" />
          </div>
          <div>
            <h2 className="text-xl sm:text-2xl font-bold text-white flex items-center gap-2">
              Personalize Gift Message <Heart className="w-4 h-4 text-pink-400 fill-pink-400" />
            </h2>
            <p className="text-xs text-white/70 mt-0.5">
              Customize the friend's name, titles, and message shown on screen.
            </p>
          </div>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Friend's Name */}
          <div>
            <label className="block text-xs font-semibold text-pink-200 mb-1.5 uppercase tracking-wider">
              Friend's Name / Dedicated To
            </label>
            <input
              type="text"
              value={friendName}
              onChange={(e) => setFriendName(e.target.value)}
              placeholder="e.g. Simran ✨"
              className="w-full px-4 py-2.5 rounded-xl bg-black/40 border border-white/15 focus:border-pink-400 focus:outline-none text-sm text-white placeholder-white/40 transition-all"
            />
          </div>

          {/* Hindi Title & Custom Title */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-semibold text-white/80 mb-1.5 uppercase tracking-wider">
                Hindi Header Text
              </label>
              <input
                type="text"
                value={hindiTitle}
                onChange={(e) => setHindiTitle(e.target.value)}
                placeholder="e.g. मेरी पसंदीदा"
                className="w-full px-4 py-2.5 rounded-xl bg-black/40 border border-white/15 focus:border-pink-400 focus:outline-none text-sm text-white placeholder-white/40 transition-all"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-white/80 mb-1.5 uppercase tracking-wider">
                English Sub-Header
              </label>
              <input
                type="text"
                value={customTitle}
                onChange={(e) => setCustomTitle(e.target.value)}
                placeholder="e.g. Music / Playlist"
                className="w-full px-4 py-2.5 rounded-xl bg-black/40 border border-white/15 focus:border-pink-400 focus:outline-none text-sm text-white placeholder-white/40 transition-all"
              />
            </div>
          </div>

          {/* Dedicated Message */}
          <div>
            <label className="block text-xs font-semibold text-white/80 mb-1.5 uppercase tracking-wider">
              Dedicated Gift Note
            </label>
            <textarea
              rows={3}
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder="Write a sweet message for your friend..."
              className="w-full px-4 py-2.5 rounded-xl bg-black/40 border border-white/15 focus:border-pink-400 focus:outline-none text-sm text-white placeholder-white/40 transition-all resize-none"
            />
          </div>

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
              <Check className="w-4 h-4" />
              <span>Apply & Save</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
