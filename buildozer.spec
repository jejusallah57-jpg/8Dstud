[app]
# Basic Info
title = 8DStud
package.name = dstud8
package.domain = org.homies
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,wav,mp3,ttf
version = 0.1

# 8D STUD CORE: These are the critical libraries
# ffpyplayer = Audio Engine | yt-dlp = YouTube Downloader
requirements = python3,kivy==2.3.0,ffpyplayer,pillow,requests,yt-dlp,certifi

# Display & Orientation
orientation = portrait
fullscreen = 0
android.archs = arm64-v8a

# Permissions for the "Homies" to use it
android.permissions = INTERNET, READ_EXTERNAL_STORAGE, WRITE_EXTERNAL_STORAGE, RECORD_AUDIO

# Tooling (Matches GitHub Actions servers)
android.accept_sdk_license = True
android.api = 33
android.minapi = 21
android.ndk = 25b
android.sdk = 33

[buildozer]
log_level = 2
warn_on_root = 1