declare global {
  interface Window {
    YT: any;
    onYouTubeIframeAPIReady: () => void;
  }
}

export interface VideoMetaData {
  title: string;
  artist: string;
  thumbnail: string;
}

type EventCallback<T = any> = (data: T) => void;

export class YouTubePlayerService {
  private player: any = null;
  private isReady: boolean = false;
  private elementId: string;
  private currentListId: string = '';
  private currentVideoId: string = '';
  private currentTrackIndex: number = 0;
  private pollInterval: any = null;

  // Callbacks
  private onStateChangeCb: EventCallback<{ isPlaying: boolean; isBuffering: boolean }> | null = null;
  private onTrackChangeCb: EventCallback<{ index: number; videoId: string; meta?: VideoMetaData }> | null = null;
  private onTimeUpdateCb: EventCallback<{ currentTime: number; duration: number }> | null = null;

  constructor(elementId: string = 'yt-player-host') {
    this.elementId = elementId;
  }

  public init(): Promise<void> {
    return new Promise((resolve) => {
      if (window.YT && window.YT.Player) {
        this.createPlayer(resolve);
        return;
      }

      // Load YouTube IFrame API tag
      const existingScript = document.getElementById('yt-iframe-script');
      if (!existingScript) {
        const tag = document.createElement('script');
        tag.id = 'yt-iframe-script';
        tag.src = 'https://www.youtube.com/iframe_api';
        const firstScriptTag = document.getElementsByTagName('script')[0];
        firstScriptTag.parentNode?.insertBefore(tag, firstScriptTag);
      }

      const prevCallback = window.onYouTubeIframeAPIReady;
      window.onYouTubeIframeAPIReady = () => {
        if (prevCallback) prevCallback();
        this.createPlayer(resolve);
      };
    });
  }

  private createPlayer(onReadyResolve: () => void) {
    if (this.player) {
      onReadyResolve();
      return;
    }

    this.player = new window.YT.Player(this.elementId, {
      height: '100',
      width: '100',
      playerVars: {
        autoplay: 0,
        controls: 0,
        disablekb: 1,
        fs: 0,
        modestbranding: 1,
        rel: 0,
        origin: window.location.origin,
      },
      events: {
        onReady: () => {
          this.isReady = true;
          this.startPolling();
          onReadyResolve();
        },
        onStateChange: (event: any) => {
          this.handleStateChange(event.data);
        },
        onError: (event: any) => {
          console.warn('YouTube Player Error:', event.data);
          // Auto skip broken video in playlist
          setTimeout(() => {
            if (this.player && typeof this.player.nextVideo === 'function') {
              this.player.nextVideo();
            }
          }, 1000);
        },
      },
    });
  }

  private handleStateChange(state: number) {
    // YT.PlayerState: UNSTARTED (-1), ENDED (0), PLAYING (1), PAUSED (2), BUFFERING (3), CUED (5)
    const isPlaying = state === 1;
    const isBuffering = state === 3;

    if (this.onStateChangeCb) {
      this.onStateChangeCb({ isPlaying, isBuffering });
    }

    if (state === 1 || state === 5) {
      this.updateCurrentTrackInfo();
    }
  }

  private async updateCurrentTrackInfo() {
    if (!this.player) return;
    try {
      const playlist = this.player.getPlaylist ? this.player.getPlaylist() : [];
      const index = this.player.getPlaylistIndex ? this.player.getPlaylistIndex() : 0;
      const videoData = this.player.getVideoData ? this.player.getVideoData() : null;

      const videoId = videoData?.video_id || (playlist && playlist[index]) || '';
      
      if (videoId && (videoId !== this.currentVideoId || index !== this.currentTrackIndex)) {
        this.currentVideoId = videoId;
        this.currentTrackIndex = index >= 0 ? index : 0;

        let meta: VideoMetaData | undefined;
        if (videoData && videoData.title) {
          meta = {
            title: videoData.title,
            artist: videoData.author || 'YouTube Music',
            thumbnail: `https://img.youtube.com/vi/${videoId}/hqdefault.jpg`,
          };
        } else if (videoId) {
          meta = await this.fetchOembedMeta(videoId);
        }

        if (this.onTrackChangeCb) {
          this.onTrackChangeCb({ index: this.currentTrackIndex, videoId, meta });
        }
      }
    } catch (e) {
      console.error('Error updating current track info:', e);
    }
  }

  public async fetchOembedMeta(videoId: string): Promise<VideoMetaData> {
    try {
      const res = await fetch(`https://noembed.com/embed?url=https://www.youtube.com/watch?v=${videoId}`);
      if (res.ok) {
        const data = await res.json();
        return {
          title: data.title || `Track ${videoId}`,
          artist: data.author_name || 'YouTube Channel',
          thumbnail: data.thumbnail_url || `https://img.youtube.com/vi/${videoId}/hqdefault.jpg`,
        };
      }
    } catch (err) {
      // Fallback
    }
    return {
      title: `Highway Track`,
      artist: `YouTube Music`,
      thumbnail: `https://img.youtube.com/vi/${videoId}/hqdefault.jpg`,
    };
  }

  public loadPlaylist(playlistId: string, startIndex: number = 0) {
    if (!this.player || !this.isReady) return;
    this.currentListId = playlistId;
    this.player.loadPlaylist({
      listType: 'playlist',
      list: playlistId,
      index: startIndex,
    });
  }

  public loadVideo(videoId: string) {
    if (!this.player || !this.isReady) return;
    this.player.loadVideoById(videoId);
  }

  public loadVideoList(videoIds: string[], startIndex: number = 0) {
    if (!this.player || !this.isReady) return;
    this.player.loadPlaylist({
      playlist: videoIds,
      index: startIndex,
    });
  }

  public play() {
    if (this.player && typeof this.player.playVideo === 'function') {
      this.player.playVideo();
    }
  }

  public pause() {
    if (this.player && typeof this.player.pauseVideo === 'function') {
      this.player.pauseVideo();
    }
  }

  public nextTrack() {
    if (this.player && typeof this.player.nextVideo === 'function') {
      this.player.nextVideo();
    }
  }

  public previousTrack() {
    if (this.player && typeof this.player.previousVideo === 'function') {
      this.player.previousVideo();
    }
  }

  public playTrackAt(index: number) {
    if (this.player && typeof this.player.playVideoAt === 'function') {
      this.player.playVideoAt(index);
    }
  }

  public seekTo(seconds: number) {
    if (this.player && typeof this.player.seekTo === 'function') {
      this.player.seekTo(seconds, true);
    }
  }

  public setVolume(volume: number) {
    if (this.player && typeof this.player.setVolume === 'function') {
      this.player.setVolume(Math.max(0, Math.min(100, volume)));
    }
  }

  public mute() {
    if (this.player && typeof this.player.mute === 'function') {
      this.player.mute();
    }
  }

  public unMute() {
    if (this.player && typeof this.player.unMute === 'function') {
      this.player.unMute();
    }
  }

  public setShuffle(shuffle: boolean) {
    if (this.player && typeof this.player.setShuffle === 'function') {
      this.player.setShuffle(shuffle);
    }
  }

  public setLoop(loop: boolean) {
    if (this.player && typeof this.player.setLoop === 'function') {
      this.player.setLoop(loop);
    }
  }

  private startPolling() {
    if (this.pollInterval) clearInterval(this.pollInterval);
    this.pollInterval = setInterval(() => {
      if (!this.player || !this.isReady) return;
      try {
        const currentTime = this.player.getCurrentTime ? this.player.getCurrentTime() : 0;
        const duration = this.player.getDuration ? this.player.getDuration() : 0;
        if (this.onTimeUpdateCb) {
          this.onTimeUpdateCb({ currentTime: currentTime || 0, duration: duration || 0 });
        }
      } catch (e) {
        // ignore polling error
      }
    }, 500);
  }

  public onStateChange(cb: EventCallback<{ isPlaying: boolean; isBuffering: boolean }>) {
    this.onStateChangeCb = cb;
  }

  public onTrackChange(cb: EventCallback<{ index: number; videoId: string; meta?: VideoMetaData }>) {
    this.onTrackChangeCb = cb;
  }

  public onTimeUpdate(cb: EventCallback<{ currentTime: number; duration: number }>) {
    this.onTimeUpdateCb = cb;
  }

  public destroy() {
    if (this.pollInterval) clearInterval(this.pollInterval);
    if (this.player && typeof this.player.destroy === 'function') {
      this.player.destroy();
    }
    this.player = null;
    this.isReady = false;
  }
}
