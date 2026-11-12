# Third-party notices

## yt-dlp

This project bundles the pure-Python [yt-dlp](https://github.com/yt-dlp/yt-dlp)
package in `vendor/yt_dlp` (version 2026.10.26 at packaging time).

yt-dlp is released under the **Unlicense**. Its source and license text are
available at <https://github.com/yt-dlp/yt-dlp>.

## FFmpeg

FFmpeg is **not** bundled with this project. The application only invokes a
locally installed `ffmpeg` executable to merge video/audio streams and convert
audio formats. FFmpeg is a separate program with its own license (typically
GPL or LGPL, depending on the build). See <https://ffmpeg.org/legal.html>.

## Icons and interface

All interface icons are inline SVG created for this project. No external icon
fonts or JavaScript libraries are loaded by the page.
