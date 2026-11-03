(() => {
  let player = null;
  let ready = false;
  let announcing = false;
  let originalVolume = null;
  const video = document.querySelector('.video video');

  function lowerVolume() {
    if (video) {
      if (originalVolume === null) originalVolume = video.volume;
      video.volume = Math.min(originalVolume, 0.15);
    } else if (ready) {
      if (originalVolume === null) originalVolume = player.getVolume();
      player.setVolume(Math.min(originalVolume, 15));
    }
  }

  window.painelMedia = {
    lower() {
      announcing = true;
      lowerVolume();
    },
    restore() {
      announcing = false;
      if (originalVolume === null) return;
      if (video) video.volume = originalVolume;
      else if (ready) player.setVolume(originalVolume);
      originalVolume = null;
    },
  };

  const iframe = document.querySelector('.video iframe');
  if (!iframe) return;
  const url = new URL(iframe.src, location.href);
  if (!['youtube.com', 'www.youtube.com', 'youtube-nocookie.com', 'www.youtube-nocookie.com'].includes(url.hostname)) return;
  url.searchParams.set('enablejsapi', '1');
  url.searchParams.set('origin', location.origin);
  iframe.src = url.toString();

  function initialize() {
    player = new YT.Player(iframe, {
      events: {
        onReady() {
          ready = true;
          if (announcing) lowerVolume();
        },
      },
    });
  }
  if (window.YT?.Player) initialize();
  else {
    window.onYouTubeIframeAPIReady = initialize;
    const script = document.createElement('script');
    script.src = 'https://www.youtube.com/iframe_api';
    document.head.appendChild(script);
  }
})();
