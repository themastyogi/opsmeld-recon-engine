export interface PlaylistItem {
  id: string;
  title: string;
  artist: string;
  thumbnail: string;
  duration?: number;
}

export interface Playlist {
  id: string; // YouTube list ID or custom generated ID
  name: string;
  description: string;
  category: 'girl-boss' | 'cozy-lofi' | 'pop-queen' | 'romantic' | 'highway-truck' | 'custom';
  icon: string; // emoji icon
  youtubeListId?: string; // e.g. PLgObA3pAqvOh87Z03QG8Z4xE-uqlAWSBy
  items?: PlaylistItem[];
  isCustom?: boolean;
}

export type ThemeId = 'princess' | 'cozy-sunset' | 'pop-queen' | 'lavender' | 'truck-highway';

export interface Theme {
  id: ThemeId;
  name: string;
  icon: string;
  bgGradient: string;
  primaryColor: string;
  accentColor: string;
  dockBg: string;
  fontClass: string;
  taglineFont: string;
  particles: 'sparkles' | 'hearts' | 'clouds' | 'stars' | 'highway';
  cardGlow: string;
}

export interface GiftConfig {
  friendName: string;
  tagline: string;
  message: string;
  customTitle: string;
  hindiTitle: string;
  isGiftMode: boolean;
}

export interface PlayerState {
  isPlaying: boolean;
  isBuffering: boolean;
  currentTrackIndex: number;
  currentTime: number;
  duration: number;
  volume: number;
  isMuted: boolean;
  isShuffle: boolean;
  isRepeat: boolean;
  currentPlaylist: Playlist;
  currentTrack: PlaylistItem | null;
  tracks: PlaylistItem[];
  isAdmin: boolean;
}
