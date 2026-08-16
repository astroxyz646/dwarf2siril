"""Generate the Siril ``.ssf`` script.

Written against Siril 1.4 and verified by running the real ``siril-cli.exe``
1.4.4 on this machine, not against documentation alone.

Two things about the syntax were tested rather than assumed:

* ``cd`` needs DOUBLE QUOTES around a path containing spaces. Unquoted it
  fails with "directory not found". DWARF targets are named "C 27" and
  "IC 1396" and the user picks their own output folder, so spaces are the
  normal case here, not an edge case.
* Only the one absolute ``cd`` at the top carries a user path. Every path
  after it is relative and made of our own space-free folder names, so no
  amount of oddity in the user's output path can reach the rest of the script.
"""

from __future__ import annotations

from .model import (
    FRAMING_ARGUMENT,
    default_framing,
    FRAMING_CLEAN,
    FRAMING_WHOLE,
    SessionGroup,
    format_exposure,
)
from .postprocess import PostOptions
from .quality import QualityFilter

# The output tree, matching the layout Siril's own documentation uses.
LIGHTS_DIR = "lights"
DARKS_DIR = "darks"
MASTERS_DIR = "masters"
PROCESS_DIR = "process"
PREVIEW_DIR = "previews"

# Previews are for looking at, not for keeping. 1600px on the long edge is
# plenty on any screen and keeps them a few hundred KB instead of the 45 MB a
# full-resolution PNG of a DWARF frame comes to.
PREVIEW_MAX_DIM = 1600
PREVIEW_QUALITY = 90

# Suffix for the post-processed image. The plain stack keeps its own name, so
# the user always has the untouched version to go back to.
PROCESSED_SUFFIX = "_processed"

SIRIL_MIN_VERSION = "1.4.0"


def siril_path(path) -> str:
    """Render a path for a Siril script: forward slashes, always quoted.

    Siril accepts forward slashes on Windows and they avoid any argument
    about backslash escaping.
    """
    return '"' + str(path).replace("\\", "/") + '"'


def _preview_lines(label: str, index: int, caption: str) -> list[str]:
    """Snapshot whatever is currently loaded, as a small stretched JPEG.

    autostretch and resample both modify the loaded image, so this is only
    ever emitted straight after the .fit has been saved. The caller reloads
    afterwards for the next step.
    """
    return [
        f"# Preview: {caption}",
        "autostretch",
        f"resample -maxdim={PREVIEW_MAX_DIM}",
        f"savejpg {PREVIEW_DIR}/{index:02d}_{label} {PREVIEW_QUALITY}",
    ]


def _post_processing_lines(
    name: str, post: PostOptions, group=None
) -> list[str]:
    """The optional layers, in the order Siril wants them.

    The order is not arbitrary and is not mine: running pcc on an image with
    a gradient makes Siril itself warn "consider correcting the image
    gradient first", so background removal has to come before colour
    calibration. Plate solving has to precede colour calibration because pcc
    needs to know what it is looking at. Denoise goes late, after the signal
    has been cleaned up but before stars are touched. Star reduction is last
    because it is the only destructive one.
    """
    lines: list[str] = []
    add = lines.append
    working = f"{name}{PROCESSED_SUFFIX}"
    step = 0

    # THE OPTICS THESE FRAMES WERE ACTUALLY SHOT WITH, not the telephoto's.
    # This was hard-coded to 150mm / 2.0um, which is right for the telephoto
    # and wildly wrong for the wide camera at 6.7mm / 2.9um. On a wide-angle
    # session the solver hunted for a 3.4 degree field inside a 46 degree
    # image, failed, and took every layer after it down with it.
    focal = group.focal_length if group is not None else 150.0
    pixel = group.pixel_size if group is not None else 2.0
    solvable = group.can_plate_solve if group is not None else True

    add("")
    add("# ===============================================================")
    add("# Optional layers")
    add("# ===============================================================")
    add(f"# Applied: {', '.join(post.enabled_labels())}")
    add(f"# The plain stack is kept as {name}.fit and is not modified.")
    add(f"# The processed version is saved as {working}.fit.")
    add("")
    add("# Make the working copy up front, in the REQUIRED part of the run.")
    add("# Every optional step below runs in its own Siril -- that is what")
    add("# stops one failing from taking the others down -- and a fresh Siril")
    add("# has nothing loaded. So each step loads this file and saves it back,")
    add("# which also makes the chain self-healing: a step that fails leaves")
    add("# the file at the last good state and the next step carries on from")
    add("# there rather than finding nothing at all.")
    add(f"load {name}")
    add(f"save {working}")

    # The plain stack's snapshot is deliberately NOT taken here, even though
    # this is where it belongs in the story. Siril aborts a script the moment
    # any command fails, and savejpg fails for reasons that have nothing to
    # do with the stack -- a missing folder, a full disk. Taken first, a
    # failed thumbnail would stop every layer from running at all and the
    # user would get no processed image whatsoever. It is the only preview
    # that can be deferred, because the plain stack is kept and can be
    # reloaded at any point, so it is taken at the end instead. Every other
    # preview already runs after its own "save", so the .fit is on disk
    # before any JPEG is attempted.
    step += 1   # keeps its 00_ prefix, and its place in the panel's order

    if post.background_removal:
        add("")
        add("# @@SEGMENT optional Background removal")
        add(f"load {working}")
        add("# --- Background / gradient removal -------------------------")
        add("# RBF models the sky background from sample points and subtracts")
        add("# it. This is what removes light-pollution gradients and the")
        add("# brightening towards one corner.")
        add("subsky -rbf -samples=20 -tolerance=1.0 -smooth=0.5")
        add(f"save {working}")
        if post.previews:
            lines.extend(_preview_lines("background", step, "after background removal"))
            step += 1

    if post.plate_solve and not solvable:
        add("")
        add("# --- Plate solve: SKIPPED ----------------------------------")
        add("# These frames record no pointing at all -- the wide camera")
        add("# writes RA/DEC of 0/0, which is an absence rather than a")
        add("# coordinate. Siril's near solver searches around a starting")
        add("# position, and there is none to give it, so a solve here")
        add("# cannot succeed. Attempting it anyway fails the script and")
        add("# takes every layer after it with it, which is how this was")
        add("# found. Skipped deliberately, and reported rather than hidden.")

    if post.plate_solve and solvable:
        add("")
        add("# @@SEGMENT optional Plate solving")
        add(f"load {working}")
        add("# --- Plate solve -------------------------------------------")
        add("# Works out exactly where this image is pointing. The DWARF 3's")
        add("# focal length and pixel size are fixed and known, and the frames")
        add("# carry RA/DEC, so the solver is seeded rather than searching")
        add("# the whole sky. Solves against Siril's local Gaia catalogue,")
        add("# so it needs no internet.")
        add("#")
        add("# -noflip because by default Siril TURNS THE IMAGE UPSIDE DOWN")
        add("# when it decides the sky is the other way up. The solution is")
        add("# correct either way -- Siril writes a WCS that matches whichever")
        add("# orientation the pixels end up in -- but flipping means the")
        add("# finished picture no longer matches the plain stack beside it,")
        add("# which breaks the before/after view and surprises the user for")
        add("# no benefit. Measured: with -noflip the pixels come out")
        add("# bit-identical to the input, and Siril still accepts the file as")
        add("# solved (pcc runs on it).")
        add(f"platesolve -focal={focal:g} -pixelsize={pixel:g} -noflip")
        add(f"save {working}")

    if post.colour_calibration and not solvable:
        add("")
        add("# --- Colour calibration: SKIPPED ---------------------------")
        add("# It works from the measured brightness of known stars, so it")
        add("# needs the image solved first, and this one cannot be. Left")
        add("# out rather than run and failed.")

    if post.colour_calibration and solvable:
        add("")
        add("# @@SEGMENT optional Colour calibration")
        add(f"load {working}")
        add("# --- Photometric colour calibration ------------------------")
        add("# Sets the colour balance from the measured brightness of known")
        add("# stars in the field, rather than by eye. Needs the image solved")
        add("# first, and needs the internet to fetch the star catalogue.")
        add("pcc")
        add(f"save {working}")
        if post.previews:
            lines.extend(_preview_lines("colour", step, "after colour calibration"))
            step += 1

    if post.denoise:
        add("")
        add("# @@SEGMENT optional Denoising")
        add(f"load {working}")
        add("# --- Denoise -----------------------------------------------")
        add("# Siril's own denoiser (NL-Bayes). Run after the background is")
        add("# flat, so it is not trying to smooth a gradient as though it")
        add("# were noise.")
        add("# -nocosmetic: cosmetic correction belongs at calibration time,")
        add("# on the CFA frames. On a finished RGB stack it has nothing")
        add("# sensible to do.")
        add("denoise -nocosmetic")
        add(f"save {working}")
        if post.previews:
            lines.extend(_preview_lines("denoised", step, "after denoising"))
            step += 1

    if post.star_reduction:
        kept = post.star_amount
        add("")
        add("# @@SEGMENT optional Star reduction")
        add(f"load {working}")
        add("# --- Star reduction ----------------------------------------")
        add("# StarNet separates the image into a starless version and a star")
        add("# mask. Adding the mask back at reduced strength shrinks the")
        add("# stars while keeping them, rather than deleting them outright.")
        add(f"# Keeping {int(kept * 100)}% of the star layer.")
        add("#")
        add("# This one is a taste call and it is destructive to real data:")
        add("# the stars in the result are no longer what the sensor recorded.")
        if post.starnet_path:
            add(f"set core.starnet_exe={siril_path(post.starnet_path)[1:-1]}")
        # StarNet names its two outputs after whatever image is LOADED, and
        # the pixel-math line below refers to them by name. If no earlier
        # layer has saved and reloaded the working file, the loaded image is
        # still the plain stack -- so starnet writes starless_<name> while pm
        # asks for starless_<name>_processed, and the whole script dies with
        # "invalid input image". That is exactly what happened with star
        # reduction as the only layer: no output file at all.
        add(f"save {working}")
        add(f"load {working}")
        add("starnet -stretch")
        # starnet names its outputs after whatever was loaded, and leaves the
        # starless image loaded. The mask is written beside it.
        add(f'pm "$starless_{working}$ + {kept:g}*$starmask_{working}$"')
        add(f"save {working}")
        if post.previews:
            lines.extend(_preview_lines("stars_reduced", step, "after star reduction"))
            step += 1

    if post.previews:
        add("")
        add("# @@SEGMENT optional Previews")
        add(f"load {working}")
        add("# Final side of the before/after pair.")
        lines.extend(_preview_lines("final", 99, "the finished image"))

        add("")
        add("# The 'before' side, taken last on purpose -- see above. Every")
        add("# .fit this script produces already exists by this point, so if")
        add("# writing a JPEG fails here it costs a thumbnail and nothing else.")
        add(f"load {name}")
        lines.extend(_preview_lines("stacked", 0, "the plain stack, before any layer"))

    if post.plate_solve and solvable:
        add("")
        add("# @@SEGMENT optional Coordinates on the plain stack")
        add(f"load {name}")
        add("# --- And the plain stack too -------------------------------")
        add("# The plain stack is the file plenty of people will actually")
        add("# open, so it gets the coordinates as well. Because the solve")
        add("# uses -noflip it changes no pixels at all, so this adds the")
        add("# astrometry to the kept file without altering it.")
        add(f"load {name}")
        add(f"platesolve -focal={focal:g} -pixelsize={pixel:g} -noflip")
        add(f"save {name}")

    add("")
    add(f"# Processed result: {working}.fit")
    return lines


def generate_script(
    group: SessionGroup,
    output_dir,
    stack_name: str | None = None,
    post: PostOptions | None = None,
    quality: QualityFilter | None = None,
    framing: str | None = None,
) -> str:
    """Build the ``.ssf`` for one group.

    Emits master-dark creation, calibration, registration and stacking. If no
    dark set matched, the calibration step is skipped rather than faked, and
    the script says so in a comment where the user will see it.
    """
    name = stack_name or group.suggested_name()
    # Raw darks mean we stack our own master; a CALI_FRAME master is already
    # stacked and is copied into masters/ under the same name, so from the
    # script's point of view the only difference is whether step 1 runs.
    build_master = bool(group.darks)
    has_darks = group.has_calibration
    first = group.sessions[0] if group.sessions else None

    lines: list[str] = []
    add = lines.append

    add(f"# Siril script generated by Dwarf2Siril for {group.display_target}")
    add(f"# Target          : {group.display_target}")
    if first:
        add(f"# Exposure / gain : {format_exposure(first.exposure)} at gain {first.gain}")
        add(f"# Binning         : {first.binning}x{first.binning}")
        add(f"# IR filter       : {first.filter_name or '(none)'}")
        add(f"# Camera          : {first.camera}")
        add(f"# Mount mode      : {group.mount_mode}")
    add(f"# Sessions        : {len(group.sessions)}")
    for session in group.sessions:
        add(f"#   - {session.path.name} ({session.frame_count} frames)")
    add(f"# Light frames    : {group.total_frames}")
    add(f"# Integration     : {group.describe_integration()}")
    add(f"# Calibration     : {group.dark_source}")
    if group.darks:
        for dark in group.darks:
            add(f"#   - {dark.path.name} ({dark.frame_count} frames)")
    elif group.master_dark:
        add(f"#   - {group.master_dark.path.name}")
        add("#     (supplied by the telescope, not built from your own darks)")
    else:
        add("#   NONE MATCHED - calibration is skipped below.")
    add("")
    add(f"requires {SIRIL_MIN_VERSION}")
    add("")

    # The only absolute path in the script. Quoted: verified necessary for
    # paths containing spaces.
    add("# Work from the folder this script's data lives in.")
    add(f"cd {siril_path(output_dir)}")
    add("")

    add("# 16-bit is what the DWARF writes; 32-bit keeps precision through stacking.")
    add("set32bits")
    add("setext fit")
    add("")

    # Everything from here to the stack is REQUIRED: it is the thing the
    # user asked for, and a failure in it is a real failure. The optional
    # layers below each get their own marker, and each runs in its own Siril
    # so that one of them failing cannot take the others -- or this -- with
    # it. See pipeline.py.
    add("# @@SEGMENT required")
    add("")

    if build_master:
        add("# ---------------------------------------------------------------")
        add("# 1. Master dark")
        add("# ---------------------------------------------------------------")
        add(f"cd {DARKS_DIR}")
        add(f"convert dark -out=../{PROCESS_DIR}")
        add(f"cd ../{PROCESS_DIR}")
        add("# Winsorized sigma clipping; no normalisation -- darks must keep")
        add("# their true signal level or they cannot be subtracted.")
        add(f"stack dark rej w 3 3 -nonorm -out=../{MASTERS_DIR}/master_dark")
        add("cd ..")
        add("")
    elif has_darks:
        add("# ---------------------------------------------------------------")
        add("# 1. Master dark: supplied by the telescope, already stacked")
        add("# ---------------------------------------------------------------")
        add(f"# Copied into {MASTERS_DIR}/master_dark.fit from CALI_FRAME.")
        add("# Nothing to build, so calibration below uses it directly.")
        add("")

    add("# ---------------------------------------------------------------")
    add(f"# {'2' if has_darks else '1'}. Lights: convert")
    add("# ---------------------------------------------------------------")
    add(f"cd {LIGHTS_DIR}")
    if has_darks:
        # Debayering happens during calibration, further down.
        add(f"convert light -out=../{PROCESS_DIR}")
    else:
        # No calibration step means nothing else would ever demosaic these.
        # The DWARF's sensor is a Bayer CFA, so without this the whole stack
        # comes out as a single grey layer instead of colour.
        add("# -debayer here because there is no calibration step to do it:")
        add("# the sensor is a Bayer CFA and the result would otherwise be")
        add("# a mono image.")
        add(f"convert light -debayer -out=../{PROCESS_DIR}")
    add(f"cd ../{PROCESS_DIR}")
    add("")

    if has_darks:
        add("# ---------------------------------------------------------------")
        add("# 3. Calibrate against the master dark")
        add("# ---------------------------------------------------------------")
        add("# -cfa       : sensor is a Bayer CFA (RGGB), so cosmetic correction")
        add("#              must respect the mosaic")
        add("# -equalize_cfa : evens the mean level of the CFA channels")
        add("# -debayer   : demosaic on the way out, so registration sees colour")
        add(
            f"calibrate light -dark=../{MASTERS_DIR}/master_dark "
            f"-cc=dark -cfa -equalize_cfa -debayer"
        )
        add("")
        sequence = "pp_light"
        step = "4"
    else:
        add("# No matching darks were found, so there is no calibration step.")
        add("# Shoot darks at the same exposure and gain on the DWARF, then")
        add("# re-run Dwarf2Siril to get a calibrated version of this script.")
        add("")
        sequence = "light"
        step = "2"

    add("# ---------------------------------------------------------------")
    add(f"# {step}. Register")
    add("# ---------------------------------------------------------------")
    add("# Global star alignment lines up every frame from every session.")
    add("# It solves rotation as well as shift, so it handles a rotating")
    add("# field without any separate derotation step.")

    # Frames never cover exactly the same sky: alt-az rotates the field, and
    # every mount drifts, so two nights of the same target start slightly
    # apart. Either way the edges are built from fewer frames than the middle.
    # Framing is therefore decided for EVERY group, not only for alt-az.
    choice = framing or default_framing(group.is_altaz)
    framing_arg = f" -framing={FRAMING_ARGUMENT[choice]}"
    add("#")
    if group.is_altaz:
        add("# Shot in alt-az, so the field rotates between frames.")
        add("# Registration corrects the rotation, but it means the frames")
        add("# do not overlap exactly.")
    elif len(group.sessions) > 1:
        add("# Several sessions, which never start pointing identically, so")
        add("# the frames do not overlap exactly at the edges.")
    else:
        add("# The mount drifts over a session, so the frames do not overlap")
        add("# exactly at the edges.")

    if choice == FRAMING_CLEAN:
        add("# Framing: trimmed to the area every frame covers, so every")
        add("# pixel is built from all of them. When the frames line up this")
        add("# costs nothing; when they do not it removes an edge that was")
        add("# genuinely worse than the rest of the picture.")
    else:
        add("# Framing: the whole frame is kept. The edges are built from")
        add("# fewer frames than the middle and are noisier as a result.")

    if quality is not None and quality.active:
        add("#")
        add("# -2pass measures every frame -- FWHM, roundness, background,")
        add("# star count -- and picks the best reference, without writing")
        add("# out any transformed images yet. The bad frames are then never")
        add("# written at all, which saves both time and a lot of disk.")
        add(f"register {sequence} -2pass")
        add("")
        add("# Drop the frames the weather ruined. Each filter is k-sigma from")
        add("# this session's own median, so it adapts to the night rather")
        add("# than trusting a number that was right on some other night:")
        add("#   wfwhm   soft frames")
        add("#   round   trailed frames (wind, a knock, a satellite)")
        add("#   bkg     raised background: cloud, moon, stray light")
        add("#   nbstars frames that lost their stars, which is cloud")
        add(f"seqapplyreg {sequence} {' '.join(quality.filter_arguments())}{framing_arg}")
    elif framing_arg:
        # No quality filtering, but framing still needs the two-pass form,
        # because -framing is an option of seqapplyreg rather than register.
        add(f"register {sequence} -2pass")
        add(f"seqapplyreg {sequence}{framing_arg}")
    else:
        add(f"register {sequence}")
    add("")

    add("# ---------------------------------------------------------------")
    add(f"# {int(step) + 1}. Stack")
    add("# ---------------------------------------------------------------")
    add("# Additive+scaling normalisation handles the sky-level difference")
    add("# between sessions shot at different times of night.")
    add(
        f"stack r_{sequence} rej w 3 3 -norm=addscale -output_norm -rgb_equal "
        f"-out=../{name}"
    )
    add("")
    add(f"# Result: {name}.fit in the output folder.")
    add("cd ..")

    if post is not None and (post.any_enabled or post.previews):
        lines.extend(_post_processing_lines(name, post, group))

    add("close")
    add("")

    return "\n".join(lines)

