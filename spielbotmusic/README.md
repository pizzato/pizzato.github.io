# Stephen Spielbot Music

Standalone Electric Poster music section at **https://luiz.pizzato.cc/spielbotmusic/**.

This is a complete static HTML document without Jekyll front matter. The existing GitHub Pages build copies it and its assets unchanged. It uses the same repository and publishing branch as the main site, with its own styles, navigation and assets.

## Content

- `index.html`: artist gallery, contact information and page structure. The contact email `spielbot@pizzato.cc` is visible in About and the footer without JavaScript.
- `assets/catalogue.json`: verified public YouTube playlist metadata and source provenance.
- `assets/app.js`: video search, artist filtering, shareable artist/video links, accessible playlist dialog and click-to-load YouTube player.
- `assets/styles.css`: responsive Electric Poster design.
- `assets/artists/` and `assets/videos/`: curated high-resolution artist portraits and local video thumbnails.
- `assets/fonts/`: bundled Archivo Black and Space Grotesk fonts with their OFL licences.
- `_tools/refresh_catalogue.py`: catalogue maintenance utility. The leading underscore keeps this directory out of Jekyll's published output.

## Refresh the catalogue

From the repository root, using Python 3.10 or newer:

```bash
python spielbotmusic/_tools/refresh_catalogue.py --refresh
```

This fetches public playlist HTML, validates completeness and channel ownership, downloads any missing artwork and atomically updates the catalogue. To refresh existing video thumbnails as well (curated artist portraits are preserved):

```bash
python spielbotmusic/_tools/refresh_catalogue.py --refresh --download-thumbnails
```

No credentials or API key are required. There is no new scheduled task. Review and commit the refreshed files through the normal repository workflow.

The artist roster is explicit in the utility. When adding an artist, add its verified playlist entry there and its static card in `index.html`. A changed YouTube page format, incomplete playlist, or pagination causes a clear failure instead of replacing the catalogue with partial results.

## Playlist behaviour

The artist roster follows the ten artist playlists. AI Music Video Network is a separate collection. Videos verified as belonging to Stephen Spielbot Music but absent from artist playlists appear under **More from Spielbot** in the video browser.

The catalogue retains source order and duplicate entries for provenance. The interface removes duplicate video cards and keeps collaborations discoverable under every artist playlist they belong to. Playback uses the original live YouTube playlist; the displayed song list and artwork reflect the most recent catalogue refresh.

Artist and video links use URL fragments, so direct links work on GitHub Pages without additional routes. Opening an artist does not autoplay; pressing play or selecting a video loads the YouTube embed. The gallery and player default to a 9:16 portrait view suited to Shorts. The player’s **Wide view** / **Portrait view** button changes the frame without reloading the video. Closing the dialog removes the player and restores portrait view for the next visit. Native YouTube controls and a direct YouTube link remain available.

## Validation and deployment

The existing **Build Site** workflow validates Jekyll on pushes and pull requests. GitHub Pages publishes the repository root from `master`. No shared layouts, navigation, configuration, dependencies or deployment workflows were changed for this section.

Check the gallery, search/filter, playlist selection, direct artist link, close/Escape, contact email, and mobile layout when making further changes. The page's artist links also work directly on YouTube if JavaScript or catalogue loading is unavailable.

## Artist artwork and branding

The ten artist portraits were generated on 21 November 2026 using both the main character portrait and turnaround sheet in Spielbot Settings → Characters. Each is a 1024 × 1536 JPEG, with identity and wardrobe guided by those references. The complete prompts are recorded in `_tools/artwork-prompts.json`; they were created with the built-in image-generation tool. The original local character assets remain unchanged.

The supplied transparent Stephen Spielbot Music logo is used in the header and footer, with the supplied white-background version used as the page icon. Both are retained in `assets/brand/`.

`--download-thumbnails` refreshes video thumbnails only. An existing valid artist portrait is always preserved; a thumbnail fallback is created only if an artist portrait is absent or invalid.

Video previews use YouTube’s maximum-resolution thumbnails when available, with standard/high-quality and playlist-source fallbacks. The refresh utility rejects missing-size placeholders and preserves a sharper existing image if a higher-resolution source is temporarily unavailable. These local images serve both the song gallery and artist-player preview; actual playback quality is controlled by YouTube.
