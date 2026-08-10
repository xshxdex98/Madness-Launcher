# Madness Launcher

One front end for the Madness games — launch them, tune their settings, and
manage their mods. All six are supported: Midtown Madness 1 and 2, Monster Truck
Madness 1 and 2, and Motocross Madness 1 and 2.

## Giving it to somebody else

```
build_exe.bat        ->  dist\MadnessLauncher.exe
```

Send that **one file**. It contains the launcher, Python and Qt; the recipient
installs nothing and unpacks nothing. About 54 MB.

A one-file build unpacks itself to a temp folder on each run, so the **first
launch takes noticeably longer** — up to half a minute on a cold cache. It is
not hung. Later launches are quick.

It is deliberately a single file rather than a folder. The folder build produced
two identically named executables — the working one in `dist\`, and a
half-built stub in `build\` — and running the stub fails with:

```
Failed to load Python DLL '...uild\madness_launcher\_internal\python310.dll'
LoadLibrary: The specified module could not be found.
```

That is an easy mistake to make and an impossible message to act on. One file
cannot be got wrong, and `build_exe.bat` deletes the intermediate folder anyway
so the stub does not survive the build.

**Do not distribute `run.bat`.** It runs from source and needs Python and
PySide6 already installed. Handing it to players is how you get "I double-click
it and nothing happens" — it used `pythonw`, which has no console, so a missing
dependency produced an error nobody could see. It now checks for both and says
which is missing, but it remains a development tool.

**Always run the built exe once before shipping it.** A windowed build cannot
report a startup failure; it simply fails to appear. That is not hypothetical:
the first working build was broken because `madness_launcher/__main__.py` uses a
relative import, which is right for `python -m madness_launcher` and fatal under
PyInstaller, where the entry script has no parent package. The build therefore
starts from `launcher_main.py`, which imports absolutely.

## Running from source

```
python -m madness_launcher      # or run.bat
```

Requires Python 3.9+ and PySide6 (`pip install -r requirements.txt`).

## What it does today

**Overview.** The first tab is a description of the game with its developer,
publisher, release date, genre and engine, over an optional looping video.

Point it at any video with **Add background video…**; it plays muted on a loop
behind the text, with pause and sound controls. The file is used where it sits
rather than copied, since a decent backdrop clip is not small. Decoding stops
whenever the tab is not the one you are looking at, so a launcher left open in
the background is not quietly chewing a core.

That backdrop draws its frames through a `QVideoSink` and paints them itself
rather than using `QVideoWidget`. A `QVideoWidget` takes a native child window on
Windows and paints over everything Qt puts on top of it, which no amount of
`raise_()` fixes; painting the frames by hand keeps the page's text properly
composited above the video.

Video needs QtMultimedia, which lives in `PySide6-Addons` rather than
`PySide6-Essentials`. Without it the tab falls back to a gradient and says so —
nothing else is affected.

**Locate and verify.** Point it at a game folder or an executable. It checks for
the signature executables and the data archives the game needs, and reports one
of three states: verified, playable but missing data, or not found. The sidebar
carries the same state as a coloured dot.

**Launch.** Pick which executable to run — for Midtown Madness that is Open1560
or the original `MIDTOWN.exe`. The game starts detached, so closing the launcher
never kills it.

**Tune.** Every option on the Options tab maps to a real command-line argument,
each one checked against the Open1560 source rather than only its docs. Only
values you actually change are emitted, so the engine's own defaults keep
applying, and the resulting command line is shown verbatim on the Play tab
before you launch.

Options only make sense for the build that reads them. Most of Midtown
Madness's are Open1560 additions, so selecting the retail `MIDTOWN.exe` shows a
banner saying which ones stop applying. That is driven by `options_apply` on the
executable target, not hardcoded.

Midtown Madness also reads `commandline.txt` from its own folder. The engine
splices that file's arguments in *before* the real command line and lets the
last occurrence win, so **the launcher's settings override that file** where the
two overlap. Its contents are still shown on the Play tab, because it can set
options the launcher does not expose.

The exception is flags with no negation. Open1560 has two kinds of argument:
`cmd_param`, which understands `-noflag`, and plain `argv` scans such as
`ARG("-allcars")`, which latch a variable to true. Once the argument file sets
one of those, nothing on the command line can undo it. Those options are marked
`negatable=False`, the launcher never emits a useless `-noallcars`, and both the
Play tab and the affected option row say the flag is forced on.

**Mod.** Import a `.ar` file, a `.zip`, or a folder, or point the launcher at a
distribution pack and let it index what is already there.

## Chat room

**Chat Room** in the sidebar is an IRC channel dressed as an old-fashioned chat
room: transcript on the left, who's online on the right, type along the bottom.
The sidebar entry carries the current headcount, which is where "how many people
are on the launcher" comes from — it is channel membership, so it counts people
with the launcher's chat open, not every copy running.

On first run the launcher asks for a username; **Settings → Identity** changes it
later, and renames you in the channel if you are connected. Names are claimed,
not registered: the network refuses one already in use by somebody online, and
the launcher then asks for a different one. Nothing is stored server-side and
there is no password.

A short synthesised tone plays when a message arrives from somebody else — never
for your own. **Sound on/off** in the header toggles it and the choice sticks.
The tone is generated at startup (`ui/sound.py`) rather than shipped as an audio
file.

### What to know before using it

The room is **`#madness-launcher` on irc.libera.chat`** — a public network. Anyone
on it can join and read the channel, so the page says so before you connect.
Joining is deliberately manual: the launcher never connects on startup, because
quietly putting someone on a public network is not a reasonable default. Host,
port, channel and TLS are all overridable in `config.json` if you would rather
run it elsewhere.

The channel is not registered with Libera's ChanServ. Until it is, nobody holds
op privileges on it and the name is not reserved.

The client (`chat/irc.py`) is built on `QSslSocket` rather than a background
thread, so everything lands on the GUI thread with no cross-thread marshalling.
It paces outgoing lines at one per 1.2s and splits over-long messages on **byte**
length, both because IRC networks disconnect clients that flood or overrun the
512-byte line limit.

## News

**News** in the sidebar carries two tabs: **Announcements**, mirrored from a
Discord channel, and **Videos**, the latest uploads from channels you follow plus
any video links people have shared in Discord. Cards open in your own browser —
there is no embedded browser and no embedded player, which is what keeps
QtWebEngine out of the build. The sidebar entry shows a count of posts you have
not seen yet, and clears when you open the tab.

### The launcher holds no credentials

Discord has no public way to read a channel's messages. It needs a bot token, and
**a token inside the launcher is a token every user can extract from the `.exe`**
and use to act as your bot. So the launcher reads neither Discord nor YouTube
directly. A relay does that on a machine you control and publishes one plain
JSON file; the launcher only fetches that file. See
[`tools/newsbot/README.md`](tools/newsbot/README.md) for the relay and its
GitHub Actions workflow.

Point the launcher at the feed under **Settings → News**, or set
`DEFAULT_NEWS_URL` in `config.py` to ship a default for everybody. With no URL
set the tab says so rather than sitting empty, and the launcher makes no
outbound request at all.

### What it does with what it fetches

The feed is the only input to the launcher that comes from the open internet, so
`news/model.py` treats every field as hostile: wrong types are dropped, bodies
and titles are truncated, and one unreadable entry costs that entry rather than
the whole feed. Announcement text is HTML-escaped before a deliberately small
subset of Discord's formatting (`**bold**`, `*italic*`, `` `code` ``, links) is
put back. Only `http(s)` URLs are ever opened.

Images are fetched **only** from `i.ytimg.com`, `img.youtube.com`,
`cdn.discordapp.com` and `media.discordapp.net` (`IMAGE_HOSTS`). A thumbnail
pointing anywhere else is dropped rather than requested — otherwise anyone who
could write to the feed could make every launcher in the wild call out to a host
of their choosing.

Fetching is a background errand nobody is waiting for, so it fails quietly: the
feed and its thumbnails are cached under `%LOCALAPPDATA%\MadnessLauncher\cache`,
revalidated with `If-None-Match`, and shown from disk when the network is not
there. A tab full of last week's news beats an empty one. Refreshes are throttled
to one per five minutes; **Refresh** on the page ignores the throttle.

## Working with distribution packs

Community releases ship dozens of mods pre-staged in subfolders, none of them
active — you are expected to copy the `.ar` files into the game folder by hand.
**Scan game folder** on the Mods tab reads those folders and lists everything it
finds, grouped by the folder it came from.

**Which folders those are is discovered, not configured.** Any subfolder holding
archives counts, so a pack can name its folders whatever it likes. This was
originally a hardcoded list per game and it rotted immediately — the same MM2
install went from `1 Additional cars` to `Addon Cars` between two sittings, and
every one of its mods vanished from the launcher. Folders the game itself owns
(`players`, `tools`, `lua`, `dev`, `mods`, and similar) are excluded by name.

A folder counts as one mod when archives sit *directly* inside it. That splits
alternative variants — `YosemiteValley` and `YosemiteValley / For NuHook users`
become two entries, which is what they are — while a mod's own subtrees, such as
a `dev/` tree carrying loose files, stay part of the mod that owns them.

Those payloads are *indexed where they sit*, never copied — a single pack can run
to hundreds of megabytes, and duplicating it into the launcher's library would be
absurd. Only enabling a mod writes anything into the game folder, and disabling
takes it straight back out. Removing an indexed mod drops the launcher's entry
and leaves the pack's own files untouched.

**Load order is preserved exactly.** Pack authors tune the `!` prefixes against
each other, so while you leave a mod's priority alone it deploys under its
original filename, spacing and all (`! ! !oppengine.ar` stays that way). Change
the priority and the launcher takes over, stripping the old prefix and applying
yours. Folders in a staging directory that hold no archives — tool and readme
folders — are skipped rather than listed as mods.

If a pack has had its recommended executable deleted but left the debris behind
(`Open1560.log`, `.map`, `.pdb`, `SDL3.dll` with no `Open1560.exe`), the Play tab
says so, falls back to whatever else is runnable, and offers to put the missing
build back. That is driven by `residue_files` on the executable target.

Packs also sometimes rename the executable outright. Detection therefore accepts
a folder on either evidence — a known executable *or* the full set of data
archives — and the executable dropdown ends in **Choose another executable…** for
whatever the pack actually shipped.

## How the mod manager treats your game folder

The rules it follows, in priority order:

1. **It never destroys a file it did not create.** Anything a mod overwrites is
   copied to a backup store first and restored when the mod is disabled.
2. **It never guesses what to remove.** Enabling writes a receipt listing
   exactly which paths were created and which displaced an original. Disabling
   consults only that receipt.
3. **A disabled mod leaves no trace.** Payloads live outside the game folder
   until enabled.

A failed enable rolls itself back, so a mod is never half-installed. Zip
archives containing absolute or `../` paths are refused rather than extracted.

**Load order.** The engine loads `.ar` archives in name order, so a leading `!`
makes a mod override the base game. The Priority control sets how many `!`
characters are prefixed to the deployed filename — that is why changing priority
re-deploys an enabled mod. The Mods tab warns when enabling a mod would take
over files another enabled mod owns.

## Where things are stored

Everything the launcher owns lives under `%LOCALAPPDATA%\MadnessLauncher`:

```
config.json      game paths, launch options, enabled mods
branding/        the sidebar logo, copied from whatever you chose
mods/<game>/     imported mod payloads and their receipts
backups/<game>/  original files displaced by an enabled mod
icons/           small glyphs painted at startup for the theme
cache/           the last news feed fetched, and its thumbnails
```

Nothing is written into a game folder except by the mod manager. Removing that
one directory resets the launcher completely.

## Adding another game

A game is data, not code. Write a `GameDef` (see `games/mm1.py`) and add it to
`GAMES` in `games/registry.py`; the UI, detection, launching and mod manager all
work off that definition. The pieces are:

| Field | Purpose |
| --- | --- |
| `signature_files` | any one of these identifies the folder as this game |
| `data_files` | expected data; missing ones become a warning, not a block |
| `exe_targets` | the launchable executables, preferred first |
| `options` | launch settings, each mapped to a real argument |
| `mod_spec` | archive extensions, load-order prefix, and staging folders |
| `args_file` | a file the engine also reads arguments from, if any |
| `description`, `publisher`, `released`, `genre`, `setting` | Overview-tab copy; all optional |
| `extra_facts` | additional key/value rows for the Overview fact table |

On the executable target, `options_apply` marks a build the option set does not
belong to, and `residue_files` lists what that build leaves behind so a deleted
one can be recognised.

## Your logo

The top of the sidebar is an empty slot until you put an image in it. Click it,
or use **Settings → Sidebar logo**, and pick a PNG, JPEG, BMP, GIF, WebP, ICO or
SVG. It scales to the sidebar width, keeps its aspect ratio, and is capped at
116px tall, so wide wordmarks and square badges both sit correctly.

The image is copied into `branding/` under the launcher's data folder rather than
referenced where it sits — moving or deleting the original afterwards will not
blank the sidebar. Files that claim to be an image but cannot be decoded are
rejected on the spot rather than leaving a broken slot.

## Look

The shell is deliberately restrained — flat surfaces separated by lightness and a
hairline border, no chrome. The palette is a navy-tinted greyscale rather than a
neutral one, and headings are set in the game's own Gill Sans when a configured
copy ships the font (`GIL_____.TTF`); body text stays on the system UI font,
which holds up far better at 12–13px. With no game configured, or a copy without
the fonts, it falls back cleanly. Each game carries its own accent colour, so the
shell recolours as you move between titles.

Boolean options emit `-name` / `-noname`; ints and choices emit `-name value`.
If a game does not follow that convention, that is the one place to extend —
`build_args` in `games/base.py`.

### Games with nothing to configure and nothing to scan

Not every game has a settings file or an archive format, and the honest thing is
to say so rather than fake a tab. Both Motocross games keep no editable settings —
Motocross Madness 2's `mcm2_profile.json` holds video card capability profiles
and controller GUIDs as raw registry blobs, not anything a player would tune.
Motocross Madness keeps no settings at all —
its registry keys hold install metadata, nothing a player would change — so it
declares no options and the Options tab explains why instead of sitting empty.

It also has no archives and no load-order list: tracks are sets of loose files
(`stadiums/<name>.{scn,slt,tga}`, `teraform/<category>/<name>.{dat,scn,tga,trn}`).
With no manifest, a stock track and an added one are indistinguishable on disk,
so `scan_staging=False` and the scan is a **hard gate** rather than a hidden
button — otherwise a scan would offer the entire base game for deletion. Mods are
imported explicitly and tracked by receipt, so a mod folder mirroring the game's
own layout installs into the right subfolders and reverts cleanly.

### Loose content that has to land in the right folder

The Motocross games have no archives, so a downloaded course is a bare `.env` or
`.scn` file. Nothing in it says which discipline it belongs to — only the person
who downloaded it knows whether it is Supercross or Baja — and putting it in the
game folder leaves the game unable to find it at all.

So when a single file is imported for a game declaring `content_dirs`, the
launcher asks where it goes, offering the folders that **already hold content of
that kind**. Those are discovered from disk rather than hardcoded, so a copy with
extra discipline folders offers those too. The choice is stored on the mod, so
enabling and disabling both use it.

A folder-shaped mod is untouched by this: it already carries its own layout, and
its paths are honoured as they are.

### Games that demand administrator

Windows records per-executable compatibility settings, and one of them —
`RUNASADMIN` — makes an ordinary `CreateProcess` fail outright with
ERROR_ELEVATION_REQUIRED. Monster Truck Madness 2 has it set on this machine, so
launching it produced "the requested operation requires elevation" and nothing
else.

The launcher reads those settings (`launch.compatibility_layers`) and shows them
under the executable picker, so a UAC prompt is expected rather than a surprise.
If a launch is refused for elevation it retries through `ShellExecuteEx` with the
`runas` verb, which raises the prompt properly. Declining the prompt gives a
message saying so, and pointing at the checkbox that causes it.

The flag is honoured rather than worked around: somebody set it deliberately, and
a launcher quietly stripping compatibility settings off a game would be worse
than an extra click.

### Config files that are not valid UTF-8

These files were written by 1990s tools and contain whatever bytes those tools
produced. Monster Truck Madness 2's `pod.ini` names a track
`S+reaMII_C¬razyT¬aiN.pod` — byte 0xAC, which is not valid UTF-8 at all.

Decoding that with `errors="replace"` turns the byte into U+FFFD, and writing
the file back encodes U+FFFD as three different bytes. The entry then names a
file that does not exist and the game silently loses the track — from toggling
some unrelated mod. So `textfile.py` tries UTF-8 and falls back to latin-1,
which maps every byte 0-255 and back unchanged, and remembers which was used so
the file is written the way it was read. Round-tripping the bytes matters far
more than interpreting them, since only ASCII filenames are ever compared.

### Load order kept in a list file

Not every engine encodes load order in filenames. Monster Truck Madness reads
`pod.ini` — a count on the first line, then one archive path per line, in load
order. A game declaring `order_file` gets that treatment: enabling a mod adds a
line rather than renaming anything.

Because those paths are relative to the game folder, **an archive already inside
the game is referenced where it sits** and nothing is copied at all. Only a mod
imported from outside gets copied in first, then listed by name. Disabling
removes exactly the lines that were added; the count stays in step, and an
enable-then-disable cycle leaves the file byte-identical.

That also makes "enabled" knowable for archives the launcher has never touched.
A `.POD` loose in the game folder is a mod that is simply switched off if
`pod.ini` does not name it — so those are indexed too, under **Game folder**, and
one the game is already loading is shown as installed rather than offered as
available. Elsewhere that inference is impossible: a stray `.ar` beside
`MIDTOWN.exe` could equally be base game data or a mod somebody deployed by hand,
so root archives are only indexed for games with a list file.

### Settings a game cannot actually honour

Some settings will take any value and then break the game. Monster Truck Madness
stores its cockpit as pre-rendered artwork per screen height — `ART\PBIG200.RAW`,
`PBIG400`, `PBIG480` and their side and rear views, inside `TRUCK.POD`. There is no
artwork at any other height, so setting one produces *"Unable to open cockpit
file"* on load. The supported modes are 320x200, 320x400 and 640x480, and nothing
in the game says so.

An option can therefore declare `valid_values` and `invalid_help`. Anything
outside the set is called out on the Options tab, naming the current value and
what it will do. That matters because the game writes these itself: run it once
on a modern display and it will happily save a resolution it cannot render.

### Config that points at where the game used to be

Installers of this era wrote **absolute** paths into their config files, so
moving a game folder can leave it pointing at somewhere that no longer exists. A
game can declare `path_settings` — config keys that must point back into its own
folder — and the launcher offers **Repair paths** when any are stale.

An empty value is left alone rather than "repaired": Monster Truck Madness clears
`CDROMPath` itself on a hard-disk install, and filling it back in would be
inventing a setting the game deliberately blanked.

### Options that live in a config file

Not every game is configured on the command line. Midtown Madness 2's retail
executable is packed and exposes no usable argument surface; the community
configures it through MM2Hook's `mm2hook.ini` instead. An option carrying an
`ini_section` is read from and written to the game's `options_file` rather than
emitted as an argument, and the Options tab shows its `[Section] · Key` in place
of a flag.

`inifile.py` does that editing, and deliberately does not use `configparser`,
which discards comments and reformats wholesale. `mm2hook.ini` documents every
one of its settings inline, with defaults — handing that back stripped would
destroy the only documentation the user has. Instead one line's value span is
rewritten and everything else, including CRLF endings and comment alignment,
comes back byte-for-byte. Saving with nothing changed produces an identical file.

## Layout

```
madness_launcher/
  app.py         entry point
  config.py      persistent state, written atomically
  detect.py      folder identification and verification
  launch.py      building and starting the process
  mods.py        mod library, install receipts, backups
  paths.py       every location the launcher writes to
  games/         one module per game definition
  chat/          the IRC client behind the chat room
  news/          feed model, fetcher and thumbnail cache
  ui/            theme, widgets, and the pages
tools/newsbot/   the relay that publishes the news feed
```

## Status

Midtown Madness is complete: detection, launching, the full option set, and the
mod manager. The other five titles are placeholders in the sidebar until their
definitions are written.
