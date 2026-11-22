(() => {
  'use strict';

  let apiReady;

  function loadPlayerAPI() {
    if (window.YT && typeof window.YT.Player === 'function') return Promise.resolve(window.YT);
    if (apiReady) return apiReady;
    apiReady = new Promise((resolve, reject) => {
      const previousReady = window.onYouTubeIframeAPIReady;
      window.onYouTubeIframeAPIReady = () => {
        try {
          if (typeof previousReady === 'function') previousReady();
        } finally {
          resolve(window.YT);
        }
      };
      let script = document.querySelector('script[src="https://www.youtube.com/iframe_api"]');
      if (!script) {
        script = document.createElement('script');
        script.src = 'https://www.youtube.com/iframe_api';
        script.async = true;
        script.addEventListener('error', () => reject(new Error('YouTube Player API unavailable')), {once: true});
        document.head.append(script);
      } else {
        script.addEventListener('error', () => reject(new Error('YouTube Player API unavailable')), {once: true});
      }
    });
    return apiReady;
  }

  // Observe native YouTube playlist changes without restarting playback.
  // Call after attaching the iframe, then clean up before replacing it.
  window.observeMusicPlayer = (frame, onVideoChange) => {
    let active = true;
    let player = null;
    let lastVideoId = null;
    let pendingRead = null;

    function readVideo(target) {
      if (!active || !frame.isConnected) return;
      let videoId;
      try {
        videoId = new URL(target.getVideoUrl()).searchParams.get('v');
      } catch {
        return;
      }
      if (!/^[a-zA-Z0-9_-]{11}$/.test(videoId || '') || videoId === lastVideoId) return;
      lastVideoId = videoId;
      onVideoChange(videoId);
    }

    function observeState(event) {
      if (!active || !frame.isConnected) return;
      readVideo(event.target);
      clearTimeout(pendingRead);
      // Metadata can arrive just after a playlist transition's state event.
      pendingRead = setTimeout(() => readVideo(event.target), 150);
    }

    loadPlayerAPI().then(YT => {
      if (!active || !frame.isConnected) return;
      player = new YT.Player(frame, {
        events: {onReady: observeState, onStateChange: observeState}
      });
    }).catch(error => {
      if (active && frame.isConnected) console.warn('Automatic playlist layout unavailable:', error.message);
    });

    return () => {
      active = false;
      clearTimeout(pendingRead);
      if (player) {
        player.destroy();
        player = null;
      }
    };
  };
})();
