# Stephen Spielbot Music

Standalone Electric Poster music section at **https://luiz.pizzato.cc/spielbotmusic/**.

This is a complete static HTML document without Jekyll front matter. The existing GitHub Pages build copies it and its assets unchanged. It uses the same repository and publishing branch as the main site, with its own styles, navigation and assets.

## Content

- `index.html`: artist gallery, contact information and page structure. The contact email `spielbot@pizzato.cc` is visible in About and the footer without JavaScript.
- `assets/catalogue.json`: verified public YouTube playlist metadata and source provenance.
- `assets/app.js`: video search, artist filtering, shareable artist/video links, accessible playlist dialog and click-to-load YouTube player.
- `assets/styles.css`: responsive Electric Poster design.
- `assets/player-sync.js`: observes native YouTube playlist changes so the video frame follows each selected song.
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

No YouTube credentials or API key are required.

### Automatic daily updates

The [Sync Music Catalogue](https://github.com/pizzato/pizzato.github.io/actions/workflows/sync_music_catalogue.yml) GitHub Actions workflow runs daily at **18:43 UTC** (05:43 Sydney daylight time / 04:43 standard time). GitHub may delay scheduled runs. Use **Run workflow** on `master` for an immediate refresh.

Each run tests the refresh utility, fetches the configured public playlists and the complete channel uploads playlist, refreshes video thumbnails while preserving curated artist portraits, validates the Jekyll build, and commits the generated catalogue and artwork. It then explicitly requests a GitHub Pages build and checks that the public catalogue matches the refreshed file. A green run therefore confirms publication, not just a successful fetch. The workflow uses the repository's built-in `GITHUB_TOKEN` with contents and Pages write permissions; no additional secrets are needed.

Failed or incomplete retrieval is retried up to three times and never publishes partial results. A final failure is visible in GitHub Actions and preserves the existing website. The music job shares a concurrency group with **Sync Site Data** to avoid overlapping automated commits. Successful refresh timestamps are committed as a record of the last check, even when playlist contents are unchanged. Thumbnail URLs include the catalogue version so returning visitors receive updated artwork.

Updates follow both the ten configured artist playlists / Stephen Spielbot Music collection and the channel’s complete public uploads playlist. New uploads appear even before they are added to a curated playlist, under **More from Spielbot**. Videos present in multiple sources appear only once in the gallery, while retaining all their artist memberships. Titles, playlist ordering, additions/removals and video thumbnails refresh automatically. The job reads anonymous public YouTube sources and does not access private uploads.

Playlists whose names start with `Album:` (case-insensitive) are excluded. No Album section is built yet. Ignoring an album playlist does not hide an already-public video that also appears in the uploads list or an existing artist playlist. New artist playlists still require configuration; the job does not automatically import every playlist from the channel.

The artist roster is explicit in the utility. When adding an artist, add its verified playlist entry there and its static card in `index.html`. Public playlist pagination follows YouTube’s web continuation commands with bounded requests and count verification. A changed YouTube page format, invalid continuation, ownership mismatch or incomplete playlist causes a clear failure instead of replacing the catalogue with partial results.

## Playlist behaviour

The artist roster follows the ten artist playlists. Stephen Spielbot Music is a separate collection. Videos verified as belonging to Stephen Spielbot Music but absent from artist playlists appear under **More from Spielbot** in the video browser, including uploads not in the collection. The uploads dialog uses the channel’s real uploads playlist for playback.

The catalogue retains source order and duplicate entries for provenance. The interface removes duplicate video cards and keeps collaborations discoverable under every artist playlist they belong to. Playback uses the original live YouTube playlist; the displayed song list and artwork reflect the most recent catalogue refresh.

Artist and video links use URL fragments, so direct links work on GitHub Pages without additional routes. Opening an artist does not autoplay; pressing play or selecting a video loads the YouTube embed. Portrait videos retain the existing 9:16 thumbnails. Confirmed landscape videos display their complete existing YouTube cover in a 16:9 card spanning two grid columns; on mobile, each occupies a full row. Landscape playlist thumbnails also show the complete image. Each selection defaults the player to its video format, including changes made with YouTube’s native playlist controls. The player’s **Wide view** / **Portrait view** button remains available without reloading the video. Closing the dialog removes the player and its observer. Native YouTube controls and a direct YouTube link remain available.

The explicit `landscapeVideos` set in `assets/app.js` currently contains `ekrWNcVbADs` (Sunday Light) and `R31jtl8Mn6s` (I Forgot What Real Felt Like), verified against their original rendered videos. Add new landscape IDs only after checking their actual format: a missing `short` flag or a wide YouTube thumbnail does not establish landscape playback. No portrait covers are imported. The YouTube IFrame API loads only when playback is requested; if it is unavailable, site-selected tracks still choose their format, while native playlist transitions cannot be observed.

## Validation and deployment

The **Build Site** workflow runs the music catalogue tests and validates Jekyll on pushes and pull requests. GitHub Pages publishes the repository root from `master`; **Sync Music Catalogue** explicitly requests and verifies publication after each daily refresh. The existing main-site data sync remains on its six-hour schedule.

Check the gallery, search/filter, playlist selection, direct artist link, close/Escape, contact email, and mobile layout when making further changes. The page's artist links also work directly on YouTube if JavaScript or catalogue loading is unavailable.

## Artist artwork and branding

The ten artist portraits were generated on 21 November 2026 using both the main character portrait and turnaround sheet in Spielbot Settings → Characters. Each is a 1024 × 1536 JPEG, with identity and wardrobe guided by those references. The complete prompts are recorded in `_tools/artwork-prompts.json`; they were created with the built-in image-generation tool. The original local character assets remain unchanged.

The supplied transparent Stephen Spielbot Music logo is used in the header and footer, with the supplied white-background version used as the page icon. Both are retained in `assets/brand/`.

`--download-thumbnails` refreshes video thumbnails only. An existing valid artist portrait is always preserved; a thumbnail fallback is created only if an artist portrait is absent or invalid.

Video previews use YouTube’s maximum-resolution thumbnails when available, with standard/high-quality and playlist-source fallbacks. The refresh utility rejects missing-size placeholders and preserves a sharper existing image if a higher-resolution source is temporarily unavailable. These local images serve both the song gallery and artist-player preview; actual playback quality is controlled by YouTube.
