<div align="center">

# 🔭 Dwarf2Siril

**Point it at your DWARF 3. Get back a Siril project that stacks.**

Several nights of the same target, combined into one stack — automatically.

[![Python](https://img.shields.io/badge/python-3.10%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Windows-0078D6?logo=windows&logoColor=white)](#-installation)
[![Tests](https://img.shields.io/badge/tests-138%20passing-brightgreen)](#tests)
[![Siril](https://img.shields.io/badge/Siril-1.4%2B-orange)](https://siril.org/)
[![Dependencies](https://img.shields.io/badge/dependencies-1-lightgrey)](#from-source)

</div>

<!-- Drop a screenshot of the app at docs/screenshot.png and uncomment:
<div align="center">
  <img src="docs/screenshot.png" alt="Dwarf2Siril picking sessions to stack" width="820">
</div>
-->

## ✨ Highlights

- **One file, one double-click.** A 46.5 MB `.exe` with no Python, no `pip`, no
  command line. Opens in about three seconds.
- **Several nights, one stack.** It finds sessions of the same target shot at
  the same settings and combines them, which is the whole reason it exists.
- **It reads the frames, not the folder names.** Exposure, gain, binning,
  filter and EQ mode come from each frame's own FITS header.
- **Darks matched for you**, on exposure, gain and binning — with a sane
  fallback to the DWARF's own master when nothing matches.
- **Bad frames dropped automatically.** Cloud, wind and poor seeing, measured
  against the session's own median rather than a fixed number.
- **Your card is only ever read.** Nothing is moved, renamed or deleted on it.
- **EQ *and* alt-az.** Both stack. EQ is the better way to shoot and the app
  says so, but an alt-az session is not a write-off.
- **It explains itself.** Every refusal names the field that disagreed; every
  build leaves a `build_summary.txt` you can still read months later.

## 🔭 Overview

A [DWARF 3](https://dwarflab.com/) smart telescope writes a folder per session:
the individual sub-exposures, its own live-stacked result, some previews, and a
`shotsInfo.json`. [Siril](https://siril.org/) is the free stacking program most
people move to when they outgrow that live stack. Getting from one to the other
by hand means sorting frames, finding the matching darks, building a folder
layout Siril expects, and writing a script — every single time, for every
target, for every night.

Dwarf2Siril is that job, done for you. Point it at the card, tick the sessions
you want, and it hands back a Siril project that is ready to stack — or stacks
it for you, with Siril's log streaming into the window as it goes.

<details>
<summary><b>What it actually does, in five steps</b></summary>

1. You point it at your DWARF 3 drive.
2. It finds every session and dark set on the card, reading each frame's own
   FITS header for the truth about exposure, gain, binning, filter and EQ mode.
3. It groups sessions of the same target that were shot at the same settings,
   so two nights on one object arrive as a single stack.
4. It matches your dark frames to your lights on exposure, gain and binning.
5. It builds a Siril working folder — `lights/`, `darks/`, `masters/`,
   `process/` — and writes a `.ssf` script that makes the master dark,
   calibrates, registers and stacks.

It refuses to merge sessions that disagree, and tells you which field differs
rather than just failing.

</details>

<details>
<summary><b>Where it sits</b></summary>

It is a **preparer**, not a stacker and not an editor. Siril does the actual
arithmetic; Dwarf2Siril decides what goes in and writes the script. That split
is deliberate — it means you can always take the generated `.ssf`, read it, and
run it yourself without this app in the loop.

It is Windows-first because that is where the DWARF's card ends up for most
people, but nothing in the core is Windows-only.

</details>

<details>
<summary><b>Who made it and why</b></summary>

Built for a DWARF 3 owner who was tired of doing the same folder-shuffling
every clear night, and who wanted the two-nights-into-one-stack case to just
work. The unusual amount of explaining in this README is on purpose: the app
makes a lot of judgement calls on your behalf, and you should be able to check
every one of them.

</details>

## 🚀 Usage

### The app

Double-click `Dwarf2Siril.exe`. From source, it is:

```
dwarf2siril-gui
```

**Step 1 — pick your drive.** It looks for drives that hold a DWARF layout and
offers them as one click. If yours is not spotted, `Choose folder...` always
works. Point it at either the drive itself or the `Astronomy` folder inside it;
it works out which you meant.

**Step 2 — choose what to stack.** Sessions are grouped by target. Each group
shows its exposure, gain, binning, IR filter, frame count and total integration
on its face, along with the dark set that was matched to it. Untick any session
you want left out and everything re-checks immediately.

Anything worth knowing is written on the card itself: no matching darks, a
target shot at two different gains, a session the DWARF's own live stacker
rejected frames from.

Groups are laid out in a **reflowing grid** — two or three across depending on
how wide the window is — so you can take in several targets at once and
compare them. Each card is compact by default; **Details** opens the full
breakdown and the per-session tick boxes.

**Step 3 — output and options.** Pick an output folder on the left; the
optional extras are on the right, **all off by default**. Then hit **Prepare**
on the group you want. Each target gets its own subfolder, so one output folder
can hold several projects.

**Step 4 — stack it.** Hit **Stack now in Siril** and it runs, with Siril's log
streaming into the window as it goes. It can be stopped at any point. At the
end it says plainly whether it worked and offers to open the stacked image.

The command line is shown the whole time with a **Copy** button, so you can
always run it yourself instead. If Siril is not installed the app says so,
offers a **Locate Siril...** picker, and still gives you the command.

When it finishes, a **Before and after** panel appears. Drag the divider to
compare any two stages. The previews are downscaled JPEGs saved in `previews/`
next to your `.fit` — your real output is the full-resolution `.fit`, which the
preview never touches.

### The command line

Same engine, three verbs.

```bash
# See what is on the card
dwarf2siril scan D:\

# See how it would group things, and what it would warn about
dwarf2siril plan D:\

# Build a project
dwarf2siril build D:\ --target "C 27" --output "E:\Astro\C 27"

# Build it and stack it in one go
dwarf2siril build D:\ -t "C 27" -o "E:\Astro\C 27" --stack
```

Quote anything containing a space — DWARF targets are named `C 27` and
`IC 1396`.

<details>
<summary><b>Every flag</b></summary>

| Flag | What it does |
| --- | --- |
| `-o`, `--output` | where to build (required) |
| `-t`, `--target` | pick one target, e.g. `"C 27"` |
| `-s`, `--session` | name a session explicitly; repeat to combine |
| `-n`, `--name` | name the stacked result |
| `--allow-no-darks` | build even with no matching darks |
| `--no-dwarf-master` | never fall back to the DWARF's own master dark |
| `--stack` | run Siril on the script once it is built |
| `--siril` | path to `siril-cli`, if it is somewhere unusual |
| `--background` | remove the sky gradient |
| `--platesolve` | plate solve the result |
| `--colour` | photometric colour calibration (implies `--platesolve`) |
| `--denoise` | denoise the result |
| `--star-reduction` | shrink stars (needs StarNet2) |
| `--star-amount N` | how much of the star layer to keep, 0.0–1.0 (default 0.5) |
| `--starnet` | path to `starnet2.exe`, if it is somewhere unusual |
| `--no-previews` | skip the before/after JPEGs |
| `--framing` | `clean` or `whole` — see [Edges](#edges). Left off, each target picks its own |

To combine specific sessions by name instead of letting it group for you:

```bash
dwarf2siril build D:\ ^
  -s "DWARF_RAW_TELE_C 27_EXP_15_GAIN_100_2026-08-12-00-05-34-558" ^
  -s "DWARF_RAW_TELE_C 27_EXP_15_GAIN_100_2026-08-12-01-05-21-155" ^
  -o "E:\Astro\C 27"
```

Everything on, in one command:

```bash
dwarf2siril build D:\ -t "C 5" -o "G:\Astro\C 5" ^
  --background --platesolve --colour --denoise --star-reduction --stack
```

</details>

### What you get back

```
C_27_350x15s_gain100/
  lights/                            every sub from every session in the group
  darks/                             the matched dark frames
  masters/                           master_dark.fit, built by the script
  process/                           Siril's working files
  previews/                          before/after JPEGs, one per stage
  C_27_350x15s_gain100.ssf           the script
  C_27_350x15s_gain100.fit           THE PLAIN STACK - always kept
  C_27_350x15s_gain100_processed.fit the version with your layers applied
  build_summary.txt                  what went into this stack, and from where
```

To run the script yourself later:

```bash
siril-cli -s "E:\Astro\C 27\C_27_350x15s_gain100\C_27_350x15s_gain100.ssf"
```

Or open the `.ssf` from Siril's script menu.

## 📦 Installation

### Just the app

Download `Dwarf2Siril.exe` from the
[Releases page](https://github.com/astroxyz646/dwarf2siril/releases) and
double-click it. That is the whole thing — one 46.5 MB file you can put
anywhere, no Python and no command line.

Windows will warn you on first run because the file is unsigned. **More info**
→ **Run anyway**.

### From source

Python 3.10 or newer.

```bash
pip install "dwarf2siril[gui] @ git+https://github.com/astroxyz646/dwarf2siril"
```

Or, cloned:

```bash
pip install -e ".[gui]"
```

[PySide6](https://pypi.org/project/PySide6/) is the only third-party
dependency, and it is only needed for the GUI — the command line runs on the
standard library alone.

### You also need Siril

[Siril](https://siril.org/) 1.4 or newer does the actual stacking. On Windows
it installs to `C:\Program Files\Siril\bin\siril-cli.exe`, which the app finds
on its own. If it is missing, the app says so plainly rather than failing
halfway through.

**Optional:** [StarNet2](https://www.starnetastro.com/download/) is only needed
for star reduction. Take the command-line ZIP, unpack it anywhere, and use
**Locate StarNet...** in the app once. Everything else works without it.

---

## 🎛️ Optional layers

Applied to the final stacked image, each independently. **All off by default.**
Whatever you enable is applied to a *copy* — the plain stack is always kept
alongside it, so nothing is ever lost.

| Layer | What it does | Needs |
| --- | --- | --- |
| **Remove background gradient** | Models the sky background and subtracts it. Takes out light pollution and corner-to-corner brightness slope. Usually the biggest single improvement, and safe. | Siril only |
| **Plate solve** | Works out where the image is pointing and writes real sky coordinates into the file. | Siril only, works offline |
| **Photometric colour calibration** | Sets colour from the measured brightness of known stars instead of by eye. | Siril + internet |
| **Denoise** | Siril's NL-Bayes denoiser. Helps most on short total integration. | Siril only |
| **Reduce stars** | Puts the stars back smaller so the target stands out. | StarNet2 |

**Order matters and is handled for you.** Background removal runs before colour
calibration, because Siril itself warns that calibrating an image with a
gradient gives an imprecise result. Plate solving runs before colour
calibration, because colour calibration needs to know what it is looking at.
Star reduction runs last, because it is the only destructive one.

**Star reduction is a taste call, not an improvement.** It changes real data —
the stars in the result are no longer what the sensor recorded. The slider sets
how much of the star layer goes back (50% by default). The plain stack is
always kept.

## 📐 Edges

Frames never cover exactly the same patch of sky. Two things cause it:

- **Alt-az** — without a wedge the sky rotates through the frame as the night
  goes on.
- **Drift** — every mount wanders, and two nights never start pointing
  identically.

Neither is a stacking problem. Alignment solves rotation as well as shift, so
the frames line up and the stars stay round. It is an **edges** problem: the
outside of the frame is covered by fewer frames than the middle, and that shows
up as a visibly noisier band or corner.

It is real and it is measurable. Green-channel background noise on a two-night
C 27 stack, measured in the same three places before and after trimming:

| | Centre | Top edge | Bottom edge |
| --- | --- | --- | --- |
| **Keep the whole picture** (3840×2160) | 4.9 | 4.8 | **13.3** — 2.7× worse |
| **Every pixel equally good** (3550×1936) | 5.1 | 4.9 | **5.2** — even |

Trimming removed the bad band completely. It cost **17% of the frame**, which
is how far apart the two nights started.

**The default depends on why the edges are uneven**, because the two causes
want opposite answers:

- **Drift** (any EQ session, and every multi-session stack) → **trim**. The
  pixels it removes were built from a fraction of the frames; keeping them
  means keeping the worst part of the picture. On a single steady session it
  costs nothing at all.
- **Rotation** (alt-az) → **keep the whole picture**. On a session that rotated
  20.8°, trimming cost **81% of the frame**. Nothing is worth that.

The app only asks when there is a real trade — an alt-az session, or several
sessions being combined. Stack one steady EQ session and you are not asked; the
trim happens anyway and costs you nothing.

**EQ and alt-az sessions of the same target are never merged.** The frames
would align fine, but the alt-az session's rotation would cost the *whole*
combined stack its edges — including the EQ frames that did not need to lose
them. The app refuses and says why, exactly as it does for a gain mismatch.

## 🌥️ Dropping bad frames

Separate from the optional layers, and **on by default**: frames ruined by
cloud, wind or poor seeing are left out of the stack. Siril measures every
frame while aligning them, so this costs nothing extra and needs no other tool.

| Signal | What it means |
| --- | --- |
| Background up, star count down | a cloud went through |
| Weighted FWHM up | soft frame, poor seeing |
| Roundness down | trailed — wind, a knock, a satellite |
| Will not align at all | unusable; dropped automatically |

Thresholds are **k-sigma from the session's own median**, not fixed numbers, so
they adapt to the night. One control with four settings — *Gentle*, *Balanced*
(default), *Strict*, *Off* — rather than four numeric fields.

Afterwards it tells you what went and why in plain English:

> *"280 of 350 frames stacked — 70 dropped. 47 could not be aligned at all. 23
> failed quality checks: 18 trailed, 17 soft, 11 clouded, 4 washed out by sky
> glow."*

A frame often fails more than one check, so those counts overlap and it says
so. The integration time reported is what was **actually used**, not what was
shot. If it would throw away more than 40% of a session it says loudly that
something is wrong rather than quietly handing back four frames.

## 🧠 How it decides things

<details>
<summary><b>EQ vs alt-az</b> — read, not guessed</summary>

Every DWARF light frame carries `EQMODE` in its FITS header, and
`shotsInfo.json` carries `eq`. Both stack; the mode is shown on every session
card and decides whether the framing question is asked at all.

</details>

<details>
<summary><b>Which files are light frames</b></summary>

Only the subs, which always end in their sensor temperature and the `.fits`
extension: `C 27_15s100_Duo-Band_20260812-000629484_32C.fits`. Everything else
in the folder is left alone — the DWARF's own live stack
(`stacked-16_….fits`), its JPG/PNG previews, and anything *you* left there. If
you have processed a session in place, Siril's `.fit` working files,
`Autosave.tif` and the per-frame `.txt` sidecars are all ignored, so a folder
you have already worked in still scans correctly.

</details>

<details>
<summary><b>Where settings come from</b></summary>

FITS header first, then `shotsInfo.json`, then the folder name. The header wins
because the camera writes it per frame.

</details>

<details>
<summary><b>When sessions may be combined</b></summary>

Target, exposure, gain, binning, IR filter and camera must all match. Any
disagreement is refused by name — you get "gain differs: … has 130, … has 70",
not a silent failure. If one target was shot at two settings it becomes two
groups, and each says why.

</details>

<details>
<summary><b>How darks are matched</b></summary>

Exposure, gain and binning. Sensor temperature is deliberately *not* part of
the match: the DWARF 3 is uncooled and drifts several degrees within a single
session, so any exact-temperature rule would reject every dark set the
telescope writes. A large average gap is reported as a warning instead.

**If no darks match**, it falls back to the DWARF's own pre-stacked master from
`CALI_FRAME`, but only if that master was built from at least 5 frames — the
telescope writes some from a single frame, and subtracting one of those adds
more noise than it removes. Whichever source is used is stated plainly in the
UI, in the script header and in `build_summary.txt`. Turn the fallback off with
`--no-dwarf-master`, or the tick box in the app.

</details>

<details>
<summary><b>Getting the frames across</b></summary>

**Prepare** copies your frames off the card into the project folder. Before it
starts it tells you what it is about to move — how many frames and how many
gigabytes — and while it runs it reports both, counting up. Your card is only
ever read.

Where the output happens to sit on the same volume and filesystem as the
source, and that filesystem supports hard links, it links instead of copying —
same files, no second copy of the bytes. That is decided by looking, not asked
about, because a link and a copy leave you with exactly the same project. A
DWARF card is exFAT and removable, so on real hardware it is always a copy.

There used to be a **Link instead of copying** tick box, and a `--copy` flag on
the CLI to match. Both are gone. The tick box could never take effect on a real
card, and its explanation recommended putting the project on the card itself —
the one place it must not go.

</details>

## 🛠️ Development

<details>
<summary><b>Tests</b></summary>

```bash
python -m unittest discover -s tests
```

138 tests, built against a synthetic card that mirrors the real DWARF layout —
spaces in target names, the DWARF's own stack sitting beside the subs, dark
folders with no `shotsInfo.json`.

</details>

<details>
<summary><b>Live reload</b></summary>

Run with `DWARF2SIRIL_DEV=1` and the app watches its own source: saving
`theme.py` restyles the running window instantly with nothing lost, and saving
any other file restarts it and reopens the card you had. Off by default and
absent from the built exe.

```bash
set DWARF2SIRIL_DEV=1
python -m dwarf2siril.gui.app
```

</details>

<details>
<summary><b>Building the .exe</b></summary>

Build on Windows — PyInstaller does not cross-compile.

```bash
pip install PySide6 pyinstaller
python packaging/build_exe.py --clean
```

The result lands in `dist/onefile/Dwarf2Siril.exe`. PyInstaller is a
**build-time** dependency only — nothing in `dwarf2siril` imports it and the
built app does not need it, Python, or pip.

| | one-file (default) | one-folder (`--onedir`) |
| --- | --- | --- |
| Size | 46.5 MB, single file | 116 MB across a folder |
| Opens in | ~3s | ~1s |
| Good for | sending to someone | running often yourself |

One-file is the default because "send me the app" should mean one file. It
unpacks itself to a temp folder on each launch, which is where the extra two
seconds go.

| Flag | What it does |
| --- | --- |
| *(none)* | one-file build → `dist/onefile/Dwarf2Siril.exe` |
| `--onedir` | one-folder build → `dist/onedir/Dwarf2Siril/` |
| `--both` | build both and print the size and build time of each |
| `--clean` | delete `dist/` and `build/` first — do this before a release |

Set `DEBUG_CONSOLE=1` before building to attach a console, which is how you see
a crash that happens before the window opens.

</details>

<details>
<summary><b>Cutting a release</b></summary>

The `.exe` is a build artefact and is not committed. Attach it to a GitHub
release instead:

```bash
python packaging/build_exe.py --clean
git tag v0.1.0
git push origin v0.1.0
gh release create v0.1.0 dist/onefile/Dwarf2Siril.exe ^
  --title "Dwarf2Siril v0.1.0" --notes "First release."
```

</details>

## 🤝 Contributing & feedback

Bug reports and feature requests are welcome on the
[issue tracker](https://github.com/astroxyz646/dwarf2siril/issues). If
something on your card scans wrong, the most useful thing you can attach is the
folder name and the output of:

```bash
dwarf2siril scan D:\
```

If the app made a decision you disagree with, say so — most of the behaviour in
[How it decides things](#-how-it-decides-things) is a judgement call, and a
well-argued case will change it.

## 📚 Further reading

- [Siril documentation](https://siril.readthedocs.io/) — what the generated
  script is actually doing
- [Siril scripting reference](https://siril.readthedocs.io/en/stable/Commands.html)
  — every command in the `.ssf`
- [DWARF Lab](https://dwarflab.com/) — the telescope
- [StarNet2](https://www.starnetastro.com/download/) — star reduction, optional
- [FITS standard](https://fits.gsfc.nasa.gov/fits_standard.html) — the headers
  this reads
