(() => {
  'use strict';

  const pageTitle = document.title;
  const assetBase = new URL('./assets/', document.baseURI);
  const grid = document.getElementById('video-grid');
  const resultsNote = document.getElementById('video-results-note');
  const search = document.getElementById('video-search');
  const filter = document.getElementById('artist-filter');
  const more = document.getElementById('load-more');
  const empty = document.getElementById('empty-state');
  const dialog = document.getElementById('artist-dialog');
  const player = document.getElementById('video-player');
  const tracks = document.getElementById('track-list');
  const share = document.getElementById('share-artist');
  const sourceMap = new Map();
  const videoMap = new Map();
  let catalogue;
  let videos = [];
  let visibleCount = 12;
  let selectedSource = null;
  let selectedVideo = null;
  let returnFocus = null;
  let renderedRoute = '';

  const element = (tag, className, text) => {
    const item = document.createElement(tag);
    if (className) item.className = className;
    if (text !== undefined) item.textContent = text;
    return item;
  };
  const playIcon = className => {
    const wrapper = element('span', className);
    wrapper.setAttribute('aria-hidden', 'true');
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', 'M8 5v14l11-7z');
    path.setAttribute('fill', 'currentColor');
    svg.append(path);
    wrapper.append(svg);
    return wrapper;
  };
  const normalise = value => String(value).toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/æ/g, 'ae').replace(/ø/g, 'o');
  const uniqueVideos = entries => [...new Map(entries.map(video => [video.id, video])).values()];
  const thumbnail = id => new URL(`videos/${encodeURIComponent(id)}.jpg`, assetBase).href;
  const portrait = source => source.isCollection ? thumbnail(source.imageVideoId) : new URL(`artists/${encodeURIComponent(source.id)}.jpg`, assetBase).href;
  const watchUrl = (video, source) => {
    const url = new URL('https://www.youtube.com/watch');
    url.searchParams.set('v', video.id);
    if (source) url.searchParams.set('list', source.playlistId);
    return url.href;
  };
  const shortTitle = (video, source) => {
    if (!source || source.isCollection) return video.title;
    const escaped = source.name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    return video.title.replace(new RegExp(`^(?:${escaped}\\s*[—–-]\\s*)+`, 'i'), '');
  };

  function prepareData(data) {
    if (!Array.isArray(data.artists) || !data.artists.length) throw new Error('Artist catalogue unavailable');
    catalogue = data;
    const validVideo = video => /^[a-zA-Z0-9_-]{11}$/.test(video.id) && typeof video.title === 'string';
    for (const artist of data.artists) {
      artist.videos = uniqueVideos(artist.videos.filter(validVideo));
      sourceMap.set(artist.id, artist);
      const option = element('option', '', artist.name);
      option.value = artist.id;
      filter.append(option);
      document.querySelectorAll(`[data-open-artist="${artist.id}"] .artist-meta`).forEach(meta => {
        meta.textContent = `${artist.videos.length} videos · Artist playlist`;
      });
      for (const video of artist.videos) {
        if (!videoMap.has(video.id)) videoMap.set(video.id, {...video, artistIds: [], sourceId: artist.id});
        videoMap.get(video.id).artistIds.push(artist.id);
      }
    }
    if (data.collection) {
      data.collection.isCollection = true;
      data.collection.videos = uniqueVideos(data.collection.videos.filter(video => validVideo(video) && video.channelId === data.channelId));
      sourceMap.set(data.collection.id, data.collection);
      for (const video of data.collection.videos) {
        if (!videoMap.has(video.id)) videoMap.set(video.id, {...video, artistIds: [], sourceId: data.collection.id});
      }
    }
    // Interleave artists for discovery while preserving each playlist's song order.
    const orderedIds = new Set();
    const longestPlaylist = Math.max(...data.artists.map(artist => artist.videos.length));
    for (let index = 0; index < longestPlaylist; index += 1) {
      for (const artist of data.artists) {
        if (artist.videos[index]) orderedIds.add(artist.videos[index].id);
      }
    }
    for (const id of videoMap.keys()) orderedIds.add(id);
    videos = [...orderedIds].map(id => videoMap.get(id));
    if (videos.some(video => !video.artistIds.length)) {
      const option = element('option', '', 'More from Spielbot');
      option.value = 'more';
      filter.append(option);
    }
    document.getElementById('video-controls').hidden = false;
    renderGallery();
    handleRoute();
  }

  function filteredVideos() {
    const query = normalise(search.value.trim());
    return videos.filter(video => {
      if (filter.value === 'more' && video.artistIds.length) return false;
      if (filter.value !== 'all' && filter.value !== 'more' && !video.artistIds.includes(filter.value)) return false;
      const artistText = video.artistIds.map(id => `${id} ${sourceMap.get(id).name}`).join(' ');
      return !query || normalise(`${video.title} ${artistText}`).includes(query);
    });
  }

  function renderGallery() {
    const matches = filteredVideos();
    const shown = matches.slice(0, visibleCount);
    const fragment = document.createDocumentFragment();
    for (const video of shown) {
      const source = sourceMap.get(video.artistIds.includes(filter.value) ? filter.value : video.sourceId);
      const card = element('a', 'video-card');
      card.href = watchUrl(video, source);
      card.dataset.openArtist = source.id;
      card.dataset.videoId = video.id;
      card.setAttribute('aria-label', `Play ${video.title}`);
      const art = element('div', 'video-thumb');
      const image = element('img');
      image.src = thumbnail(video.id);
      image.alt = '';
      image.width = 480;
      image.height = 270;
      image.loading = 'lazy';
      art.append(image);
      if (video.duration) art.append(element('span', 'duration', video.duration));
      const play = playIcon('video-play');
      art.append(play);
      const copy = element('div', 'video-card-text');
      const names = video.artistIds.map(id => sourceMap.get(id).name).join(' + ');
      copy.append(element('p', 'video-artist', names || 'MORE FROM SPIELBOT'));
      copy.append(element('h3', '', shortTitle(video, source)));
      card.append(art, copy);
      fragment.append(card);
    }
    grid.replaceChildren(fragment);
    empty.hidden = matches.length > 0;
    more.hidden = visibleCount >= matches.length;
    more.textContent = `Show ${Math.min(12, Math.max(0, matches.length - shown.length))} more videos`;
    resultsNote.textContent = matches.length ? `Showing ${shown.length} of ${matches.length} videos` : 'No matching videos';
  }

  function routeFor(source, video) {
    return `#artist/${encodeURIComponent(source.id)}${video ? `/video/${encodeURIComponent(video.id)}` : ''}`;
  }

  function openArtist(sourceId, videoId, playNow = false) {
    const source = sourceMap.get(sourceId);
    if (!source || !source.videos.length) return;
    const video = source.videos.find(item => item.id === videoId) || source.videos[0];
    const route = routeFor(source, videoId ? video : null);
    if (!dialog.open) returnFocus = document.activeElement;
    if (location.hash !== route) history.pushState({spielbotDialog: true}, '', route);
    renderDialog(source, video, playNow);
    renderedRoute = location.hash;
  }

  function renderDialog(source, video, playNow) {
    selectedSource = source;
    selectedVideo = video;
    document.title = `${source.name} — Stephen Spielbot Music`;
    document.getElementById('dialog-eyebrow').textContent = source.isCollection ? 'THE COLLECTION' : 'THE ARTIST';
    document.getElementById('dialog-title').textContent = source.name;
    document.getElementById('dialog-description').textContent = `${source.videos.length} videos. Find a song. Press play.`;
    const image = document.getElementById('dialog-portrait');
    image.src = portrait(source);
    image.alt = `${source.name} artwork`;
    document.getElementById('dialog-youtube').href = source.playlistUrl;
    document.getElementById('dialog-count').textContent = `${source.videos.length} videos in this playlist`;
    document.getElementById('share-fallback').hidden = true;
    share.textContent = 'Copy link';
    const fragment = document.createDocumentFragment();
    source.videos.forEach((item, index) => {
      const row = element('li');
      const button = element('button', 'track');
      button.type = 'button';
      button.dataset.trackId = item.id;
      button.setAttribute('aria-label', `Play ${item.title}`);
      button.setAttribute('aria-current', String(item.id === video.id));
      button.append(element('span', 'track-index', String(index + 1).padStart(2, '0')));
      const art = element('span', 'track-thumb');
      const thumb = element('img');
      thumb.src = thumbnail(item.id);
      thumb.alt = '';
      thumb.loading = 'eager';
      thumb.width = 80;
      thumb.height = 60;
      art.append(thumb);
      const copy = element('span', 'track-copy');
      copy.append(element('span', 'track-title', shortTitle(item, source)));
      if (item.duration) copy.append(element('span', 'track-duration', item.duration));
      button.append(art, copy);
      row.append(button);
      fragment.append(row);
    });
    tracks.replaceChildren(fragment);
    selectVideo(video, playNow);
    if (!dialog.open) {
      document.body.classList.add('dialog-open');
      dialog.showModal();
      document.getElementById('dialog-close').focus();
    }
    dialog.scrollTop = 0;
  }

  function selectVideo(video, playNow) {
    selectedVideo = video;
    document.getElementById('selected-video-title').textContent = shortTitle(video, selectedSource);
    document.getElementById('watch-youtube').href = watchUrl(video, selectedSource);
    tracks.querySelectorAll('[data-track-id]').forEach(track => track.setAttribute('aria-current', String(track.dataset.trackId === video.id)));
    player.replaceChildren();
    if (playNow) {
      const frame = element('iframe');
      const url = new URL(`https://www.youtube-nocookie.com/embed/${video.id}`);
      url.search = new URLSearchParams({listType: 'playlist', list: selectedSource.playlistId, autoplay: '1', playsinline: '1', rel: '0'}).toString();
      frame.src = url.href;
      frame.title = `${video.title} — YouTube player`;
      frame.allow = 'autoplay; encrypted-media; picture-in-picture; web-share';
      frame.referrerPolicy = 'strict-origin-when-cross-origin';
      frame.allowFullscreen = true;
      player.append(frame);
      document.getElementById('dialog-status').textContent = 'Playback controls are in the video player.';
    } else {
      const poster = element('div', 'player-poster');
      const art = element('img');
      art.src = thumbnail(video.id);
      art.alt = `${video.title} artwork`;
      const play = element('button', 'player-start');
      play.type = 'button';
      const symbol = playIcon('player-start-symbol');
      play.append(symbol, element('span', '', 'Play playlist'));
      play.addEventListener('click', () => selectVideo(selectedVideo, true));
      poster.append(art, play);
      player.append(poster);
      document.getElementById('dialog-status').textContent = 'Choose a song and press play.';
    }
  }

  function closeView() {
    player.replaceChildren();
    selectedSource = null;
    selectedVideo = null;
    renderedRoute = '';
    document.title = pageTitle;
    document.body.classList.remove('dialog-open');
    if (dialog.open) dialog.close();
    if (returnFocus && document.contains(returnFocus)) returnFocus.focus({preventScroll: true});
    returnFocus = null;
  }

  function requestClose() {
    closeView();
    if (location.hash.startsWith('#artist/')) {
      if (history.state && history.state.spielbotDialog) history.back();
      else history.replaceState(null, '', '#artists');
    }
  }

  function handleRoute() {
    if (!catalogue) return;
    if (renderedRoute === location.hash && dialog.open) return;
    const match = location.hash.match(/^#artist\/([a-z0-9-]+)(?:\/video\/([a-zA-Z0-9_-]{11}))?$/);
    if (!match) { if (dialog.open) closeView(); return; }
    const source = sourceMap.get(match[1]);
    if (!source || !source.videos.length) return;
    const video = source.videos.find(item => item.id === match[2]) || source.videos[0];
    if (!dialog.open) returnFocus = document.activeElement;
    renderDialog(source, video, false);
    renderedRoute = location.hash;
  }

  document.addEventListener('click', event => {
    const link = event.target.closest('a[data-open-artist]');
    if (!link || !catalogue || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    if (!sourceMap.has(link.dataset.openArtist)) return;
    event.preventDefault();
    openArtist(link.dataset.openArtist, link.dataset.videoId, Boolean(link.dataset.videoId));
  });
  tracks.addEventListener('click', event => {
    const track = event.target.closest('[data-track-id]');
    if (!track || !selectedSource) return;
    const video = selectedSource.videos.find(item => item.id === track.dataset.trackId);
    if (!video) return;
    history.replaceState(history.state, '', routeFor(selectedSource, video));
    renderedRoute = location.hash;
    selectVideo(video, true);
  });
  document.getElementById('dialog-close').addEventListener('click', requestClose);
  dialog.addEventListener('cancel', event => { event.preventDefault(); requestClose(); });
  dialog.addEventListener('click', event => {
    if (event.target !== dialog) return;
    const bounds = dialog.getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) requestClose();
  });
  window.addEventListener('hashchange', handleRoute);
  window.addEventListener('popstate', handleRoute);
  search.addEventListener('input', () => { visibleCount = 12; renderGallery(); });
  filter.addEventListener('change', () => { visibleCount = 12; renderGallery(); });
  more.addEventListener('click', () => {
    const firstNewIndex = visibleCount;
    visibleCount += 12;
    renderGallery();
    const newCard = grid.children[firstNewIndex];
    if (newCard) newCard.focus({preventScroll: true});
  });
  document.getElementById('clear-filters').addEventListener('click', () => {
    search.value = '';
    filter.value = 'all';
    visibleCount = 12;
    renderGallery();
    search.focus();
  });
  share.addEventListener('click', async () => {
    try {
      if (!navigator.clipboard) throw new Error('Clipboard unavailable');
      await navigator.clipboard.writeText(location.href);
      share.textContent = 'Link copied';
      document.getElementById('dialog-status').textContent = 'Artist link copied.';
    } catch {
      const fallback = document.getElementById('share-fallback');
      const input = document.getElementById('share-url');
      input.value = location.href;
      fallback.hidden = false;
      input.focus();
      input.select();
    }
  });

  fetch(new URL('catalogue.json', assetBase), {credentials: 'omit'})
    .then(response => { if (!response.ok) throw new Error('Catalogue request failed'); return response.json(); })
    .then(prepareData)
    .catch(error => {
      console.warn('Music catalogue could not load:', error.message);
      resultsNote.textContent = 'The full video list could not load. Open an artist playlist above to keep listening.';
      const channelLink = element('a', 'button button-lime', 'Watch on YouTube');
      channelLink.href = 'https://www.youtube.com/@SpielbotMusic/videos';
      grid.replaceChildren(channelLink);
    });
})();
